"""PayPal webhook receiver. The only event that moves a job is the payout item result:
SUCCEEDED -> job PAID_OUT; a failed outcome marks the payout FAILED for a human to look at.
Everything else is acknowledged and ignored."""
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import append_audit
from app.config import get_settings
from app.db import get_db
from app.models import Job, JobStatus, Payout
from app.paypal.client import PayPalClient, get_paypal_client
from app.settlement import PAYOUT_FAILED, PAYOUT_SUCCESS, mark_paid
from app.state_machine import InvalidTransition

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

ITEM_SUCCEEDED = "PAYMENT.PAYOUTS-ITEM.SUCCEEDED"
ITEM_FAILED_EVENTS = {
    "PAYMENT.PAYOUTS-ITEM.FAILED",
    "PAYMENT.PAYOUTS-ITEM.UNCLAIMED",
    "PAYMENT.PAYOUTS-ITEM.RETURNED",
    "PAYMENT.PAYOUTS-ITEM.BLOCKED",
}


@router.post("/paypal")
async def paypal_webhook(
    request: Request,
    db: Session = Depends(get_db),
    paypal: PayPalClient = Depends(get_paypal_client),
) -> dict[str, str]:
    if not get_settings().paypal_webhook_id:
        raise HTTPException(503, "PAYPAL_WEBHOOK_ID is not set")
    body = await request.body()  # the exact bytes PayPal signed
    if not paypal.verify_webhook(request.headers, body):
        raise HTTPException(400, "Invalid webhook signature")

    try:
        event = json.loads(body)
        event_type = event["event_type"]
    except (ValueError, KeyError, TypeError):
        raise HTTPException(400, "Malformed webhook body") from None

    if event_type == ITEM_SUCCEEDED or event_type in ITEM_FAILED_EVENTS:
        resource = event.get("resource") or {}
        batch_id = resource.get("payout_batch_id")
        payout = db.scalar(select(Payout).where(Payout.batch_id == batch_id)) if batch_id else None
        if payout is None:
            # Maybe the webhook beat our own commit of the payout row. A non-2xx makes PayPal
            # redeliver, and /settle's polling covers the case where it never matches.
            log.warning("Webhook %s for unknown payout batch %s", event_type, batch_id)
            raise HTTPException(404, "Unknown payout batch")
        if event_type == ITEM_SUCCEEDED:
            _item_succeeded(db, payout, resource)
        else:
            _item_failed(db, payout, event_type, resource)
    return {"status": "ok"}


def _item_succeeded(db: Session, payout: Payout, resource: dict) -> None:
    if payout.status == PAYOUT_SUCCESS:
        return  # a redelivery, or /settle's polling got there first
    try:
        payout.item_id = resource.get("payout_item_id") or payout.item_id
        mark_paid(db, payout)
        db.commit()
    except InvalidTransition:
        # Polling marked it paid between our read and write.
        db.rollback()
        job = db.get(Job, payout.job_id)
        if JobStatus(job.status) is not JobStatus.PAID_OUT:
            raise
    except Exception:
        db.rollback()
        raise


def _item_failed(db: Session, payout: Payout, event_type: str, resource: dict) -> None:
    if payout.status == PAYOUT_FAILED:
        return  # redelivery
    payout.status = PAYOUT_FAILED
    payout.item_id = resource.get("payout_item_id") or payout.item_id
    append_audit(db, job_id=payout.job_id, actor="paypal", event="PAYOUT_FAILED", payload={
        "event_type": event_type, "payout_id": payout.id, "batch_id": payout.batch_id,
        "item_id": payout.item_id, "transaction_status": resource.get("transaction_status"),
        "errors": resource.get("errors"),
    })
    db.commit()

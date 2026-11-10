import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import append_audit
from app.cleaners import day_is_claimed_by_another
from app.db import get_db
from app.models import Job, JobStatus, Payment
from app.paypal.client import PayPalClient, PayPalError, get_paypal_client
from app.schemas import JobOut
from app.state_machine import InvalidTransition, transition

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/jobs/{job_id}/paypal", tags=["paypal"])


class OrderOut(BaseModel):
    order_id: str


class AuthorizeIn(BaseModel):
    order_id: str


def _get_job(db: Session, job_id: uuid.UUID) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return job


def _get_payment(db: Session, job_id: uuid.UUID) -> Payment | None:
    return db.scalar(select(Payment).where(Payment.job_id == job_id))


def _require_cleaner_still_free(db: Session, job: Job) -> None:
    """An unpaid job stops holding its cleaner after 30 minutes, so someone else may have booked the day since.
    Check before any PayPal call so this customer is never charged for a day that is gone."""
    if day_is_claimed_by_another(db, job):
        raise HTTPException(409, "This cleaner was booked by someone else for that day. Please book again.")


@router.post("/order", response_model=OrderOut)
def create_order(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    paypal: PayPalClient = Depends(get_paypal_client),
) -> OrderOut:
    job = _get_job(db, job_id)
    if job.status != JobStatus.BOOKED.value:
        raise HTTPException(409, f"Job is {job.status}; an order can only be created for a BOOKED job")

    existing = _get_payment(db, job.id)
    if existing:
        return OrderOut(order_id=existing.order_id)
    _require_cleaner_still_free(db, job)

    try:
        order = paypal.create_order(job_id=job.id, amount=job.amount, currency=job.currency)
    except PayPalError as exc:
        raise HTTPException(502, f"PayPal error (debug id {exc.debug_id})") from exc

    db.add(Payment(job_id=job.id, order_id=order.id, status="ORDER_CREATED"))
    append_audit(
        db,
        job_id=job.id,
        actor="system",
        event="PAYPAL_ORDER_CREATED",
        payload={"order_id": order.id, "amount": job.amount, "currency": job.currency},
    )
    try:
        db.commit()
    except IntegrityError:
        # A concurrent request stored an order first. PayPal-Request-Id is derived from the job,
        # so both calls got the same order; return the stored one.
        db.rollback()
        existing = _get_payment(db, job.id)
        if existing is None:
            raise
        return OrderOut(order_id=existing.order_id)
    return OrderOut(order_id=order.id)


@router.post("/authorize", response_model=JobOut)
def authorize(
    job_id: uuid.UUID,
    body: AuthorizeIn,
    db: Session = Depends(get_db),
    paypal: PayPalClient = Depends(get_paypal_client),
) -> Job:
    job = _get_job(db, job_id)
    payment = _get_payment(db, job.id)
    if payment is None:
        raise HTTPException(409, "No PayPal order exists for this job")
    if body.order_id != payment.order_id:
        raise HTTPException(400, "order_id does not match the order for this job")

    if job.status == JobStatus.AUTHORIZED.value and payment.authorization_id:
        return job  # repeat call: already done, don't call PayPal again
    if job.status != JobStatus.BOOKED.value:
        raise HTTPException(409, f"Job is {job.status}; only a BOOKED job can be authorized")
    _require_cleaner_still_free(db, job)

    # The PayPal call runs outside any row lock; transition() locks the job only for the write.
    try:
        auth = paypal.authorize_order(payment.order_id)
    except PayPalError as exc:
        append_audit(
            db, job_id=job.id, actor="system", event="PAYPAL_AUTHORIZE_ERROR",
            payload={"order_id": payment.order_id, "http_status": exc.status_code, "debug_id": exc.debug_id},
        )
        db.commit()
        raise HTTPException(502, f"PayPal error (debug id {exc.debug_id})") from exc

    problem = None
    if auth.id is None:
        problem = "PayPal returned no authorization"
    elif auth.status != "CREATED":
        problem = f"Authorization status is {auth.status}"
    elif auth.amount != job.amount or auth.currency != job.currency:
        problem = f"Authorized {auth.amount} {auth.currency}, expected {job.amount} {job.currency}"
    if problem:
        append_audit(
            db, job_id=job.id, actor="system", event="PAYPAL_AUTHORIZE_REJECTED",
            payload={
                "order_id": payment.order_id, "authorization_id": auth.id,
                "authorization_status": auth.status, "reason": problem, "debug_id": auth.debug_id,
            },
        )
        db.commit()
        raise HTTPException(402, problem)

    try:
        transition(
            # The PayPal account that approved the order is recorded as the authorizing actor.
            db, job, JobStatus.AUTHORIZED, actor=auth.payer_email or "customer",
            event="PAYPAL_AUTHORIZED",
            payload={
                "order_id": payment.order_id, "authorization_id": auth.id,
                "amount": auth.amount, "currency": auth.currency, "debug_id": auth.debug_id,
                "payer_email": auth.payer_email, "payer_id": auth.payer_id,
            },
        )
        # After transition(): it refreshes the job row, which would discard earlier assignments.
        now = datetime.now(timezone.utc)
        job.authorized_at = now
        payment.authorization_id = auth.id
        payment.authorized_amount = auth.amount
        payment.authorized_at = now
        payment.status = "AUTHORIZED"
        db.commit()
    except InvalidTransition:
        # A concurrent request authorized this job first (same PayPal-Request-Id, same result).
        db.rollback()
        db.refresh(job)
        if job.status == JobStatus.AUTHORIZED.value:
            return job
        raise
    except Exception:
        # PayPal holds the funds but we failed to record it. Log the ID so it can be recovered.
        log.error("Authorization %s for job %s succeeded at PayPal but the DB write failed",
                  auth.id, job.id, exc_info=True)
        db.rollback()
        raise
    return job

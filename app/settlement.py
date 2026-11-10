"""Settlement: moves the money for a job the policy engine has released.

settle() does the next missing step: capture the held funds (RELEASED -> CAPTURED), create the payout
to the cleaner, then mark the job paid once PayPal confirms. It is safe to call repeatedly: the money
calls carry deterministic ids, so a retry can't charge or pay twice. PayPal is called outside any row
lock; transition() locks the job only for the write.
"""
import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import append_audit
from app.config import get_settings
from app.models import Job, JobStatus, Payment, Payout
from app.paypal.client import PayPalClient, PayPalError
from app.state_machine import InvalidTransition, transition

log = logging.getLogger(__name__)

PAYOUT_PENDING = "PENDING"
PAYOUT_SUCCESS = "SUCCESS"
PAYOUT_FAILED = "FAILED"


def settle(db: Session, job: Job, paypal: PayPalClient) -> Job:
    """Do the next missing money step for the job, commit, and return the job (whatever its status)."""
    status = JobStatus(job.status)
    if status is JobStatus.RELEASED:
        if not _capture(db, job, paypal):
            return job
        status = JobStatus.CAPTURED
    if status is JobStatus.CAPTURED:
        payout = db.scalar(
            select(Payout).where(Payout.job_id == job.id).order_by(Payout.id.desc()).limit(1)
        )
        if payout is None:
            _create_payout(db, job, paypal)
        elif payout.status == PAYOUT_PENDING:
            _poll_payout(db, job, payout, paypal)
        elif payout.status == PAYOUT_FAILED:
            # Not retried automatically: the failure may be ambiguous (e.g. UNCLAIMED money can still
            # be claimed), and there is one payout per job. A human has to look.
            log.warning("Job %s payout batch %s is FAILED; not retrying", job.id, payout.batch_id)
    return job


def mark_paid(db: Session, payout: Payout) -> None:
    """The payout reached the cleaner: payout SUCCESS, job CAPTURED -> PAID_OUT. Does not commit."""
    job = db.get(Job, payout.job_id)
    transition(db, job, JobStatus.PAID_OUT, actor="paypal", event="PAYOUT_SUCCEEDED",
               payload={"payout_id": payout.id, "batch_id": payout.batch_id,
                        "item_id": payout.item_id, "amount": payout.amount})
    payout.status = PAYOUT_SUCCESS


def _error(db: Session, job: Job, event: str, payload: dict) -> None:
    append_audit(db, job_id=job.id, actor="system", event=event, payload=payload)
    db.commit()


def _capture(db: Session, job: Job, paypal: PayPalClient) -> bool:
    """Capture the authorization. True when the job is now CAPTURED."""
    payment = db.scalar(select(Payment).where(Payment.job_id == job.id))
    if payment is None or not payment.authorization_id:
        _error(db, job, "CAPTURE_ERROR", {"reason": "no authorization on record"})
        return False
    try:
        capture = paypal.capture_authorization(payment.authorization_id, job.amount, job.currency)
    except PayPalError as exc:
        _error(db, job, "CAPTURE_ERROR", {
            "authorization_id": payment.authorization_id,
            "http_status": exc.status_code, "debug_id": exc.debug_id,
        })
        return False
    if capture.status != "COMPLETED" or not capture.id:
        _error(db, job, "CAPTURE_ERROR", {
            "authorization_id": payment.authorization_id,
            "capture_status": capture.status, "debug_id": capture.debug_id,
        })
        return False

    try:
        transition(db, job, JobStatus.CAPTURED, actor="paypal", event="CAPTURE_COMPLETED",
                   payload={"authorization_id": payment.authorization_id, "capture_id": capture.id,
                            "amount": job.amount, "currency": job.currency,
                            "debug_id": capture.debug_id})
        payment.capture_id = capture.id
        payment.status = "CAPTURED"
        db.commit()
    except InvalidTransition:
        # A concurrent settle already recorded this capture (PayPal returned the same capture to both).
        db.rollback()
        db.refresh(job)
        if JobStatus(job.status) not in (JobStatus.CAPTURED, JobStatus.PAID_OUT):
            log.error("Capture %s for job %s: unexpected status %s after a failed transition",
                      capture.id, job.id, job.status, exc_info=True)
            raise
    except Exception:
        # The customer was charged but we failed to record it. Log the ID so it can be recovered.
        log.error("Capture %s for job %s succeeded at PayPal but the DB write failed",
                  capture.id, job.id, exc_info=True)
        db.rollback()
        raise
    return True


def _create_payout(db: Session, job: Job, paypal: PayPalClient) -> None:
    email = get_settings().paypal_cleaner_email
    if not email:
        _error(db, job, "PAYOUT_ERROR", {"reason": "PAYPAL_CLEANER_EMAIL is not set"})
        return
    try:
        batch = paypal.create_payout(job.id, email, job.amount, job.currency)
    except PayPalError as exc:
        _error(db, job, "PAYOUT_ERROR", {"http_status": exc.status_code, "debug_id": exc.debug_id})
        return
    try:
        db.add(Payout(job_id=job.id, batch_id=batch.batch_id, item_id=batch.item_id,
                      amount=job.amount, status=PAYOUT_PENDING))
        append_audit(db, job_id=job.id, actor="system", event="PAYOUT_CREATED",
                     payload={"batch_id": batch.batch_id, "receiver": email,
                              "amount": job.amount, "currency": job.currency})
        db.commit()
    except IntegrityError:
        # A concurrent settle already recorded the payout (one per job). PayPal's batch id is
        # deterministic, so both requests got the same batch; drop our duplicate rows.
        db.rollback()
        db.refresh(job)
    except Exception:
        # The cleaner may have been paid but we failed to record it. Log the ID so it can be recovered.
        log.error("Payout batch %s for job %s created at PayPal but the DB write failed",
                  batch.batch_id, job.id, exc_info=True)
        db.rollback()
        raise


def _poll_payout(db: Session, job: Job, payout: Payout, paypal: PayPalClient) -> None:
    """Fallback for when the webhook doesn't arrive: ask PayPal whether the item succeeded."""
    try:
        batch = paypal.get_payout_batch(payout.batch_id)
    except PayPalError as exc:
        log.warning("Polling payout batch %s failed: %r", payout.batch_id, exc)
        return
    if batch.item_status != "SUCCESS":
        return
    payout.item_id = batch.item_id or payout.item_id
    mark_paid(db, payout)
    db.commit()

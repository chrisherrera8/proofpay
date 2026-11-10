"""Resolve a job that the policy engine parked in PENDING_APPROVAL."""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.jobs import JOB_LOAD_OPTIONS
from app.db import get_db
from app.models import Approval, Job, JobStatus
from app.paypal.client import PayPalClient, get_paypal_client
from app.schemas import ApprovalDecisionIn, JobOut
from app.settlement import settle_after_release
from app.state_machine import InvalidTransition, transition

router = APIRouter(prefix="/api/jobs/{job_id}", tags=["approvals"])


@router.post("/approval", response_model=JobOut)
def decide_approval(
    job_id: uuid.UUID,
    body: ApprovalDecisionIn,
    db: Session = Depends(get_db),
    paypal: PayPalClient = Depends(get_paypal_client),
) -> Job:
    """approve: PENDING_APPROVAL -> RELEASED, then capture and payout (best effort; /settle retries). deny: PENDING_APPROVAL -> REJECTED (the cleaner can re-clean).

    No auth in the demo; decided_by is free text, so the audit actor is the fixed "admin" and the name goes in the payload.
    """
    job = db.scalar(select(Job).options(*JOB_LOAD_OPTIONS).where(Job.id == job_id))
    if job is None:
        raise HTTPException(404, "Job not found")

    approve = body.decision == "approve"
    try:
        # transition() locks the job row and re-checks the status, so two racing decisions can't both win.
        transition(
            db, job, JobStatus.RELEASED if approve else JobStatus.REJECTED,
            actor="admin", event="APPROVAL_APPROVED" if approve else "APPROVAL_DENIED",
            payload={"decided_by": body.decided_by, "reason": body.reason},
        )
    except InvalidTransition:
        db.rollback()
        raise HTTPException(409, f"Job is {job.status}; only a PENDING_APPROVAL job can be approved or denied") from None

    approval = db.scalar(
        select(Approval).where(Approval.job_id == job.id, Approval.status == "PENDING").order_by(Approval.id.desc()).limit(1)
    )
    if approval is None:  # PENDING_APPROVAL always has one; if not, don't half-apply the decision
        db.rollback()
        raise HTTPException(409, "No pending approval found for this job")
    approval.status = "APPROVED" if approve else "DENIED"
    approval.decided_by = body.decided_by
    approval.decided_at = datetime.now(timezone.utc)
    if body.reason is not None:
        approval.reason = body.reason
    db.commit()
    db.refresh(job)
    if approve:
        settle_after_release(db, job, paypal)
    return job

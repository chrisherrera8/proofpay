"""Job state machine. transition() is the only code path that changes Job.status."""
from typing import Any

from sqlalchemy.orm import Session

from app.audit import append_audit
from app.models import Job, JobStatus

S = JobStatus

TRANSITIONS: dict[JobStatus, set[JobStatus]] = {
    S.BOOKED: {S.AUTHORIZED},
    S.AUTHORIZED: {S.SUBMITTED},
    S.SUBMITTED: {S.VERIFIED},
    S.VERIFIED: {S.RELEASED, S.PENDING_APPROVAL, S.REJECTED},
    S.PENDING_APPROVAL: {S.RELEASED, S.REJECTED},
    S.REJECTED: {S.SUBMITTED},  # re-clean loop
    S.RELEASED: {S.CAPTURED},
    S.CAPTURED: {S.PAID_OUT},
    S.PAID_OUT: set(),
}


class InvalidTransition(Exception):
    def __init__(self, from_status: str, to_status: str):
        super().__init__(f"Cannot move job from {from_status} to {to_status}")
        self.from_status = from_status
        self.to_status = to_status


def transition(
    db: Session,
    job: Job,
    to_status: JobStatus,
    *,
    actor: str,
    event: str,
    payload: dict[str, Any] | None = None,
) -> Job:
    """Move a job to a new status and write the audit row, in the caller's transaction.

    Locks the job row first so concurrent requests can't both pass the check.
    Does not commit.
    """
    db.refresh(job, with_for_update=True)
    from_status = JobStatus(job.status)
    if to_status not in TRANSITIONS[from_status]:
        raise InvalidTransition(from_status.value, to_status.value)

    job.status = to_status.value
    append_audit(
        db,
        job_id=job.id,
        actor=actor,
        event=event,
        from_status=from_status.value,
        to_status=to_status.value,
        payload=payload,
    )
    db.flush()
    return job

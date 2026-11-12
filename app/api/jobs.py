import uuid
from datetime import datetime, time, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from app.audit import append_audit
from app.checklists import CHECKLIST_TEMPLATES
from app.cleaners import active_cleaner_filter, booked_on, touch_cleaner
from app.db import get_db
from app.models import Approval, ChecklistItem, Cleaner, Job, JobStatus, Payment, Payout, Photo, Verification
from app.schemas import JobCreate, JobOut
from app.settlement import PAYOUT_FAILED

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

JOB_LOAD_OPTIONS = (selectinload(Job.checklist_items), selectinload(Job.payment), selectinload(Job.verification),
                    selectinload(Job.decision_event), selectinload(Job.payout), selectinload(Job.cleaner))


@router.post("", response_model=JobOut, status_code=201)
def create_job(body: JobCreate, db: Session = Depends(get_db)) -> Job:
    # Lock the cleaner row so two simultaneous bookings for the same day are checked one after the other:
    # the second waits here, then sees the first job and gets a 409.
    cleaner = db.scalar(
        select(Cleaner).where(Cleaner.id == body.cleaner_id, active_cleaner_filter()).with_for_update()
    )
    if cleaner is None:
        raise HTTPException(404, "Cleaner not found (cleaner data is deleted after 24 hours without use)")
    if db.scalar(select(booked_on(body.service_date)).where(Cleaner.id == cleaner.id)):
        db.rollback()  # release the lock
        raise HTTPException(409, f"{cleaner.name} is already booked on {body.service_date}. Pick another cleaner or date.")

    touch_cleaner(db, cleaner.id)  # committed with the job below
    job = Job(
        status=JobStatus.BOOKED.value,
        customer_name=body.customer_name,
        customer_email=body.customer_email,
        address=body.address,
        service_type=body.service_type,
        cleaner_id=cleaner.id,
        service_date=body.service_date,
        strict_check=body.strict_check,
        # Whole-day booking: scheduled_at is only a display value, noon UTC so it falls on the same calendar day
        # in every common timezone. service_date is what counts.
        scheduled_at=datetime.combine(body.service_date, time(12), tzinfo=timezone.utc),
        amount=body.amount,
        currency=body.currency,
        checklist_items=[
            ChecklistItem(label=label, required=required, position=i)
            for i, (label, required) in enumerate(CHECKLIST_TEMPLATES[body.service_type])
        ],
    )
    db.add(job)
    db.flush()  # assigns job.id
    # Initial state has no from_status, so this bypasses transition() on purpose.
    append_audit(
        db,
        job_id=job.id,
        actor="customer",
        event="JOB_BOOKED",
        to_status=JobStatus.BOOKED.value,
        payload={
            "service_type": job.service_type,
            "cleaner_id": job.cleaner_id,  # an id only: cleaner names and emails never go into the audit log
            "service_date": job.service_date,
            "amount": job.amount,
            "currency": job.currency,
            "strict_check": job.strict_check,
        },
    )
    db.commit()
    db.refresh(job)
    return job


@router.get("", response_model=list[JobOut])
def list_jobs(
    cleaner_id: uuid.UUID,
    status: JobStatus | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[Job]:
    stmt = (
        select(Job).options(*JOB_LOAD_OPTIONS).where(Job.cleaner_id == cleaner_id)
        .order_by(Job.created_at.desc(), Job.id).limit(limit).offset(offset)
    )
    if status:
        stmt = stmt.where(Job.status == status.value)
    touch_cleaner(db, cleaner_id)  # the cleaner is looking at their jobs
    db.commit()
    return list(db.scalars(stmt))


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: uuid.UUID, db: Session = Depends(get_db)) -> Job:
    job = db.scalar(select(Job).options(*JOB_LOAD_OPTIONS).where(Job.id == job_id))
    if job is None:
        raise HTTPException(404, "Job not found")
    return job


# Deleting is only allowed where no customer money is held or in flight: BOOKED (never paid) and PAID_OUT
# (finished and settled). Anywhere between, a PayPal hold or capture would be orphaned. The one exception is a
# CAPTURED job whose payout FAILED: nothing is in flight and settlement never retries it, so it is stuck.
DELETABLE = {JobStatus.BOOKED.value, JobStatus.PAID_OUT.value}


def is_deletable(job: Job) -> bool:
    if job.status in DELETABLE:
        return True
    return job.status == JobStatus.CAPTURED.value and job.payout is not None and job.payout.status == PAYOUT_FAILED


@router.delete("/{job_id}", status_code=204)
def delete_job(job_id: uuid.UUID, db: Session = Depends(get_db)) -> Response:
    """Delete a job and its photos, checks, payment, payout, approvals and checklist. The audit log keeps its
    rows (ids only, no foreign key) and gets a JOB_DELETED row."""
    job = db.scalar(select(Job).where(Job.id == job_id).with_for_update())
    if job is None:
        raise HTTPException(404, "Job not found")
    if not is_deletable(job):
        db.rollback()  # release the lock
        raise HTTPException(409, f"Job is {job.status}; only unpaid (BOOKED), finished (PAID_OUT) or failed-payout jobs can be deleted")
    status = job.status
    for child in (Photo, Verification, Payout, Approval, Payment, ChecklistItem):
        db.execute(delete(child).where(child.job_id == job_id))
    db.expire_all()  # the bulk deletes bypass the ORM's view of the job's relationships
    db.execute(delete(Job).where(Job.id == job_id))
    append_audit(db, job_id=job_id, actor="cleaner", event="JOB_DELETED", from_status=status)
    db.commit()
    return Response(status_code=204)

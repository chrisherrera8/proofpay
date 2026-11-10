import uuid
from datetime import datetime, time, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.audit import append_audit
from app.checklists import CHECKLIST_TEMPLATES
from app.cleaners import active_cleaner_filter, booked_on
from app.db import get_db
from app.models import ChecklistItem, Cleaner, Job, JobStatus
from app.schemas import JobCreate, JobOut

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
        raise HTTPException(404, "Cleaner not found (cleaner data is deleted after 24 hours)")
    if db.scalar(select(booked_on(body.service_date)).where(Cleaner.id == cleaner.id)):
        db.rollback()  # release the lock
        raise HTTPException(409, f"{cleaner.name} is already booked on {body.service_date}. Pick another cleaner or date.")

    job = Job(
        status=JobStatus.BOOKED.value,
        customer_name=body.customer_name,
        customer_email=body.customer_email,
        address=body.address,
        service_type=body.service_type,
        cleaner_id=cleaner.id,
        service_date=body.service_date,
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
        },
    )
    db.commit()
    db.refresh(job)
    return job


@router.get("", response_model=list[JobOut])
def list_jobs(
    status: JobStatus | None = None,
    cleaner_id: uuid.UUID | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[Job]:
    stmt = select(Job).options(*JOB_LOAD_OPTIONS).order_by(Job.created_at.desc(), Job.id).limit(limit).offset(offset)
    if status:
        stmt = stmt.where(Job.status == status.value)
    if cleaner_id:
        stmt = stmt.where(Job.cleaner_id == cleaner_id)
    return list(db.scalars(stmt))


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: uuid.UUID, db: Session = Depends(get_db)) -> Job:
    job = db.scalar(select(Job).options(*JOB_LOAD_OPTIONS).where(Job.id == job_id))
    if job is None:
        raise HTTPException(404, "Job not found")
    return job

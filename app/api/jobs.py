import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.audit import append_audit
from app.checklists import CHECKLIST_TEMPLATES
from app.db import get_db
from app.models import ChecklistItem, Job, JobStatus
from app.schemas import JobCreate, JobOut

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

JOB_LOAD_OPTIONS = (selectinload(Job.checklist_items), selectinload(Job.payment), selectinload(Job.verifications))


@router.post("", response_model=JobOut, status_code=201)
def create_job(body: JobCreate, db: Session = Depends(get_db)) -> Job:
    job = Job(
        status=JobStatus.BOOKED.value,
        customer_name=body.customer_name,
        customer_email=body.customer_email,
        address=body.address,
        service_type=body.service_type,
        scheduled_at=body.scheduled_at,
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
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[Job]:
    stmt = select(Job).options(*JOB_LOAD_OPTIONS).order_by(Job.created_at.desc(), Job.id).limit(limit).offset(offset)
    if status:
        stmt = stmt.where(Job.status == status.value)
    return list(db.scalars(stmt))


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: uuid.UUID, db: Session = Depends(get_db)) -> Job:
    job = db.scalar(select(Job).options(*JOB_LOAD_OPTIONS).where(Job.id == job_id))
    if job is None:
        raise HTTPException(404, "Job not found")
    return job

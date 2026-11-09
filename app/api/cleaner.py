"""Cleaner side: upload before/after photos, submit the job, run the vision check."""
import logging
import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.audit import append_audit
from app.db import get_db
from app.models import Job, JobStatus, Photo, Verification
from app.schemas import JobOut, PhotoOut
from app.state_machine import transition
from app.vision import ImageInput, VisionError, VisionProvider, get_vision_provider

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/jobs/{job_id}", tags=["cleaner"])

MAX_PHOTO_BYTES = 3 * 1024 * 1024  # the site resizes to ~1024px (a few hundred KB); this is a safety cap
MAX_PHOTOS_PER_KIND = 4
EDITABLE = {JobStatus.AUTHORIZED.value, JobStatus.REJECTED.value}


def _sniff(data: bytes) -> str | None:
    """Image type from the file's magic bytes; the Content-Type header is not trusted."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _get_job(db: Session, job_id: uuid.UUID) -> Job:
    job = db.scalar(
        select(Job).options(selectinload(Job.checklist_items), selectinload(Job.payment),
                            selectinload(Job.verifications)).where(Job.id == job_id)
    )
    if job is None:
        raise HTTPException(404, "Job not found")
    return job


@router.get("/photos", response_model=list[PhotoOut])
def list_photos(job_id: uuid.UUID, db: Session = Depends(get_db)) -> list[Photo]:
    _get_job(db, job_id)
    return list(db.scalars(select(Photo).where(Photo.job_id == job_id).order_by(Photo.id)))


async def _raw_body(request: Request) -> bytes:
    # Async only to read the body; no DB work here, so the event loop is never blocked on I/O.
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_PHOTO_BYTES:
        raise HTTPException(413, "Photo is too large")
    return await request.body()


@router.post("/photos", response_model=PhotoOut, status_code=201)
def upload_photo(
    job_id: uuid.UUID,
    kind: str = Query(pattern="^(before|after)$"),
    data: bytes = Depends(_raw_body),
    db: Session = Depends(get_db),
) -> Photo:
    """The request body is the raw image bytes (the site sends the resized JPEG blob)."""
    if not data:
        raise HTTPException(400, "Empty upload")
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(413, "Photo is too large")
    content_type = _sniff(data)
    if content_type is None:
        raise HTTPException(415, "Only JPEG, PNG or WebP photos are accepted")

    job = _get_job(db, job_id)
    if job.status not in EDITABLE:
        raise HTTPException(409, f"Job is {job.status}; photos can only be added to an AUTHORIZED or REJECTED job")
    count = db.scalar(select(func.count()).select_from(Photo).where(Photo.job_id == job.id, Photo.kind == kind))
    if count >= MAX_PHOTOS_PER_KIND:
        raise HTTPException(409, f"At most {MAX_PHOTOS_PER_KIND} {kind} photos per job")

    photo = Photo(job_id=job.id, kind=kind, data=data, content_type=content_type)
    db.add(photo)
    db.flush()
    append_audit(db, job_id=job.id, actor="cleaner", event="PHOTO_UPLOADED",
                 payload={"photo_id": photo.id, "kind": kind, "bytes": len(data)})
    db.commit()
    return photo


@router.get("/photos/{photo_id}")
def get_photo(job_id: uuid.UUID, photo_id: int, db: Session = Depends(get_db)) -> Response:
    photo = db.scalar(select(Photo).where(Photo.id == photo_id, Photo.job_id == job_id))
    if photo is None:
        raise HTTPException(404, "Photo not found")
    return Response(photo.data, media_type=photo.content_type,
                    headers={"Cache-Control": "private, max-age=3600"})


@router.delete("/photos/{photo_id}", status_code=204)
def delete_photo(job_id: uuid.UUID, photo_id: int, db: Session = Depends(get_db)) -> Response:
    job = _get_job(db, job_id)
    if job.status not in EDITABLE:
        raise HTTPException(409, f"Job is {job.status}; photos can no longer be changed")
    photo = db.scalar(select(Photo).where(Photo.id == photo_id, Photo.job_id == job_id))
    if photo is None:
        raise HTTPException(404, "Photo not found")
    db.delete(photo)
    append_audit(db, job_id=job.id, actor="cleaner", event="PHOTO_DELETED",
                 payload={"photo_id": photo_id, "kind": photo.kind})
    db.commit()
    return Response(status_code=204)


def _run_verification(db: Session, job: Job, vision: VisionProvider) -> Job:
    """SUBMITTED -> VERIFIED. The provider call runs outside any row lock; a failure leaves the job SUBMITTED."""
    photos = list(db.scalars(select(Photo).where(Photo.job_id == job.id).order_by(Photo.id)))
    before = [ImageInput(p.data, p.content_type) for p in photos if p.kind == "before"]
    after = [ImageInput(p.data, p.content_type) for p in photos if p.kind == "after"]
    checklist = [i.label for i in job.checklist_items]
    try:
        result = vision.verify(before, after, checklist)
    except VisionError as exc:
        append_audit(db, job_id=job.id, actor="system", event="VERIFICATION_ERROR",
                     payload={"error": str(exc)})
        db.commit()
        raise HTTPException(502, f"Vision check failed: {exc}. The job is still SUBMITTED; retry verification.") from exc

    db.add(Verification(
        job_id=job.id,
        score=Decimal(str(result.score)),
        results={
            "overall_pass": result.overall_pass,
            "items": [i.as_dict() for i in result.items],
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
        },
        model=result.model,
    ))
    transition(
        db, job, JobStatus.VERIFIED, actor="vision", event="VERIFICATION_COMPLETED",
        payload={"model": result.model, "score": result.score, "overall_pass": result.overall_pass,
                 "failed_items": [i.item for i in result.items if i.visible and not i.passed]},
    )
    db.commit()
    db.refresh(job)
    return job


@router.post("/submit", response_model=JobOut)
def submit(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    vision: VisionProvider = Depends(get_vision_provider),
) -> Job:
    """AUTHORIZED (or REJECTED, for a re-clean) -> SUBMITTED, then run the vision check -> VERIFIED."""
    job = _get_job(db, job_id)
    if job.status not in EDITABLE:
        raise HTTPException(409, f"Job is {job.status}; only an AUTHORIZED or REJECTED job can be submitted")
    kinds = set(db.scalars(select(Photo.kind).where(Photo.job_id == job.id)))
    if kinds != {"before", "after"}:
        raise HTTPException(422, "Upload at least one before photo and one after photo first")

    transition(db, job, JobStatus.SUBMITTED, actor="cleaner", event="JOB_SUBMITTED")
    db.commit()
    return _run_verification(db, job, vision)


@router.post("/verify", response_model=JobOut)
def verify(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    vision: VisionProvider = Depends(get_vision_provider),
) -> Job:
    """Retry the vision check for a job stuck in SUBMITTED (the provider failed on submit)."""
    job = _get_job(db, job_id)
    if job.status != JobStatus.SUBMITTED.value:
        raise HTTPException(409, f"Job is {job.status}; only a SUBMITTED job can be verified")
    return _run_verification(db, job, vision)

"""Cleaner sign-up and the roster a customer picks from when booking."""
import datetime as dt
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.cleaners import ensure_default_cleaner, get_active_cleaner, list_cleaners
from app.db import get_db
from app.models import Cleaner
from app.schemas import CleanerAvailability, CleanerCreate, CleanerOut

router = APIRouter(prefix="/api/cleaners", tags=["cleaners"])


@router.post("", response_model=CleanerOut, status_code=201)
def sign_up(body: CleanerCreate, db: Session = Depends(get_db)) -> Cleaner:
    cleaner = Cleaner(name=body.name, paypal_email=body.paypal_email)
    db.add(cleaner)
    db.commit()
    return cleaner


@router.get("", response_model=list[CleanerAvailability])
def roster(
    date: dt.date,
    available: bool = Query(False, description="Only cleaners who are free that day"),
    db: Session = Depends(get_db),
) -> list[dict]:
    """Active cleaners with `available` for `date`. The default cleaner is (re)created here if it is missing."""
    ensure_default_cleaner(db)
    return [
        {"id": c.id, "name": c.name, "is_seed": c.is_seed, "created_at": c.created_at, "available": free}
        for c, free in list_cleaners(db, date)
        if free or not available
    ]


@router.get("/{cleaner_id}", response_model=CleanerOut)
def get_cleaner(cleaner_id: uuid.UUID, db: Session = Depends(get_db)) -> Cleaner:
    cleaner = get_active_cleaner(db, cleaner_id)
    if cleaner is None:
        raise HTTPException(404, "Cleaner not found (sign-ups are deleted after 24 hours)")
    return cleaner

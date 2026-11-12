"""Cleaner sign-up and the roster a customer picks from when booking."""
import datetime as dt
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.cleaners import (CleanerExists, ensure_default_cleaner, get_active_cleaner, list_cleaners, purge_if_due,
                          sign_up_or_resume, touch_cleaner)
from app.db import get_db
from app.models import Cleaner
from app.schemas import CleanerAvailability, CleanerCreate, CleanerOut

router = APIRouter(prefix="/api/cleaners", tags=["cleaners"])


@router.post("", response_model=CleanerOut, status_code=201)
def sign_up(body: CleanerCreate, response: Response, db: Session = Depends(get_db)) -> Cleaner:
    """Create a cleaner, or sign back in to the active one with the same PayPal email (200, name unchanged) when
    this browser already holds it or `confirmed` is set; otherwise 409. Either way the 24-hour clock restarts."""
    try:
        cleaner, created = sign_up_or_resume(
            db, body.name, body.paypal_email, confirmed=body.confirmed, known_id=body.known_id
        )
    except CleanerExists:
        raise HTTPException(409, "An account with this PayPal email already exists. Only continue if it's yours.")
    if not created:
        response.status_code = 200
    return cleaner


@router.get("", response_model=list[CleanerAvailability])
def roster(
    date: dt.date,
    available: bool = Query(False, description="Only cleaners who are free that day"),
    db: Session = Depends(get_db),
) -> list[dict]:
    """Active cleaners with `available` for `date`. Also purges expired cleaners (at most once a minute) and
    (re)creates the default cleaner if it is missing."""
    purge_if_due(db)
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
        raise HTTPException(404, "Cleaner not found (sign-ups are deleted after 24 hours without use)")
    touch_cleaner(db, cleaner.id)
    db.commit()
    return cleaner

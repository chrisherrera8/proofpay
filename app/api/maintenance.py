"""Housekeeping for the demo: delete expired cleaner data. Meant for an external pinger (e.g. a scheduled
GitHub Action); the roster endpoint also purges lazily, so this is optional."""
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.cleaners import purge_expired
from app.config import get_settings
from app.db import get_db

router = APIRouter(prefix="/api/maintenance", tags=["maintenance"])


def require_maintenance_token(authorization: str | None = Header(default=None)) -> None:
    expected = get_settings().maintenance_token
    if not expected:
        raise HTTPException(503, "MAINTENANCE_TOKEN is not set")  # fail closed
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(token.encode(), expected.encode()):
        raise HTTPException(401, "Missing or wrong maintenance token", headers={"WWW-Authenticate": "Bearer"})


@router.post("/purge", dependencies=[Depends(require_maintenance_token)])
def purge(db: Session = Depends(get_db)) -> dict[str, int]:
    return purge_expired(db)

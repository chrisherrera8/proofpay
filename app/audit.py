"""Append-only, hash-chained audit log.

Each row stores prev_hash (the previous row's hash) and its own hash, a SHA-256 over
prev_hash plus the row's fields. Editing or deleting any old row breaks every hash after
it, and verify_chain() reports the first row that no longer matches.
"""
import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import AuditLog

GENESIS_HASH = "0" * 64
# Arbitrary constant key for pg_advisory_xact_lock; serializes writers so the chain stays linear.
_CHAIN_LOCK_KEY = 7_265_001


def _canonical(data: dict[str, Any]) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)


def compute_hash(
    prev_hash: str,
    job_id: uuid.UUID | None,
    actor: str,
    event: str,
    from_status: str | None,
    to_status: str | None,
    payload: dict,
    created_at: datetime,
) -> str:
    body = _canonical(
        {
            "job_id": str(job_id) if job_id else None,
            "actor": actor,
            "event": event,
            "from_status": from_status,
            "to_status": to_status,
            "payload": payload,
            "created_at": created_at.astimezone(timezone.utc).isoformat(),
        }
    )
    return hashlib.sha256((prev_hash + body).encode()).hexdigest()


def append_audit(
    db: Session,
    *,
    job_id: uuid.UUID | None,
    actor: str,
    event: str,
    from_status: str | None = None,
    to_status: str | None = None,
    payload: dict | None = None,
) -> AuditLog:
    """Add a row to the audit log inside the caller's transaction (does not commit)."""
    # Held until the transaction ends, so the next writer sees this row as the latest.
    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _CHAIN_LOCK_KEY})
    prev_hash = db.scalar(select(AuditLog.hash).order_by(AuditLog.id.desc()).limit(1)) or GENESIS_HASH

    # Round-trip through JSON so what we hash is exactly what JSONB stores (Decimals, UUIDs, ...).
    clean_payload = json.loads(_canonical(payload or {}))
    created_at = datetime.now(timezone.utc)
    row = AuditLog(
        job_id=job_id,
        actor=actor,
        event=event,
        from_status=from_status,
        to_status=to_status,
        payload=clean_payload,
        created_at=created_at,
        prev_hash=prev_hash,
        hash=compute_hash(
            prev_hash, job_id, actor, event, from_status, to_status, clean_payload, created_at
        ),
    )
    db.add(row)
    db.flush()
    return row


def verify_chain(db: Session) -> int | None:
    """Return None if the whole chain is intact, else the id of the first bad row."""
    prev_hash = GENESIS_HASH
    for row in db.scalars(select(AuditLog).order_by(AuditLog.id)):
        expected = compute_hash(
            prev_hash, row.job_id, row.actor, row.event, row.from_status, row.to_status,
            row.payload, row.created_at,
        )
        if row.prev_hash != prev_hash or row.hash != expected:
            return row.id
        prev_hash = row.hash
    return None

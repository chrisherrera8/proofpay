import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.audit import GENESIS_HASH, append_audit, verify_chain
from app.models import AuditLog


def _write(db, n):
    for i in range(n):
        append_audit(db, job_id=None, actor="test", event=f"E{i}", payload={"i": i})
    db.commit()


def test_empty_chain_is_valid(db):
    assert verify_chain(db) is None


def test_chain_links_and_verifies(db):
    _write(db, 5)
    rows = db.scalars(select(AuditLog).order_by(AuditLog.id)).all()
    assert rows[0].prev_hash == GENESIS_HASH
    for prev, cur in zip(rows, rows[1:]):
        assert cur.prev_hash == prev.hash
    assert verify_chain(db) is None


def test_payload_with_decimal_and_uuid_hashes_consistently(db, make_job):
    from decimal import Decimal

    job = make_job()
    append_audit(db, job_id=job.id, actor="t", event="E", payload={"amount": Decimal("10.00"), "job": job.id})
    db.commit()
    assert verify_chain(db) is None


def test_update_and_delete_are_blocked_by_trigger(db):
    _write(db, 1)
    for stmt in ("UPDATE audit_log SET actor = 'x'", "DELETE FROM audit_log"):
        with pytest.raises(DBAPIError, match="append-only"):
            db.execute(text(stmt))
        db.rollback()


def test_tampering_is_detected(db):
    _write(db, 4)
    target = db.scalars(select(AuditLog).order_by(AuditLog.id)).all()[1].id
    # Bypass the trigger (as the table owner) to simulate someone editing the table directly.
    db.execute(text("ALTER TABLE audit_log DISABLE TRIGGER audit_log_append_only"))
    try:
        db.execute(text("UPDATE audit_log SET actor = 'attacker' WHERE id = :id"), {"id": target})
        db.commit()
    finally:
        db.execute(text("ALTER TABLE audit_log ENABLE TRIGGER audit_log_append_only"))
        db.commit()
    assert verify_chain(db) == target

import os

# Must run before anything imports app.config: tests only ever touch the "test" schema.
os.environ["DB_SCHEMA"] = "test"

from datetime import datetime, timezone  # noqa: E402
from decimal import Decimal  # noqa: E402

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import SessionLocal, engine  # noqa: E402
from app.models import Job  # noqa: E402

TABLES = (
    "audit_log, approvals, verifications, payouts, photos, payments, checklist_items, mandates, jobs"
)


@pytest.fixture(scope="session", autouse=True)
def _test_schema():
    assert get_settings().db_schema == "test", "refusing to run tests outside the test schema"
    command.upgrade(Config("alembic.ini"), "head")


@pytest.fixture
def db(_test_schema):
    # TRUNCATE doesn't fire the row-level append-only trigger, so it can reset the audit log.
    with engine.begin() as conn:
        assert conn.execute(text("SELECT current_schema()")).scalar() == "test"
        conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
    with SessionLocal() as session:
        yield session
        session.rollback()


@pytest.fixture
def make_job(db):
    def _make(status: str = "BOOKED") -> Job:
        job = Job(
            status=status,
            customer_name="Test Customer",
            customer_email="customer@example.com",
            address="1 Test St",
            service_type="standard_clean",
            scheduled_at=datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc),
            amount=Decimal("10.00"),
            currency="USD",
        )
        db.add(job)
        db.commit()
        return job

    return _make

import os

# Must run before anything imports app.config: tests only ever touch the "test" schema.
os.environ["DB_SCHEMA"] = "test"
# Tests use the local Postgres from docker-compose.yml, never the DATABASE_URL in .env (Neon).
# Set TEST_DATABASE_URL to point them somewhere else.
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://proofpay:proofpay@localhost:5433/proofpay"
)

# Keep a developer's .env payee out of the tests; tests that need a default cleaner set it themselves.
os.environ["PAYPAL_CLEANER_EMAIL"] = ""

from datetime import datetime, timezone  # noqa: E402
from decimal import Decimal  # noqa: E402

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import engine  # noqa: E402
from app.models import Job  # noqa: E402

TABLES = (
    "audit_log, approvals, verifications, payouts, photos, payments, checklist_items, mandates, jobs, cleaners"
)


@pytest.fixture(scope="session", autouse=True)
def _test_schema():
    assert get_settings().db_schema == "test", "refusing to run tests outside the test schema"
    command.upgrade(Config("alembic.ini"), "head")


@pytest.fixture(scope="session", autouse=True)
def _clean_slate(_test_schema):
    # TRUNCATE doesn't fire the row-level append-only trigger, so it can reset the audit log.
    with engine.begin() as conn:
        assert conn.execute(text("SELECT current_schema()")).scalar() == "test"
        conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))


@pytest.fixture
def db(_clean_slate):
    """A session wrapped in an outer transaction that is rolled back after every test.

    session.commit() only releases a savepoint, so code under test can commit freely and
    nothing ever reaches the database.
    """
    with engine.connect() as conn:
        outer = conn.begin()
        session = Session(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
        try:
            yield session
        finally:
            session.close()
            outer.rollback()


@pytest.fixture
def make_job(db):
    def _make(status: str = "BOOKED") -> Job:
        job = Job(
            status=status,
            customer_name="Test Customer",
            customer_email="customer@example.com",
            address="1 Test St",
            service_type="basic",
            scheduled_at=datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc),
            amount=Decimal("10.00"),
            currency="USD",
        )
        db.add(job)
        db.commit()
        return job

    return _make

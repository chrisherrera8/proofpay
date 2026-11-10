"""The payout goes to the booked cleaner; the default PAYPAL_CLEANER_EMAIL is only the fallback."""
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.audit import verify_chain
from app.config import get_settings
from app.models import AuditLog, Cleaner, Payment
from app.paypal.client import PayPalError
from app.settlement import settle
from tests.fakes import FakePayPal

DEFAULT = "default@example.com"
MINE = "grace@example.com"


@pytest.fixture
def paypal():
    return FakePayPal()


@pytest.fixture(autouse=True)
def default_email(monkeypatch):
    monkeypatch.setattr(get_settings(), "paypal_cleaner_email", DEFAULT)


@pytest.fixture
def booked_job(db, make_job):
    """A RELEASED job with an authorized payment and a signed-up cleaner."""
    cleaner = Cleaner(name="Grace Hopper", paypal_email=MINE)
    db.add(cleaner)
    db.commit()
    job = make_job("RELEASED")
    job.cleaner_id = cleaner.id
    db.add(Payment(job_id=job.id, order_id=f"O-{job.id}", authorization_id="A1",
                   authorized_amount=job.amount, status="AUTHORIZED"))
    db.commit()
    return job, cleaner


def payout_row(db):
    return db.scalars(select(AuditLog).where(AuditLog.event == "PAYOUT_CREATED")).one()


def test_booked_cleaner_is_paid_not_the_default(db, booked_job, paypal):
    job, cleaner = booked_job
    settle(db, job, paypal)
    assert [c[1:] for c in paypal.payout_calls] == [(MINE, Decimal("10.00"), "USD")]
    row = payout_row(db)
    assert row.payload["payee"] == "cleaner" and row.payload["cleaner_id"] == str(cleaner.id)


def test_audit_rows_never_contain_the_cleaners_name_or_email(db, booked_job, paypal):
    job, _ = booked_job
    settle(db, job, paypal)
    everything = " ".join(f"{r.actor} {r.payload}" for r in db.scalars(select(AuditLog)))
    assert MINE not in everything and "Grace" not in everything
    assert verify_chain(db) is None


def test_job_without_a_cleaner_pays_the_default(db, make_job, paypal):
    job = make_job("RELEASED")
    db.add(Payment(job_id=job.id, order_id="O1", authorization_id="A1", authorized_amount=job.amount,
                   status="AUTHORIZED"))
    db.commit()
    settle(db, job, paypal)
    assert paypal.payout_calls[0][1] == DEFAULT
    assert payout_row(db).payload["payee"] == "default"


def test_cleaner_purged_between_capture_and_payout_falls_back_to_the_default(db, booked_job, paypal):
    job, cleaner = booked_job
    paypal.payout_error = PayPalError("boom", status_code=500, debug_id="d1")
    settle(db, job, paypal)  # captured, payout failed
    assert paypal.payout_calls[-1][1] == MINE
    db.delete(cleaner)  # what the 24-hour purge does
    db.commit()
    db.expire_all()
    paypal.payout_error = None
    settle(db, job, paypal)
    assert paypal.payout_calls[-1][1] == DEFAULT
    row = payout_row(db)
    assert row.payload["payee"] == "default" and row.payload["cleaner_id"] is None


def test_a_retry_keeps_paying_the_same_cleaner(db, booked_job, paypal):
    job, _ = booked_job
    paypal.payout_error = PayPalError("boom", status_code=500, debug_id="d1")
    settle(db, job, paypal)
    paypal.payout_error = None
    settle(db, job, paypal)
    assert [c[1] for c in paypal.payout_calls] == [MINE, MINE]


def test_no_cleaner_and_no_default_sends_nothing(db, make_job, monkeypatch, paypal):
    monkeypatch.setattr(get_settings(), "paypal_cleaner_email", "")
    job = make_job("RELEASED")
    db.add(Payment(job_id=job.id, order_id="O1", authorization_id="A1", authorized_amount=job.amount,
                   status="AUTHORIZED"))
    db.commit()
    settle(db, job, paypal)
    assert paypal.payout_calls == []
    err = db.scalars(select(AuditLog).where(AuditLog.event == "PAYOUT_ERROR")).one()
    assert "no cleaner" in err.payload["reason"]

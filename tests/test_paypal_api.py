from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.audit import verify_chain
from app.db import get_db
from app.main import app
from app.models import AuditLog, Payment
from app.paypal.client import Authorization, Order, PayPalClient, PayPalError, get_paypal_client


class FakePayPal(PayPalClient):
    def __init__(self):
        self.order_calls = []
        self.authorize_calls = []
        self.order_error = None
        self.authorize_error = None
        self.auth = Authorization("A1", "CREATED", Decimal("10.00"), "USD", "COMPLETED", "dbg")

    def create_order(self, *, job_id, amount, currency, description=None):
        self.order_calls.append(job_id)
        if self.order_error:
            raise self.order_error
        return Order(id="ORDER1", status="CREATED")

    def authorize_order(self, order_id):
        self.authorize_calls.append(order_id)
        if self.authorize_error:
            raise self.authorize_error
        return self.auth


@pytest.fixture
def paypal():
    return FakePayPal()


@pytest.fixture
def client(db, paypal):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_paypal_client] = lambda: paypal
    yield TestClient(app)
    app.dependency_overrides.clear()


def events(db):
    return [r.event for r in db.scalars(select(AuditLog).order_by(AuditLog.id))]


# --- create order ---

def test_create_order(client, db, make_job, paypal):
    job = make_job()
    r = client.post(f"/api/jobs/{job.id}/paypal/order")
    assert r.status_code == 200
    assert r.json() == {"order_id": "ORDER1"}
    payment = db.scalar(select(Payment))
    assert (payment.job_id, payment.order_id, payment.status) == (job.id, "ORDER1", "ORDER_CREATED")
    assert events(db) == ["PAYPAL_ORDER_CREATED"]
    db.refresh(job)
    assert job.status == "BOOKED"  # no status change


def test_create_order_twice_returns_same_order_without_calling_paypal(client, make_job, paypal):
    job = make_job()
    client.post(f"/api/jobs/{job.id}/paypal/order")
    r = client.post(f"/api/jobs/{job.id}/paypal/order")
    assert r.json() == {"order_id": "ORDER1"}
    assert len(paypal.order_calls) == 1


def test_create_order_wrong_status(client, make_job, paypal):
    job = make_job("AUTHORIZED")
    assert client.post(f"/api/jobs/{job.id}/paypal/order").status_code == 409
    assert paypal.order_calls == []


def test_create_order_unknown_job(client):
    assert client.post("/api/jobs/00000000-0000-0000-0000-000000000000/paypal/order").status_code == 404


def test_create_order_paypal_error(client, db, make_job, paypal):
    paypal.order_error = PayPalError("boom", status_code=503, debug_id="d1")
    job = make_job()
    r = client.post(f"/api/jobs/{job.id}/paypal/order")
    assert r.status_code == 502
    assert db.scalars(select(Payment)).all() == []


# --- authorize ---

@pytest.fixture
def ordered_job(client, make_job):
    job = make_job()
    client.post(f"/api/jobs/{job.id}/paypal/order")
    return job


def authorize(client, job, order_id="ORDER1"):
    return client.post(f"/api/jobs/{job.id}/paypal/authorize", json={"order_id": order_id})


def test_authorize_success(client, db, ordered_job, paypal):
    r = authorize(client, ordered_job)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "AUTHORIZED"
    assert body["authorized_at"] is not None
    assert body["payment"]["authorization_id"] == "A1"
    assert Decimal(body["payment"]["authorized_amount"]) == Decimal("10.00")

    payment = db.scalar(select(Payment))
    assert (payment.authorization_id, payment.status) == ("A1", "AUTHORIZED")
    assert payment.authorized_at is not None
    rows = db.scalars(select(AuditLog).order_by(AuditLog.id)).all()
    assert [r.event for r in rows] == ["PAYPAL_ORDER_CREATED", "PAYPAL_AUTHORIZED"]
    assert (rows[1].from_status, rows[1].to_status) == ("BOOKED", "AUTHORIZED")
    assert rows[1].payload["authorization_id"] == "A1"
    assert verify_chain(db) is None


@pytest.mark.parametrize("status", ["DENIED", "PENDING", "VOIDED"])
def test_authorize_non_created_status_keeps_job_booked(client, db, ordered_job, paypal, status):
    paypal.auth = Authorization("A1", status, Decimal("10.00"), "USD", "COMPLETED", "dbg")
    r = authorize(client, ordered_job)
    assert r.status_code == 402
    db.refresh(ordered_job)
    assert ordered_job.status == "BOOKED"
    assert db.scalar(select(Payment)).authorization_id is None
    assert events(db)[-1] == "PAYPAL_AUTHORIZE_REJECTED"


def test_authorize_without_authorization_block(client, db, ordered_job, paypal):
    paypal.auth = Authorization(None, None, None, None, "COMPLETED", "dbg")
    assert authorize(client, ordered_job).status_code == 402
    db.refresh(ordered_job)
    assert ordered_job.status == "BOOKED"


def test_authorize_amount_mismatch_keeps_job_booked(client, db, ordered_job, paypal):
    paypal.auth = Authorization("A1", "CREATED", Decimal("1.00"), "USD", "COMPLETED", "dbg")
    assert authorize(client, ordered_job).status_code == 402
    db.refresh(ordered_job)
    assert ordered_job.status == "BOOKED"
    assert events(db)[-1] == "PAYPAL_AUTHORIZE_REJECTED"


def test_authorize_order_id_mismatch(client, ordered_job, paypal):
    assert authorize(client, ordered_job, order_id="OTHER").status_code == 400
    assert paypal.authorize_calls == []


def test_authorize_without_order(client, make_job, paypal):
    job = make_job()
    assert authorize(client, job).status_code == 409
    assert paypal.authorize_calls == []


def test_authorize_wrong_job_status(client, db, ordered_job, paypal):
    ordered_job.status = "SUBMITTED"  # test setup only
    db.commit()
    assert authorize(client, ordered_job).status_code == 409
    assert paypal.authorize_calls == []


def test_authorize_repeat_is_idempotent(client, db, ordered_job, paypal):
    first = authorize(client, ordered_job).json()
    second = authorize(client, ordered_job)
    assert second.status_code == 200
    assert second.json() == first
    assert len(paypal.authorize_calls) == 1
    assert events(db).count("PAYPAL_AUTHORIZED") == 1


def test_authorize_paypal_error_leaves_job_booked(client, db, ordered_job, paypal):
    paypal.authorize_error = PayPalError("boom", status_code=503, debug_id="d9")
    r = authorize(client, ordered_job)
    assert r.status_code == 502
    assert "d9" in r.json()["detail"]
    db.refresh(ordered_job)
    assert ordered_job.status == "BOOKED"
    last = db.scalars(select(AuditLog).order_by(AuditLog.id.desc())).first()
    assert last.event == "PAYPAL_AUTHORIZE_ERROR"
    assert last.payload["debug_id"] == "d9"


def test_authorize_can_be_retried_after_failure(client, db, ordered_job, paypal):
    paypal.authorize_error = PayPalError("boom", status_code=503)
    assert authorize(client, ordered_job).status_code == 502
    paypal.authorize_error = None
    assert authorize(client, ordered_job).status_code == 200
    db.refresh(ordered_job)
    assert ordered_job.status == "AUTHORIZED"

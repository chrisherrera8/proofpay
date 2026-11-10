import json
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.audit import verify_chain
from app.config import get_settings
from app.db import get_db
from app.main import app
from app.models import AuditLog, Payment, Payout
from app.paypal.client import get_paypal_client
from app.settlement import settle
from tests.fakes import FakePayPal

URL = "/api/webhooks/paypal"


@pytest.fixture
def paypal():
    return FakePayPal()


@pytest.fixture
def client(db, paypal, monkeypatch):
    monkeypatch.setattr(get_settings(), "paypal_webhook_id", "WH1")
    monkeypatch.setattr(get_settings(), "paypal_cleaner_email", "cleaner@example.com")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_paypal_client] = lambda: paypal
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def captured_job(db, make_job, paypal, client):
    """A CAPTURED job with a PENDING payout (batch BATCH1)."""
    job = make_job("RELEASED")
    db.add(Payment(job_id=job.id, order_id="O1", authorization_id="A1",
                   authorized_amount=job.amount, status="AUTHORIZED"))
    db.commit()
    settle(db, job, paypal)
    db.refresh(job)
    assert job.status == "CAPTURED"
    return job


def event(event_type, batch_id="BATCH1", **resource):
    return {"id": "WH-1", "event_type": event_type,
            "resource": {"payout_batch_id": batch_id, "payout_item_id": "ITEM9",
                         "transaction_status": "SUCCESS", **resource}}


def post(client, body):
    return client.post(URL, content=json.dumps(body), headers={"content-type": "application/json"})


def payout_of(db):
    return db.scalar(select(Payout))


def events(db):
    return [r.event for r in db.scalars(select(AuditLog).order_by(AuditLog.id))]


def test_item_succeeded_marks_job_paid_out(client, db, captured_job):
    r = post(client, event("PAYMENT.PAYOUTS-ITEM.SUCCEEDED"))
    assert r.status_code == 200
    db.refresh(captured_job)
    assert captured_job.status == "PAID_OUT"
    payout = payout_of(db)
    assert (payout.status, payout.item_id, payout.amount) == ("SUCCESS", "ITEM9", Decimal("10.00"))
    assert events(db)[-1] == "PAYOUT_SUCCEEDED"
    assert verify_chain(db) is None


def test_replayed_delivery_is_a_noop(client, db, captured_job):
    post(client, event("PAYMENT.PAYOUTS-ITEM.SUCCEEDED"))
    n = len(events(db))
    r = post(client, event("PAYMENT.PAYOUTS-ITEM.SUCCEEDED"))
    assert r.status_code == 200
    assert len(events(db)) == n


def test_already_paid_by_polling_is_a_noop(client, db, captured_job, paypal):
    settle(db, captured_job, paypal)  # polling finds the item SUCCESS
    db.refresh(captured_job)
    assert captured_job.status == "PAID_OUT"
    n = len(events(db))
    assert post(client, event("PAYMENT.PAYOUTS-ITEM.SUCCEEDED")).status_code == 200
    assert len(events(db)) == n


@pytest.mark.parametrize("kind", ["FAILED", "UNCLAIMED", "RETURNED", "BLOCKED"])
def test_item_failure_marks_payout_failed_and_keeps_job_captured(client, db, captured_job, kind):
    r = post(client, event(f"PAYMENT.PAYOUTS-ITEM.{kind}", transaction_status=kind))
    assert r.status_code == 200
    db.refresh(captured_job)
    assert captured_job.status == "CAPTURED"
    assert payout_of(db).status == "FAILED"
    row = db.scalars(select(AuditLog).order_by(AuditLog.id.desc())).first()
    assert row.event == "PAYOUT_FAILED"
    assert row.payload["event_type"] == f"PAYMENT.PAYOUTS-ITEM.{kind}"
    assert verify_chain(db) is None


def test_failure_replay_writes_one_audit_row(client, db, captured_job):
    for _ in range(2):
        assert post(client, event("PAYMENT.PAYOUTS-ITEM.FAILED")).status_code == 200
    assert events(db).count("PAYOUT_FAILED") == 1


def test_bad_signature_is_400_and_changes_nothing(client, db, captured_job, paypal):
    paypal.webhook_valid = False
    assert post(client, event("PAYMENT.PAYOUTS-ITEM.SUCCEEDED")).status_code == 400
    db.refresh(captured_job)
    assert captured_job.status == "CAPTURED"
    assert payout_of(db).status == "PENDING"


def test_no_webhook_id_is_503(client, monkeypatch, captured_job):
    monkeypatch.setattr(get_settings(), "paypal_webhook_id", "")
    assert post(client, event("PAYMENT.PAYOUTS-ITEM.SUCCEEDED")).status_code == 503


@pytest.mark.parametrize("event_type", [
    "PAYMENT.CAPTURE.COMPLETED", "PAYMENT.AUTHORIZATION.CREATED", "CHECKOUT.ORDER.APPROVED",
    "PAYMENT.PAYOUTSBATCH.SUCCESS", "SOMETHING.NEW",
])
def test_other_events_are_acknowledged_and_ignored(client, db, captured_job, event_type):
    n = len(events(db))
    assert post(client, event(event_type)).status_code == 200
    db.refresh(captured_job)
    assert captured_job.status == "CAPTURED"
    assert len(events(db)) == n


def test_unknown_batch_is_404_so_paypal_retries(client, db, captured_job):
    assert post(client, event("PAYMENT.PAYOUTS-ITEM.SUCCEEDED", batch_id="NOPE")).status_code == 404
    db.refresh(captured_job)
    assert captured_job.status == "CAPTURED"


def test_malformed_body_is_400(client):
    r = client.post(URL, content=b"not json")
    assert r.status_code == 400

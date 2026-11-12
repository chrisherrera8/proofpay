"""Booking a cleaner for a whole day: availability, the lock, and the unpaid-hold rules."""
import datetime as dt
import json
import threading

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.audit import verify_chain
from app.config import get_settings
from app.db import SessionLocal, engine, get_db
from app.main import app
from app.models import AuditLog, Cleaner, Job, Payment
from app.paypal.client import get_paypal_client
from tests.conftest import TABLES
from tests.fakes import FakePayPal

UTC = dt.timezone.utc
DAY = (dt.datetime.now(UTC) + dt.timedelta(days=7)).date()


@pytest.fixture
def paypal():
    return FakePayPal()


@pytest.fixture
def client(db, paypal):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_paypal_client] = lambda: paypal
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def make_cleaner(db):
    def _make(name="Cleaner", age=dt.timedelta(0), is_seed=False) -> Cleaner:
        c = Cleaner(name=name, paypal_email=f"{name.lower()}@example.com", is_seed=is_seed,
                    created_at=dt.datetime.now(UTC) - age, last_used_at=dt.datetime.now(UTC) - age)
        db.add(c)
        db.commit()
        return c

    return _make


def body(cleaner, day=DAY, **over):
    return {"customer_name": "Ada Lovelace", "customer_email": "ada@example.com", "address": "12 Analytical Way",
            "service_type": "basic", "cleaner_id": str(cleaner.id), "service_date": day.isoformat(),
            "amount": "10.00", **over}


def age_job(db, job_id, minutes):
    db.execute(text("UPDATE jobs SET created_at = now() - make_interval(mins => :m) WHERE id = :id"),
               {"m": minutes, "id": job_id})
    db.commit()


# --- booking -------------------------------------------------------------------------------------

def test_booking_stores_cleaner_and_date_and_audits_ids_only(client, db, make_cleaner):
    c = make_cleaner("Grace")
    r = client.post("/api/jobs", json=body(c))
    assert r.status_code == 201
    data = r.json()
    assert data["cleaner_id"] == str(c.id) and data["service_date"] == DAY.isoformat()
    assert data["scheduled_at"] == f"{DAY}T12:00:00Z"  # display value only
    row = db.scalar(select(AuditLog))
    assert row.payload["cleaner_id"] == str(c.id) and row.payload["service_date"] == DAY.isoformat()
    # Scrubbing a cleaner must leave nothing personal behind in the append-only log.
    dumped = json.dumps(row.payload) + row.actor
    assert "Grace" not in dumped and "grace@example.com" not in dumped
    assert verify_chain(db) is None


def test_booking_restarts_the_cleaners_24_hour_clock(client, db, make_cleaner):
    c = make_cleaner("Grace", age=dt.timedelta(hours=20))
    assert client.post("/api/jobs", json=body(c)).status_code == 201
    db.refresh(c)
    assert dt.datetime.now(UTC) - c.last_used_at < dt.timedelta(minutes=1)


def test_same_cleaner_same_day_is_a_409_and_creates_nothing(client, db, make_cleaner):
    c = make_cleaner()
    assert client.post("/api/jobs", json=body(c)).status_code == 201
    r = client.post("/api/jobs", json=body(c, customer_email="bob@example.com"))
    assert r.status_code == 409 and "already booked" in r.json()["detail"]
    assert len(db.scalars(select(Job)).all()) == 1
    assert len(db.scalars(select(AuditLog)).all()) == 1


def test_other_day_and_other_cleaner_are_free(client, make_cleaner):
    a, b = make_cleaner("A"), make_cleaner("B")
    assert client.post("/api/jobs", json=body(a)).status_code == 201
    assert client.post("/api/jobs", json=body(a, DAY + dt.timedelta(days=1))).status_code == 201
    assert client.post("/api/jobs", json=body(b)).status_code == 201


def test_booked_cleaner_disappears_from_the_available_roster(client, make_cleaner):
    a, b = make_cleaner("A"), make_cleaner("B")
    client.post("/api/jobs", json=body(a))
    names = [c["name"] for c in client.get("/api/cleaners", params={"date": DAY.isoformat(), "available": "true"}).json()]
    assert names == ["B"]


def test_unknown_or_expired_cleaner_is_404(client, make_cleaner):
    gone = make_cleaner("Gone", age=dt.timedelta(hours=25))
    assert client.post("/api/jobs", json=body(gone)).status_code == 404
    assert client.post("/api/jobs", json={**body(gone), "cleaner_id": "00000000-0000-0000-0000-000000000000"}).status_code == 404


def test_default_cleaner_never_expires_and_can_be_booked(client, make_cleaner):
    default = make_cleaner("Default", age=dt.timedelta(days=90), is_seed=True)
    assert client.post("/api/jobs", json=body(default)).status_code == 201


def test_cleaner_id_and_service_date_are_required(client, make_cleaner):
    c = make_cleaner()
    for missing in ("cleaner_id", "service_date"):
        b = body(c)
        del b[missing]
        assert client.post("/api/jobs", json=b).status_code == 422


def test_past_dates_are_rejected_but_yesterday_is_allowed_for_timezones(client, make_cleaner):
    c = make_cleaner()
    today = dt.datetime.now(UTC).date()
    assert client.post("/api/jobs", json=body(c, today - dt.timedelta(days=2))).status_code == 422
    assert client.post("/api/jobs", json=body(c, today - dt.timedelta(days=1))).status_code == 201


# --- the unpaid hold -----------------------------------------------------------------------------

def test_unpaid_booking_holds_for_30_minutes_then_frees_the_day(client, db, make_cleaner):
    c = make_cleaner()
    first = client.post("/api/jobs", json=body(c)).json()["id"]
    assert client.post("/api/jobs", json=body(c)).status_code == 409
    age_job(db, first, 31)
    assert client.post("/api/jobs", json=body(c, customer_email="bob@example.com")).status_code == 201


def test_stale_unpaid_job_cannot_start_payment_once_the_day_is_taken(client, db, make_cleaner, paypal):
    c = make_cleaner()
    stale = client.post("/api/jobs", json=body(c)).json()["id"]
    age_job(db, stale, 31)
    assert client.post("/api/jobs", json=body(c, customer_email="bob@example.com")).status_code == 201
    r = client.post(f"/api/jobs/{stale}/paypal/order")
    assert r.status_code == 409 and "booked by someone else" in r.json()["detail"]
    assert paypal.order_calls == []


def test_stale_job_with_an_order_cannot_authorize_after_the_day_is_taken(client, db, make_cleaner, paypal):
    c = make_cleaner()
    stale = client.post("/api/jobs", json=body(c)).json()["id"]
    order = client.post(f"/api/jobs/{stale}/paypal/order").json()["order_id"]
    age_job(db, stale, 31)
    client.post("/api/jobs", json=body(c, customer_email="bob@example.com"))
    r = client.post(f"/api/jobs/{stale}/paypal/authorize", json={"order_id": order})
    assert r.status_code == 409
    assert paypal.authorize_calls == []  # PayPal was never asked to hold the money
    assert db.get(Job, stale).status == "BOOKED"


def test_a_job_does_not_conflict_with_itself(client, make_cleaner, paypal):
    c = make_cleaner()
    job = client.post("/api/jobs", json=body(c)).json()["id"]
    order = client.post(f"/api/jobs/{job}/paypal/order")
    assert order.status_code == 200
    r = client.post(f"/api/jobs/{job}/paypal/authorize", json={"order_id": order.json()["order_id"]})
    assert r.status_code == 200 and r.json()["status"] == "AUTHORIZED"


def test_jobs_without_a_cleaner_are_unaffected(client, make_job, paypal):
    job = make_job()  # an old row: no cleaner, no service_date
    assert client.post(f"/api/jobs/{job.id}/paypal/order").status_code == 200


# --- concurrency (real committed transactions, so it cleans up after itself) ----------------------

def test_two_simultaneous_bookings_for_one_cleaner_and_day_only_one_wins(monkeypatch):
    monkeypatch.setattr(get_settings(), "paypal_cleaner_email", "")
    with SessionLocal() as s:
        c = Cleaner(name="Racer", paypal_email="racer@example.com")
        s.add(c)
        s.commit()
    try:
        results: list[int] = []
        barrier = threading.Barrier(2)

        def go(email):
            barrier.wait()
            with TestClient(app) as http:  # own client and own DB session per thread
                results.append(http.post("/api/jobs", json=body(c, customer_email=email)).status_code)

        threads = [threading.Thread(target=go, args=(f"u{i}@example.com",)) for i in range(2)]
        [t.start() for t in threads]
        [t.join(30) for t in threads]
        assert sorted(results) == [201, 409]
        with SessionLocal() as s:
            assert len(s.scalars(select(Job).where(Job.cleaner_id == c.id)).all()) == 1
    finally:
        with engine.begin() as conn:  # TRUNCATE skips the append-only row trigger, like conftest does
            assert conn.execute(text("SELECT current_schema()")).scalar() == "test"
            conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))


def test_job_out_shows_cleaner_name_and_null_after_purge(client, db, make_cleaner):
    c = make_cleaner("Dana")
    job_id = client.post("/api/jobs", json=body(c)).json()["id"]
    assert client.get(f"/api/jobs/{job_id}").json()["cleaner_name"] == "Dana"
    assert client.get(f"/api/jobs?cleaner_id={c.id}").json()[0]["cleaner_name"] == "Dana"

    db.delete(c)
    db.commit()
    db.expire_all()
    out = client.get(f"/api/jobs/{job_id}").json()
    assert out["cleaner_id"] is None and out["cleaner_name"] is None

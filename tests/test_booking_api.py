import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.audit import verify_chain
from app.db import get_db
from app.main import app
from app.models import AuditLog, Cleaner, Job


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


FUTURE = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=7)).date()


@pytest.fixture
def body(db):
    cleaner = Cleaner(name="Test Cleaner", paypal_email="cleaner@example.com")
    db.add(cleaner)
    db.commit()
    return {
        "customer_name": "Ada Lovelace",
        "customer_email": "ada@example.com",
        "address": "12 Analytical Way",
        "service_type": "basic",
        "cleaner_id": str(cleaner.id),
        "service_date": FUTURE.isoformat(),
        "amount": "10.00",
    }


def test_healthz(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_book_job_happy_path(client, db, body):
    r = client.post("/api/jobs", json=body)
    assert r.status_code == 201
    data = r.json()
    assert data["status"] == "BOOKED"
    assert data["amount"] == "10.00"
    assert data["currency"] == "USD"
    assert data["payment"] is None

    rows = db.scalars(select(AuditLog)).all()
    assert len(rows) == 1
    assert rows[0].event == "JOB_BOOKED"
    assert rows[0].from_status is None
    assert rows[0].to_status == "BOOKED"
    assert str(rows[0].job_id) == data["id"]
    assert verify_chain(db) is None


def test_checklist_copied_from_template(client, body):
    items = client.post("/api/jobs", json=body).json()["checklist_items"]
    assert [i["label"] for i in items] == ["Kitchen", "Bathroom", "Floors", "Surfaces"]
    assert [i["position"] for i in items] == [0, 1, 2, 3]
    assert [i["required"] for i in items] == [True, True, True, True]


@pytest.mark.parametrize("amount", ["0", "-5", "0.00", "abc", "10.001"])
def test_invalid_amount_rejected(client, db, amount, body):
    r = client.post("/api/jobs", json={**body, "amount": amount})
    assert r.status_code == 422
    assert db.scalars(select(Job)).all() == []
    assert db.scalars(select(AuditLog)).all() == []


@pytest.mark.parametrize(
    "service_type,amount", [("basic", "10.00"), ("deep", "20.00"), ("deluxe", "30.00")]
)
def test_each_tier_books_at_its_price(client, service_type, amount, body):
    r = client.post("/api/jobs", json={**body, "service_type": service_type, "amount": amount})
    assert r.status_code == 201
    assert r.json()["amount"] == amount


@pytest.mark.parametrize(
    "service_type,amount",
    [("deluxe", "1.00"), ("deluxe", "10.00"), ("basic", "30.00"), ("deep", "20.01"), ("basic", "9.99")],
)
def test_wrong_price_for_tier_rejected(client, db, service_type, amount, body):
    r = client.post("/api/jobs", json={**body, "service_type": service_type, "amount": amount})
    assert r.status_code == 422
    assert db.scalars(select(Job)).all() == []
    assert db.scalars(select(AuditLog)).all() == []


def test_unknown_service_type_rejected(client, body):
    assert client.post("/api/jobs", json={**body, "service_type": "moat_dredging"}).status_code == 422


def test_unsupported_currency_rejected(client, body):
    assert client.post("/api/jobs", json={**body, "currency": "EUR"}).status_code == 422


def test_bad_email_rejected(client, body):
    assert client.post("/api/jobs", json={**body, "customer_email": "nope"}).status_code == 422


def test_get_job(client, body):
    job_id = client.post("/api/jobs", json=body).json()["id"]
    r = client.get(f"/api/jobs/{job_id}")
    assert r.status_code == 200
    assert r.json()["id"] == job_id
    assert len(r.json()["checklist_items"]) == 4


def test_get_unknown_job_404(client):
    assert client.get("/api/jobs/00000000-0000-0000-0000-000000000000").status_code == 404


def test_get_malformed_id_422(client):
    assert client.get("/api/jobs/not-a-uuid").status_code == 422


def test_list_jobs_and_status_filter(client, db, make_job, body):
    from sqlalchemy import update

    from app.models import Cleaner, Job

    c = Cleaner(name="Lister", paypal_email="lister@example.com")
    db.add(c)
    db.commit()
    cid = str(c.id)
    booked_id = client.post("/api/jobs", json=body).json()["id"]
    other = make_job("AUTHORIZED")
    db.execute(update(Job).where(Job.id.in_([booked_id, other.id])).values(cleaner_id=c.id))
    db.commit()
    assert len(client.get("/api/jobs", params={"cleaner_id": cid}).json()) == 2
    booked = client.get("/api/jobs", params={"cleaner_id": cid, "status": "BOOKED"}).json()
    assert [j["status"] for j in booked] == ["BOOKED"]
    assert client.get("/api/jobs", params={"cleaner_id": cid, "status": "BOGUS"}).status_code == 422


def test_list_jobs_requires_cleaner_id(client, make_job):
    make_job("AUTHORIZED")
    assert client.get("/api/jobs").status_code == 422
    assert client.get("/api/jobs", params={"status": "AUTHORIZED", "limit": 200}).status_code == 422
    assert client.get("/api/jobs", params={"cleaner_id": "not-a-uuid"}).status_code == 422


# web/src/tiers.ts shows these prices to customers, so they must match what the API accepts.
@pytest.mark.parametrize("tier,price", [("basic", "10.00"), ("deep", "20.00"), ("deluxe", "30.00")])
def test_tier_prices_match_web(client, body, tier, price):
    ok = client.post("/api/jobs", json={**body, "service_type": tier, "amount": price})
    assert ok.status_code == 201
    other = "20.00" if price != "20.00" else "10.00"
    assert client.post("/api/jobs", json={**body, "service_type": tier, "amount": other}).status_code == 422

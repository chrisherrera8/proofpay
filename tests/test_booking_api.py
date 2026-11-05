import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.audit import verify_chain
from app.db import get_db
from app.main import app
from app.models import AuditLog, Job


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


BODY = {
    "customer_name": "Ada Lovelace",
    "customer_email": "ada@example.com",
    "address": "12 Analytical Way",
    "service_type": "standard_clean",
    "scheduled_at": "2026-11-10T09:00:00Z",
    "amount": "120.00",
}


def test_healthz(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_book_job_happy_path(client, db):
    r = client.post("/api/jobs", json=BODY)
    assert r.status_code == 201
    data = r.json()
    assert data["status"] == "BOOKED"
    assert data["amount"] == "120.00"
    assert data["currency"] == "USD"
    assert data["payment"] is None

    rows = db.scalars(select(AuditLog)).all()
    assert len(rows) == 1
    assert rows[0].event == "JOB_BOOKED"
    assert rows[0].from_status is None
    assert rows[0].to_status == "BOOKED"
    assert str(rows[0].job_id) == data["id"]
    assert verify_chain(db) is None


def test_checklist_copied_from_template(client):
    items = client.post("/api/jobs", json=BODY).json()["checklist_items"]
    assert [i["label"] for i in items] == ["Kitchen", "Bathroom", "Floors", "Surfaces", "Oven"]
    assert [i["position"] for i in items] == [0, 1, 2, 3, 4]
    assert [i["required"] for i in items] == [True, True, True, True, False]


@pytest.mark.parametrize("amount", ["0", "-5", "0.00", "abc", "10.001"])
def test_invalid_amount_rejected(client, db, amount):
    r = client.post("/api/jobs", json={**BODY, "amount": amount})
    assert r.status_code == 422
    assert db.scalars(select(Job)).all() == []
    assert db.scalars(select(AuditLog)).all() == []


def test_unknown_service_type_rejected(client):
    assert client.post("/api/jobs", json={**BODY, "service_type": "moat_dredging"}).status_code == 422


def test_unsupported_currency_rejected(client):
    assert client.post("/api/jobs", json={**BODY, "currency": "EUR"}).status_code == 422


def test_naive_scheduled_at_rejected(client):
    assert client.post("/api/jobs", json={**BODY, "scheduled_at": "2026-11-10T09:00:00"}).status_code == 422


def test_bad_email_rejected(client):
    assert client.post("/api/jobs", json={**BODY, "customer_email": "nope"}).status_code == 422


def test_get_job(client):
    job_id = client.post("/api/jobs", json=BODY).json()["id"]
    r = client.get(f"/api/jobs/{job_id}")
    assert r.status_code == 200
    assert r.json()["id"] == job_id
    assert len(r.json()["checklist_items"]) == 5


def test_get_unknown_job_404(client):
    assert client.get("/api/jobs/00000000-0000-0000-0000-000000000000").status_code == 404


def test_get_malformed_id_422(client):
    assert client.get("/api/jobs/not-a-uuid").status_code == 422


def test_list_jobs_and_status_filter(client, make_job):
    client.post("/api/jobs", json=BODY)
    make_job("AUTHORIZED")
    assert len(client.get("/api/jobs").json()) == 2
    booked = client.get("/api/jobs", params={"status": "BOOKED"}).json()
    assert [j["status"] for j in booked] == ["BOOKED"]
    assert client.get("/api/jobs", params={"status": "BOGUS"}).status_code == 422

"""DELETE /api/jobs/{id}: removes the job and its rows, only where no money is held."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_db
from app.main import app
from app.models import AuditLog, ChecklistItem, Job, Payment, Payout, Photo


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.mark.parametrize("status", ["BOOKED", "PAID_OUT"])
def test_delete_removes_job_and_children(client, db, make_job, status):
    job = make_job(status)
    job_id = job.id
    db.add_all([Photo(job_id=job_id, kind="before", data=b"x", content_type="image/jpeg"),
                ChecklistItem(job_id=job_id, label="Sink"),
                Payment(job_id=job_id, order_id="ORDER-1")])
    db.commit()

    assert client.delete(f"/api/jobs/{job_id}").status_code == 204

    db.expire_all()
    assert db.get(Job, job_id) is None
    for model in (Photo, ChecklistItem, Payment):
        assert db.scalar(select(model).where(model.job_id == job_id)) is None
    assert db.scalar(select(AuditLog).where(AuditLog.job_id == job_id, AuditLog.event == "JOB_DELETED"))
    assert client.get(f"/api/jobs/{job_id}").status_code == 404


def test_delete_allowed_when_payout_failed(client, db, make_job):
    job = make_job("CAPTURED")
    job_id = job.id
    db.add(Payout(job_id=job_id, status="FAILED", amount=job.amount))
    db.commit()
    assert client.delete(f"/api/jobs/{job_id}").status_code == 204
    db.expire_all()
    assert db.get(Job, job_id) is None


@pytest.mark.parametrize("payout_status", ["PENDING", "SUCCESS"])
def test_delete_refused_when_captured_payout_not_failed(client, db, make_job, payout_status):
    job = make_job("CAPTURED")
    db.add(Payout(job_id=job.id, status=payout_status, amount=job.amount))
    db.commit()
    assert client.delete(f"/api/jobs/{job.id}").status_code == 409


@pytest.mark.parametrize("status", ["AUTHORIZED", "SUBMITTED", "PENDING_APPROVAL", "RELEASED", "CAPTURED", "REJECTED"])
def test_delete_refused_while_money_is_held(client, db, make_job, status):
    job = make_job(status)
    r = client.delete(f"/api/jobs/{job.id}")
    assert r.status_code == 409
    db.expire_all()
    assert db.get(Job, job.id) is not None


def test_delete_unknown_job_is_404(client):
    assert client.delete("/api/jobs/00000000-0000-0000-0000-000000000000").status_code == 404

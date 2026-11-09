import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.audit import verify_chain
from app.db import get_db
from app.main import app
from app.models import AuditLog, ChecklistItem, Photo
from app.vision import VisionError, get_vision_provider
from app.vision.base import ItemResult, VisionResult

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


class FakeVision:
    model = "fake-vision"

    def __init__(self, fail_items=(), error=None):
        self.fail_items = set(fail_items)
        self.error = error
        self.calls = []

    def verify(self, before, after, checklist):
        self.calls.append((len(before), len(after), list(checklist)))
        if self.error:
            raise self.error
        items = [ItemResult(c, True, c not in self.fail_items, 0.9, "ok") for c in checklist]
        ok = all(i.passed for i in items)
        return VisionResult(items, ok, 1.0 if ok else 0.5, self.model, 100, 20)


@pytest.fixture
def vision():
    return FakeVision()


@pytest.fixture
def client(db, vision):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_vision_provider] = lambda: vision
    yield TestClient(app)
    app.dependency_overrides.clear()


def _post(client, job, kind, data=JPEG):
    return client.post(f"/api/jobs/{job.id}/photos", params={"kind": kind}, content=data,
                       headers={"Content-Type": "image/jpeg"})


def _ready(client, make_job, db):
    job = make_job("AUTHORIZED")
    # make_job creates no checklist; real jobs get a copy of the tier template at booking.
    job.checklist_items = [ChecklistItem(label=l, required=True, position=i)
                           for i, l in enumerate(["Kitchen", "Bathroom", "Floors", "Surfaces"])]
    db.commit()
    assert _post(client, job, "before").status_code == 201
    assert _post(client, job, "after").status_code == 201
    return job


def test_upload_stores_photo_and_audits(client, db, make_job):
    job = make_job("AUTHORIZED")
    r = _post(client, job, "before", PNG)
    assert r.status_code == 201
    assert r.json()["kind"] == "before"
    assert r.json()["content_type"] == "image/png"  # sniffed from the bytes
    assert db.scalar(select(Photo)).data == PNG
    assert db.scalars(select(AuditLog.event)).all() == ["PHOTO_UPLOADED"]
    assert client.get(f"/api/jobs/{job.id}/photos/{r.json()['id']}").content == PNG
    assert len(client.get(f"/api/jobs/{job.id}/photos").json()) == 1


@pytest.mark.parametrize("data,code", [(b"", 400), (b"not an image", 415), (b"\xff\xd8\xff" + b"0" * (3 * 1024 * 1024), 413)])
def test_upload_rejects_bad_bodies(client, make_job, data, code):
    assert _post(client, make_job("AUTHORIZED"), "before", data).status_code == code


def test_upload_rejects_bad_kind_and_wrong_status_and_limit(client, make_job):
    job = make_job("AUTHORIZED")
    assert _post(client, job, "during").status_code == 422
    assert _post(client, make_job("BOOKED"), "before").status_code == 409
    assert _post(client, make_job("VERIFIED"), "before").status_code == 409
    for _ in range(4):
        assert _post(client, job, "after").status_code == 201
    assert _post(client, job, "after").status_code == 409
    assert client.post(f"/api/jobs/{job.id}/photos", params={"kind": "before"}, content=JPEG).status_code == 201
    missing = client.post(f"/api/jobs/{uuid.uuid4()}/photos", params={"kind": "before"}, content=JPEG)
    assert missing.status_code == 404


def test_delete_photo(client, db, make_job):
    job = make_job("AUTHORIZED")
    pid = _post(client, job, "before").json()["id"]
    assert client.delete(f"/api/jobs/{job.id}/photos/{pid}").status_code == 204
    assert client.delete(f"/api/jobs/{job.id}/photos/{pid}").status_code == 404
    assert db.scalars(select(Photo)).all() == []


def test_submit_runs_vision_and_verifies(client, db, make_job, vision):
    job = _ready(client, make_job, db)
    r = client.post(f"/api/jobs/{job.id}/submit")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "VERIFIED"
    assert data["verification"]["model"] == "fake-vision"
    assert data["verification"]["score"] == "1.00"
    assert data["verification"]["results"]["overall_pass"] is True
    assert [i["item"] for i in data["verification"]["results"]["items"]] == ["Kitchen", "Bathroom", "Floors", "Surfaces"]
    assert vision.calls == [(1, 1, ["Kitchen", "Bathroom", "Floors", "Surfaces"])]
    events = db.scalars(select(AuditLog.event).order_by(AuditLog.id)).all()
    assert events == ["PHOTO_UPLOADED", "PHOTO_UPLOADED", "JOB_SUBMITTED", "VERIFICATION_COMPLETED"]
    assert verify_chain(db) is None


def test_failed_items_recorded(client, db, make_job, vision):
    vision.fail_items = {"Kitchen"}
    job = _ready(client, make_job, db)
    data = client.post(f"/api/jobs/{job.id}/submit").json()
    assert data["status"] == "VERIFIED"  # the policy engine, not this step, decides what a failure means
    assert data["verification"]["results"]["overall_pass"] is False


def test_submit_needs_both_photo_kinds(client, make_job):
    job = make_job("AUTHORIZED")
    assert client.post(f"/api/jobs/{job.id}/submit").status_code == 422
    _post(client, job, "before")
    assert client.post(f"/api/jobs/{job.id}/submit").status_code == 422
    assert job.status == "AUTHORIZED"


@pytest.mark.parametrize("status", ["BOOKED", "SUBMITTED", "VERIFIED", "CAPTURED"])
def test_submit_wrong_status(client, make_job, status):
    assert client.post(f"/api/jobs/{make_job(status).id}/submit").status_code == 409


def test_vision_failure_leaves_job_submitted_and_verify_retries(client, db, make_job, vision):
    job = _ready(client, make_job, db)
    vision.error = VisionError("Gemini error 503")
    r = client.post(f"/api/jobs/{job.id}/submit")
    assert r.status_code == 502
    assert "still SUBMITTED" in r.json()["detail"]
    db.refresh(job)
    assert job.status == "SUBMITTED"
    assert "VERIFICATION_ERROR" in db.scalars(select(AuditLog.event)).all()

    vision.error = None
    r = client.post(f"/api/jobs/{job.id}/verify")
    assert r.status_code == 200 and r.json()["status"] == "VERIFIED"
    assert client.post(f"/api/jobs/{job.id}/verify").status_code == 409


def test_missing_api_key_gives_503(db, make_job, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "gemini_api_key", "")
    app.dependency_overrides[get_db] = lambda: db
    try:
        job = make_job("AUTHORIZED")
        c = TestClient(app)
        _post(c, job, "before"); _post(c, job, "after")
        r = c.post(f"/api/jobs/{job.id}/submit")
        assert r.status_code == 503
    finally:
        app.dependency_overrides.clear()

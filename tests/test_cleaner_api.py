import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.audit import verify_chain
from app.config import get_settings
from app.db import get_db
from app.main import app
from app.models import AuditLog, ChecklistItem, Photo, Verification
from app.vision import VisionError, get_vision_provider
from app.vision.base import ItemResult, VisionResult
from app.vision.gemini import GeminiProvider

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


def events(db):
    return db.scalars(select(AuditLog.event).order_by(AuditLog.id)).all()


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


def test_oversized_content_length_is_rejected_before_reading_body(client, make_job, monkeypatch):
    async def body_must_not_be_read(self):
        raise AssertionError("body was read despite oversized Content-Length")

    monkeypatch.setattr("starlette.requests.Request.body", body_must_not_be_read)
    job = make_job("AUTHORIZED")
    res = client.post(f"/api/jobs/{job.id}/photos", params={"kind": "before"},
                      content=JPEG, headers={"Content-Length": str(3 * 1024 * 1024 + 1)})
    assert res.status_code == 413


# --- upload validation ---

def test_upload_rejects_unknown_kind(client, make_job):
    assert _post(client, make_job("AUTHORIZED"), "during").status_code == 422


@pytest.mark.parametrize("status", ["BOOKED", "VERIFIED"])
def test_upload_rejects_non_editable_status(client, make_job, status):
    assert _post(client, make_job(status), "before").status_code == 409


def test_upload_caps_photos_per_kind(client, make_job):
    job = make_job("AUTHORIZED")
    for _ in range(4):
        assert _post(client, job, "after").status_code == 201
    assert _post(client, job, "after").status_code == 409
    assert _post(client, job, "before").status_code == 201  # the cap is per kind


def test_upload_to_missing_job_is_404(client):
    r = client.post(f"/api/jobs/{uuid.uuid4()}/photos", params={"kind": "before"}, content=JPEG)
    assert r.status_code == 404


def test_delete_photo(client, db, make_job):
    job = make_job("AUTHORIZED")
    pid = _post(client, job, "before").json()["id"]
    assert client.delete(f"/api/jobs/{job.id}/photos/{pid}").status_code == 204
    assert client.delete(f"/api/jobs/{job.id}/photos/{pid}").status_code == 404
    assert db.scalars(select(Photo)).all() == []


# --- photo access ---

def test_photo_requested_through_wrong_job_is_404(client, db, make_job):
    owner, other = make_job("AUTHORIZED"), make_job("AUTHORIZED")
    pid = _post(client, owner, "before").json()["id"]
    assert client.get(f"/api/jobs/{other.id}/photos/{pid}").status_code == 404
    assert client.delete(f"/api/jobs/{other.id}/photos/{pid}").status_code == 404
    assert client.get(f"/api/jobs/{owner.id}/photos/{pid}").status_code == 200
    assert events(db) == ["PHOTO_UPLOADED"]


def test_delete_photo_on_non_editable_job_is_409(client, db, make_job):
    job = make_job("AUTHORIZED")
    pid = _post(client, job, "before").json()["id"]
    job.status = "VERIFIED"
    db.commit()
    assert client.delete(f"/api/jobs/{job.id}/photos/{pid}").status_code == 409
    assert len(db.scalars(select(Photo)).all()) == 1
    assert events(db) == ["PHOTO_UPLOADED"]


def test_list_photos_missing_job_is_404(client):
    assert client.get(f"/api/jobs/{uuid.uuid4()}/photos").status_code == 404


def test_get_missing_photo_is_404(client, make_job):
    assert client.get(f"/api/jobs/{make_job('AUTHORIZED').id}/photos/999999").status_code == 404


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


def test_reclean_after_rejection_resubmits_and_latest_verification_wins(client, db, make_job, vision):
    vision.fail_items = {"Kitchen"}
    job = _ready(client, make_job, db)
    first = client.post(f"/api/jobs/{job.id}/submit").json()
    assert first["verification"]["results"]["overall_pass"] is False

    # Nothing rejects a job yet (the policy engine comes later), so force it.
    job.status = "REJECTED"
    db.commit()
    assert _post(client, job, "after").status_code == 201  # a REJECTED job is editable again

    vision.fail_items = set()
    second = client.post(f"/api/jobs/{job.id}/submit")
    assert second.status_code == 200
    assert second.json()["status"] == "VERIFIED"
    assert second.json()["verification"]["results"]["overall_pass"] is True
    assert second.json()["verification"]["id"] != first["verification"]["id"]
    assert len(db.scalars(select(Verification)).all()) == 2
    assert client.get(f"/api/jobs/{job.id}").json()["verification"]["id"] == second.json()["verification"]["id"]
    assert events(db) == [
        "PHOTO_UPLOADED", "PHOTO_UPLOADED", "JOB_SUBMITTED", "VERIFICATION_COMPLETED",
        "PHOTO_UPLOADED", "JOB_SUBMITTED", "VERIFICATION_COMPLETED",
    ]
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


# --- vision provider wiring ---

def test_missing_api_key_gives_503(client, db, make_job, monkeypatch):
    job = _ready(client, make_job, db)
    del app.dependency_overrides[get_vision_provider]  # use the real provider factory
    monkeypatch.setattr(get_settings(), "gemini_api_key", "")
    r = client.post(f"/api/jobs/{job.id}/submit")
    assert r.status_code == 503
    assert r.json() == {"detail": "Vision check unavailable: GEMINI_API_KEY is not set"}
    db.refresh(job)
    assert job.status == "AUTHORIZED"  # nothing happened to the job


def test_get_vision_provider_builds_gemini_from_settings(monkeypatch):
    monkeypatch.setattr(get_settings(), "gemini_api_key", "test-key")
    provider = get_vision_provider()
    assert isinstance(provider, GeminiProvider)
    assert provider.api_key == "test-key"
    assert provider.model == get_settings().gemini_model

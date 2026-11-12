import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.audit import verify_chain
from app.config import get_settings
from app.db import get_db
from app.main import app
from app.models import Approval, AuditLog, ChecklistItem, Cleaner, Payment, Payout, Photo, Verification
from app.paypal.client import PayPalError, get_paypal_client
from app.vision import VisionError, get_vision_provider
from app.vision.base import ItemResult, VisionResult
from app.vision.gemini import GeminiProvider
from tests.fakes import FakePayPal

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
WEBP = b"RIFF" + b"\x24\x00\x00\x00" + b"WEBP" + b"VP8 " + b"0" * 32


class FakeVision:
    model = "fake-vision"

    def __init__(self, fail_items=(), error=None):
        self.fail_items = set(fail_items)
        self.error = error
        self.calls = []

    def verify(self, before, after, checklist, strict=False):
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
def paypal():
    return FakePayPal()


@pytest.fixture(autouse=True)
def cleaner_email(monkeypatch):
    monkeypatch.setattr(get_settings(), "paypal_cleaner_email", "cleaner@example.com")


@pytest.fixture
def client(db, vision, paypal):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_vision_provider] = lambda: vision
    app.dependency_overrides[get_paypal_client] = lambda: paypal
    yield TestClient(app)
    app.dependency_overrides.clear()


def events(db):
    return db.scalars(select(AuditLog.event).order_by(AuditLog.id)).all()


def _post(client, job, kind, data=JPEG):
    return client.post(f"/api/jobs/{job.id}/photos", params={"kind": kind}, content=data,
                       headers={"Content-Type": "image/jpeg"})


@pytest.fixture
def owner(db):
    """The cleaner whose job list the tests read; GET /api/jobs is always scoped to one cleaner."""
    c = Cleaner(name="Owner", paypal_email="owner@example.com")
    db.add(c)
    db.commit()
    return c


def _own(db, owner, *jobs):
    for j in jobs:
        j.cleaner_id = owner.id
    db.commit()


def _list(client, owner, **params):
    r = client.get("/api/jobs", params={"cleaner_id": str(owner.id), **params})
    assert r.status_code == 200, r.text
    return r.json()


def _ready(client, make_job, db):
    job = make_job("AUTHORIZED")
    # make_job creates no checklist; real jobs get a copy of the tier template at booking.
    job.checklist_items = [ChecklistItem(label=l, required=True, position=i)
                           for i, l in enumerate(["Kitchen", "Bathroom", "Floors", "Surfaces"])]
    db.add(Payment(job_id=job.id, order_id=f"ORDER-{job.id}", authorization_id="A1", status="AUTHORIZED"))
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


def test_upload_sniffs_webp(client, db, make_job):
    r = _post(client, make_job("AUTHORIZED"), "before", WEBP)
    assert r.status_code == 201
    assert r.json()["content_type"] == "image/webp"
    assert db.scalar(select(Photo)).data == WEBP


@pytest.mark.parametrize("data", [
    b"RIFF" + b"\x24\x00\x00\x00" + b"WAVE" + b"fmt " + b"0" * 32,  # RIFF, but audio
    b"RIFF" + b"\x24\x00\x00\x00" + b"WEB",  # truncated before the type tag
])
def test_upload_rejects_non_webp_riff(client, make_job, data):
    assert _post(client, make_job("AUTHORIZED"), "before", data).status_code == 415


def test_upload_trusts_bytes_not_the_content_type_header(client, db, make_job):
    job = make_job("AUTHORIZED")
    r = client.post(f"/api/jobs/{job.id}/photos", params={"kind": "before"}, content=WEBP,
                    headers={"Content-Type": "image/jpeg"})
    assert r.json()["content_type"] == "image/webp"


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
    # all items pass at $10, so the policy engine auto-releases and settlement captures straight away
    assert data["status"] == "CAPTURED"
    assert data["payout"] == {"amount": "10.00", "status": "PENDING"}
    assert data["decision"]["outcome"] == "auto_release"
    assert data["verification"]["model"] == "fake-vision"
    assert data["verification"]["score"] == "1.00"
    assert data["verification"]["results"]["overall_pass"] is True
    assert [i["item"] for i in data["verification"]["results"]["items"]] == ["Kitchen", "Bathroom", "Floors", "Surfaces"]
    assert vision.calls == [(1, 1, ["Kitchen", "Bathroom", "Floors", "Surfaces"])]
    events = db.scalars(select(AuditLog.event).order_by(AuditLog.id)).all()
    assert events == ["PHOTO_UPLOADED", "PHOTO_UPLOADED", "JOB_SUBMITTED", "VERIFICATION_COMPLETED",
                      "POLICY_DECIDED", "CAPTURE_COMPLETED", "PAYOUT_CREATED"]
    assert verify_chain(db) is None


def test_reclean_after_rejection_resubmits_and_latest_verification_wins(client, db, make_job, vision):
    vision.fail_items = {"Kitchen"}
    job = _ready(client, make_job, db)
    first = client.post(f"/api/jobs/{job.id}/submit").json()
    assert first["verification"]["results"]["overall_pass"] is False
    assert first["status"] == "REJECTED"
    assert first["decision"]["outcome"] == "reject"
    assert _post(client, job, "after").status_code == 201  # a REJECTED job is editable again

    vision.fail_items = set()
    second = client.post(f"/api/jobs/{job.id}/submit")
    assert second.status_code == 200
    assert second.json()["status"] == "CAPTURED"
    assert second.json()["decision"]["outcome"] == "auto_release"
    assert second.json()["verification"]["results"]["overall_pass"] is True
    assert second.json()["verification"]["id"] != first["verification"]["id"]
    assert len(db.scalars(select(Verification)).all()) == 2
    assert client.get(f"/api/jobs/{job.id}").json()["verification"]["id"] == second.json()["verification"]["id"]
    assert events(db) == [
        "PHOTO_UPLOADED", "PHOTO_UPLOADED", "JOB_SUBMITTED", "VERIFICATION_COMPLETED", "POLICY_DECIDED",
        "PHOTO_UPLOADED", "JOB_SUBMITTED", "VERIFICATION_COMPLETED", "POLICY_DECIDED",
        "CAPTURE_COMPLETED", "PAYOUT_CREATED",
    ]
    assert verify_chain(db) is None


def test_list_jobs_includes_latest_verification(client, db, make_job, vision, owner):
    vision.fail_items = {"Kitchen"}
    verified = _ready(client, make_job, db)
    first = client.post(f"/api/jobs/{verified.id}/submit").json()["verification"]
    waiting = make_job("AUTHORIZED")
    _own(db, owner, verified, waiting)

    # Re-clean (the failed check rejected the job): the list must show the newest verification.
    assert _post(client, verified, "after").status_code == 201
    vision.fail_items = set()
    second = client.post(f"/api/jobs/{verified.id}/submit").json()["verification"]

    rows = {r["id"]: r for r in _list(client, owner)}
    assert rows[str(verified.id)]["decision"]["outcome"] == "auto_release"  # latest decision, not the reject
    assert rows[str(waiting.id)]["decision"] is None
    assert rows[str(verified.id)]["verification"]["id"] == second["id"] != first["id"]
    assert rows[str(verified.id)]["verification"]["results"]["overall_pass"] is True
    assert rows[str(waiting.id)]["verification"] is None

    by_status = _list(client, owner, status="CAPTURED")
    assert [r["id"] for r in by_status] == [str(verified.id)]
    assert by_status[0]["verification"]["id"] == second["id"]


def test_failed_items_recorded(client, db, make_job, vision):
    vision.fail_items = {"Kitchen"}
    job = _ready(client, make_job, db)
    data = client.post(f"/api/jobs/{job.id}/submit").json()
    assert data["status"] == "REJECTED"
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
    assert "POLICY_DECIDED" not in events(db)
    assert client.get(f"/api/jobs/{job.id}").json()["decision"] is None

    vision.error = None
    r = client.post(f"/api/jobs/{job.id}/verify")
    assert r.status_code == 200 and r.json()["status"] == "CAPTURED"
    assert r.json()["decision"]["outcome"] == "auto_release"
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


# --- policy decisions ---

def _decision_events(db):
    return db.scalars(select(AuditLog).where(AuditLog.event == "POLICY_DECIDED").order_by(AuditLog.id)).all()


def test_submit_rejects_when_score_is_under_minimum(client, db, make_job, vision):
    vision.fail_items = {"Kitchen"}  # 3 of 4 visible items pass -> 0.75 < 0.80
    job = _ready(client, make_job, db)
    data = client.post(f"/api/jobs/{job.id}/submit").json()
    assert data["status"] == "REJECTED"
    assert data["decision"]["outcome"] == "reject"
    assert any("below the minimum" in r for r in data["decision"]["reasons"])
    (row,) = _decision_events(db)
    assert (row.actor, row.from_status, row.to_status) == ("policy-engine", "VERIFIED", "REJECTED")
    assert row.payload["rules"]["min_score"] == "0.80"
    assert db.scalars(select(Approval)).all() == []
    assert verify_chain(db) is None


def test_submit_needs_approval_above_ceiling(client, db, make_job):
    job = _ready(client, make_job, db)
    job.amount = Decimal("30.00")
    db.commit()
    data = client.post(f"/api/jobs/{job.id}/submit").json()
    assert data["status"] == "PENDING_APPROVAL"
    assert data["decision"] == {
        "outcome": "needs_approval",
        "reasons": ["Amount $30.00 is above the auto-release ceiling of $25.00"],
    }
    approval = db.scalar(select(Approval))
    assert (approval.job_id, approval.status) == (job.id, "PENDING")
    assert events(db)[-3:] == ["JOB_SUBMITTED", "VERIFICATION_COMPLETED", "POLICY_DECIDED"]
    assert verify_chain(db) is None


def test_submit_auto_releases_within_rules(client, db, make_job):
    job = _ready(client, make_job, db)
    data = client.post(f"/api/jobs/{job.id}/submit").json()
    assert data["status"] == "CAPTURED"
    assert data["decision"]["outcome"] == "auto_release"
    assert db.scalars(select(Approval)).all() == []
    assert verify_chain(db) is None


def test_decision_in_detail_and_list_responses(client, db, make_job, owner):
    job = _ready(client, make_job, db)
    _own(db, owner, job)
    job.amount = Decimal("30.00")
    db.commit()
    client.post(f"/api/jobs/{job.id}/submit")
    detail = client.get(f"/api/jobs/{job.id}").json()["decision"]
    listed = {r["id"]: r for r in _list(client, owner)}[str(job.id)]["decision"]
    assert detail == listed
    assert detail["outcome"] == "needs_approval"


def test_list_decisions_do_not_add_a_query_per_job(client, db, make_job, owner):
    from sqlalchemy import event as sa_event

    for _ in range(3):
        j = _ready(client, make_job, db)
        _own(db, owner, j)
        client.post(f"/api/jobs/{j.id}/submit")

    def count_list_queries():
        n = []
        listener = lambda *a: n.append(1)  # noqa: E731
        sa_event.listen(db.get_bind(), "before_cursor_execute", listener)
        try:
            assert len(_list(client, owner)) >= 3
        finally:
            sa_event.remove(db.get_bind(), "before_cursor_execute", listener)
        return len(n)

    three = count_list_queries()
    for _ in range(3):
        j = _ready(client, make_job, db)
        _own(db, owner, j)
        client.post(f"/api/jobs/{j.id}/submit")
    assert count_list_queries() == three


def test_verify_retry_also_applies_the_policy(client, db, make_job, vision):
    job = _ready(client, make_job, db)
    job.amount = Decimal("30.00")
    db.commit()
    vision.error = VisionError("Gemini error 503")
    assert client.post(f"/api/jobs/{job.id}/submit").status_code == 502
    vision.error = None
    data = client.post(f"/api/jobs/{job.id}/verify").json()
    assert data["status"] == "PENDING_APPROVAL"
    assert len(_decision_events(db)) == 1


def test_decide_failure_leaves_job_verified(client, db, make_job, monkeypatch):
    import app.api.cleaner as cleaner

    def boom(db, job):
        raise RuntimeError("engine down")

    monkeypatch.setattr(cleaner, "decide", boom)
    job = _ready(client, make_job, db)
    with pytest.raises(RuntimeError):
        client.post(f"/api/jobs/{job.id}/submit")
    db.refresh(job)
    assert job.status == "VERIFIED"
    assert "POLICY_DECIDED" not in events(db)
    # /verify only accepts SUBMITTED jobs, so a stuck VERIFIED job is not retryable (known gap).
    assert client.post(f"/api/jobs/{job.id}/verify").status_code == 409


# --- approval endpoint ---

def _pending(client, make_job, db):
    """A $30 job that passed vision, so the policy engine parked it in PENDING_APPROVAL."""
    job = _ready(client, make_job, db)
    job.amount = Decimal("30.00")
    db.commit()
    assert client.post(f"/api/jobs/{job.id}/submit").json()["status"] == "PENDING_APPROVAL"
    return job


def _approval(client, job, decision="approve", **kw):
    body = {"decision": decision, "decided_by": "owner", **kw}
    return client.post(f"/api/jobs/{job.id}/approval", json=body)


def test_approve_releases_job(client, db, make_job):
    job = _pending(client, make_job, db)
    r = _approval(client, job, reason="Looks fine")
    assert r.status_code == 200
    assert r.json()["status"] == "CAPTURED"
    a = db.scalar(select(Approval))
    assert (a.status, a.decided_by, a.reason) == ("APPROVED", "owner", "Looks fine")
    assert a.decided_at is not None
    row = db.scalar(select(AuditLog).where(AuditLog.event == "APPROVAL_APPROVED"))
    assert (row.event, row.actor, row.from_status, row.to_status) == (
        "APPROVAL_APPROVED", "admin", "PENDING_APPROVAL", "RELEASED")
    assert row.payload == {"decided_by": "owner", "reason": "Looks fine"}
    assert verify_chain(db) is None


def test_deny_rejects_job_and_cleaner_can_reclean(client, db, make_job):
    job = _pending(client, make_job, db)
    r = _approval(client, job, "deny")
    assert r.json()["status"] == "REJECTED"
    a = db.scalar(select(Approval))
    assert (a.status, a.decided_by) == ("DENIED", "owner")
    assert a.reason is not None  # keeps the policy engine's reason when none is given
    assert events(db)[-1] == "APPROVAL_DENIED"
    assert _post(client, job, "after").status_code == 201
    assert client.post(f"/api/jobs/{job.id}/submit").json()["status"] == "PENDING_APPROVAL"
    assert verify_chain(db) is None


def test_approval_on_job_that_is_not_pending_is_409(client, db, make_job):
    job = _ready(client, make_job, db)  # AUTHORIZED
    r = _approval(client, job)
    assert r.status_code == 409
    assert "AUTHORIZED" in r.json()["detail"]
    assert db.scalars(select(Approval)).all() == []
    assert "APPROVAL_APPROVED" not in events(db)


def test_approval_on_unknown_job_is_404(client):
    assert client.post(f"/api/jobs/{uuid.uuid4()}/approval",
                       json={"decision": "approve", "decided_by": "owner"}).status_code == 404


def test_second_decision_is_409_and_changes_nothing(client, db, make_job):
    job = _pending(client, make_job, db)
    assert _approval(client, job, "approve").status_code == 200
    assert _approval(client, job, "deny").status_code == 409
    assert _approval(client, job, "approve").status_code == 409
    db.refresh(job)
    assert job.status == "CAPTURED"
    assert db.scalar(select(Approval)).status == "APPROVED"
    assert events(db).count("APPROVAL_APPROVED") == 1
    assert "APPROVAL_DENIED" not in events(db)


@pytest.mark.parametrize("body", [
    {"decision": "maybe", "decided_by": "owner"},
    {"decision": "approve"},
    {"decision": "approve", "decided_by": ""},
])
def test_approval_validates_body(client, db, make_job, body):
    job = _pending(client, make_job, db)
    assert client.post(f"/api/jobs/{job.id}/approval", json=body).status_code == 422
    db.refresh(job)
    assert job.status == "PENDING_APPROVAL"


def test_pending_job_without_approval_row_is_409_and_unchanged(client, db, make_job):
    job = make_job("PENDING_APPROVAL")
    assert _approval(client, job).status_code == 409
    db.refresh(job)
    assert job.status == "PENDING_APPROVAL"
    assert events(db) == []


# --- settlement hooks ---

def test_auto_released_job_is_captured_and_payout_requested(client, db, make_job, paypal):
    job = _ready(client, make_job, db)
    data = client.post(f"/api/jobs/{job.id}/submit").json()
    assert data["status"] == "CAPTURED"
    assert paypal.capture_calls == [("A1", Decimal("10.00"), "USD")]
    assert [c[1:] for c in paypal.payout_calls] == [("cleaner@example.com", Decimal("10.00"), "USD")]
    assert db.scalar(select(Payout)).status == "PENDING"
    assert verify_chain(db) is None


def test_approved_job_is_captured(client, db, make_job, paypal):
    job = _pending(client, make_job, db)
    assert paypal.capture_calls == []  # parked, nothing moves before approval
    data = _approval(client, job).json()
    assert data["status"] == "CAPTURED"
    assert data["payout"] == {"amount": "30.00", "status": "PENDING"}
    assert paypal.capture_calls == [("A1", Decimal("30.00"), "USD")]
    assert verify_chain(db) is None


def test_denied_job_moves_no_money(client, db, make_job, paypal):
    job = _pending(client, make_job, db)
    _approval(client, job, "deny")
    assert paypal.capture_calls == [] and paypal.payout_calls == []


def test_capture_failure_still_returns_the_released_job_and_settle_retries(client, db, make_job, paypal):
    paypal.capture_error = PayPalError("boom", status_code=503, debug_id="d1")
    job = _ready(client, make_job, db)
    r = client.post(f"/api/jobs/{job.id}/submit")
    assert r.status_code == 200
    assert r.json()["status"] == "RELEASED"
    assert r.json()["payout"] is None
    assert events(db)[-1] == "CAPTURE_ERROR"

    paypal.capture_error = None
    r = client.post(f"/api/jobs/{job.id}/settle")
    assert r.status_code == 200 and r.json()["status"] == "CAPTURED"
    assert r.json()["payout"]["status"] == "PENDING"
    assert verify_chain(db) is None


def test_db_failure_during_settle_does_not_break_the_decision(client, db, make_job, monkeypatch):
    import app.api.cleaner as cleaner

    def boom(db, job, paypal):
        raise RuntimeError("db down")

    monkeypatch.setattr("app.settlement.settle", boom)
    job = _ready(client, make_job, db)
    r = client.post(f"/api/jobs/{job.id}/submit")
    assert r.status_code == 200
    assert r.json()["status"] == "RELEASED"
    assert r.json()["decision"]["outcome"] == "auto_release"


def test_manual_settle_does_not_swallow_errors(client, db, make_job, monkeypatch):
    job = _ready(client, make_job, db)
    job.status = "RELEASED"
    db.commit()

    def boom(db, job, paypal):
        raise RuntimeError("db down")

    monkeypatch.setattr("app.api.cleaner.settle", boom)
    with pytest.raises(RuntimeError):
        client.post(f"/api/jobs/{job.id}/settle")


def test_settle_twice_pays_once(client, db, make_job, paypal):
    job = _ready(client, make_job, db)
    client.post(f"/api/jobs/{job.id}/submit")
    r = client.post(f"/api/jobs/{job.id}/settle")  # polls; the fake says the item succeeded
    assert r.json()["status"] == "PAID_OUT"
    assert r.json()["payout"]["status"] == "SUCCESS"
    again = client.post(f"/api/jobs/{job.id}/settle")  # PAID_OUT: returned as is, no PayPal calls
    assert again.status_code == 200 and again.json()["status"] == "PAID_OUT"
    assert again.json()["payout"]["status"] == "SUCCESS"
    assert paypal.batch_calls == ["BATCH1"]
    assert len(paypal.capture_calls) == 1 and len(paypal.payout_calls) == 1


def test_settle_404_and_409(client, db, make_job):
    assert client.post(f"/api/jobs/{uuid.uuid4()}/settle").status_code == 404
    job = _ready(client, make_job, db)  # AUTHORIZED
    r = client.post(f"/api/jobs/{job.id}/settle")
    assert r.status_code == 409 and "AUTHORIZED" in r.json()["detail"]


def test_payout_is_in_detail_and_list(client, db, make_job, owner):
    captured = _ready(client, make_job, db)
    client.post(f"/api/jobs/{captured.id}/submit")
    waiting = make_job("AUTHORIZED")
    _own(db, owner, captured, waiting)
    detail = client.get(f"/api/jobs/{captured.id}").json()
    assert detail["payout"] == {"amount": "10.00", "status": "PENDING"}
    rows = {r["id"]: r for r in _list(client, owner)}
    assert rows[str(captured.id)]["payout"] == {"amount": "10.00", "status": "PENDING"}
    assert rows[str(waiting.id)]["payout"] is None

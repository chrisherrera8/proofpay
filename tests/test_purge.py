"""The 24-hour scrub: expired cleaners and their jobs' photos go; jobs and the audit log stay."""
import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

import app.cleaners as cleaners_mod
from app.audit import append_audit, verify_chain
from app.cleaners import purge_expired, purge_if_due
from app.config import get_settings
from app.db import get_db
from app.main import app
from app.models import AuditLog, Cleaner, Job, Photo

UTC = dt.timezone.utc
DAY = dt.date(2026, 11, 20)
JPEG = b"\xff\xd8\xff\xe0fake"


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def fresh_throttle(monkeypatch):
    monkeypatch.setattr(cleaners_mod, "_last_purge", 0.0)
    monkeypatch.setattr(get_settings(), "paypal_cleaner_email", "")


@pytest.fixture
def make_cleaner(db):
    def _make(name, hours_old, is_seed=False) -> Cleaner:
        c = Cleaner(name=name, paypal_email=f"{name.lower()}@example.com", is_seed=is_seed,
                    created_at=dt.datetime.now(UTC) - dt.timedelta(hours=hours_old))
        db.add(c)
        db.commit()
        return c

    return _make


@pytest.fixture
def booked(db, make_job):
    """Factory: a job for a cleaner, with a before and an after photo and a photo audit row."""
    def _book(cleaner) -> Job:
        job = make_job("AUTHORIZED")
        job.cleaner_id, job.service_date = cleaner.id, DAY
        db.add_all([Photo(job_id=job.id, kind=k, data=JPEG, content_type="image/jpeg") for k in ("before", "after")])
        append_audit(db, job_id=job.id, actor="cleaner", event="PHOTO_UPLOADED", payload={"kind": "before"})
        db.commit()
        return job

    return _book


def names(db):
    return {c.name for c in db.scalars(select(Cleaner))}


def photo_count(db, job):
    return len(db.scalars(select(Photo).where(Photo.job_id == job.id)).all())


def test_expired_cleaners_and_their_photos_go_but_jobs_stay_scrubbed(db, make_cleaner, booked):
    old, fresh = make_cleaner("Old", 25), make_cleaner("Fresh", 23)
    old_job, fresh_job = booked(old), booked(fresh)
    assert purge_expired(db) == {"cleaners": 1, "photos": 2}
    assert names(db) == {"Fresh"}
    db.refresh(old_job)
    assert old_job.cleaner_id is None and old_job.service_date == DAY and old_job.status == "AUTHORIZED"
    assert photo_count(db, old_job) == 0
    assert photo_count(db, fresh_job) == 2 and fresh_job.cleaner_id == fresh.id


def test_default_cleaner_is_never_purged(db, make_cleaner, booked):
    default = make_cleaner("Default", 24 * 90, is_seed=True)
    job = booked(default)
    assert purge_expired(db) == {"cleaners": 0, "photos": 0}
    assert names(db) == {"Default"} and photo_count(db, job) == 2


def test_audit_rows_survive_and_the_chain_still_verifies(db, make_cleaner, booked):
    job = booked(make_cleaner("Old", 30))
    before = db.scalars(select(AuditLog.id)).all()
    purge_expired(db)
    assert set(before) <= set(db.scalars(select(AuditLog.id)).all())
    assert [r.event for r in db.scalars(select(AuditLog).where(AuditLog.job_id == job.id))] == ["PHOTO_UPLOADED"]
    assert verify_chain(db) is None


def test_one_count_only_audit_row_is_written_and_none_when_nothing_expired(db, make_cleaner, booked):
    booked(make_cleaner("Old", 30)), make_cleaner("Other", 40)
    purge_expired(db)
    row = db.scalars(select(AuditLog).where(AuditLog.event == "CLEANERS_PURGED")).one()
    assert (row.job_id, row.actor, row.payload) == (None, "system", {"cleaners": 2, "photos": 2})
    assert "old@example.com" not in str(row.payload) and "Old" not in str(row.payload)
    assert purge_expired(db) == {"cleaners": 0, "photos": 0}  # idempotent
    assert len(db.scalars(select(AuditLog).where(AuditLog.event == "CLEANERS_PURGED")).all()) == 1
    assert verify_chain(db) is None


def test_exactly_24_hours_old_is_expired(db, make_cleaner):
    make_cleaner("Edge", 24.01)
    make_cleaner("Young", 23.99)
    purge_expired(db)
    assert names(db) == {"Young"}


# --- when it runs --------------------------------------------------------------------------------

def test_the_roster_purges_lazily_at_most_once_a_minute(client, db, make_cleaner, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(cleaners_mod.time, "monotonic", lambda: clock[0])
    make_cleaner("Old", 25)
    client.get("/api/cleaners", params={"date": DAY.isoformat()})
    assert names(db) == set()
    make_cleaner("Old2", 25)
    clock[0] += 30
    client.get("/api/cleaners", params={"date": DAY.isoformat()})
    assert names(db) == {"Old2"}  # throttled: not purged yet (but hidden from the roster either way)
    clock[0] += 31
    client.get("/api/cleaners", params={"date": DAY.isoformat()})
    assert names(db) == set()


def test_a_failing_purge_never_breaks_the_roster(client, make_cleaner, monkeypatch):
    def boom(_):
        raise RuntimeError("db hiccup")

    monkeypatch.setattr(cleaners_mod, "purge_expired", boom)
    make_cleaner("Fresh", 1)
    r = client.get("/api/cleaners", params={"date": DAY.isoformat()})
    assert r.status_code == 200 and [c["name"] for c in r.json()] == ["Fresh"]


def test_purge_if_due_swallows_errors_and_rolls_back(db, monkeypatch):
    monkeypatch.setattr(cleaners_mod, "purge_expired", lambda _: 1 / 0)
    purge_if_due(db)  # must not raise
    assert db.execute(text("SELECT 1")).scalar() == 1  # the session is still usable


# --- the maintenance endpoint --------------------------------------------------------------------

@pytest.fixture
def token(monkeypatch):
    monkeypatch.setattr(get_settings(), "maintenance_token", "s3cret")
    return {"Authorization": "Bearer s3cret"}


def test_purge_endpoint_with_the_right_token(client, db, make_cleaner, booked, token):
    booked(make_cleaner("Old", 25))
    r = client.post("/api/maintenance/purge", headers=token)
    assert r.status_code == 200 and r.json() == {"cleaners": 1, "photos": 2}
    assert names(db) == set()


@pytest.mark.parametrize("header", [None, "", "Bearer wrong", "s3cret", "Basic s3cret", "Bearer "])
def test_purge_endpoint_rejects_missing_or_wrong_tokens(client, db, make_cleaner, token, header):
    make_cleaner("Old", 25)
    headers = {"Authorization": header} if header is not None else {}
    assert client.post("/api/maintenance/purge", headers=headers).status_code == 401
    assert names(db) == {"Old"}  # nothing was deleted


def test_purge_endpoint_is_503_when_no_token_is_configured(client, db, make_cleaner, monkeypatch):
    monkeypatch.setattr(get_settings(), "maintenance_token", "")
    make_cleaner("Old", 25)
    for headers in ({}, {"Authorization": "Bearer "}):  # an empty token must not match an empty setting
        assert client.post("/api/maintenance/purge", headers=headers).status_code == 503
    assert names(db) == {"Old"}


def test_purge_endpoint_only_accepts_post(client, token):
    assert client.get("/api/maintenance/purge", headers=token).status_code == 405

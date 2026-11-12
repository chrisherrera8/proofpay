import datetime as dt

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.cleaners import ensure_default_cleaner, touch_cleaner
from app.config import get_settings
from app.db import engine, get_db
from app.main import app
from app.models import Cleaner, Job

DAY = dt.date(2026, 11, 20)
SIGNUP = {"name": "Grace Hopper", "paypal_email": "grace@example.com"}


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def no_default(monkeypatch):
    monkeypatch.setattr(get_settings(), "paypal_cleaner_email", "")


@pytest.fixture
def make_cleaner(db):
    def _make(name="Cleaner", age=dt.timedelta(0), is_seed=False) -> Cleaner:
        c = Cleaner(name=name, paypal_email=f"{name.lower()}@example.com", is_seed=is_seed,
                    created_at=dt.datetime.now(dt.timezone.utc) - age, last_used_at=dt.datetime.now(dt.timezone.utc) - age)
        db.add(c)
        db.commit()
        return c

    return _make


def book(db, make_job, cleaner, day=DAY, status="AUTHORIZED", age=dt.timedelta(0)) -> Job:
    job = make_job(status)
    job.cleaner_id, job.service_date = cleaner.id, day
    job.created_at = dt.datetime.now(dt.timezone.utc) - age
    db.commit()
    return job


def roster(client, day=DAY, **params):
    r = client.get("/api/cleaners", params={"date": day.isoformat(), **params})
    assert r.status_code == 200, r.text
    return {c["name"]: c for c in r.json()}


# --- sign-up -------------------------------------------------------------------------------------

def test_sign_up_returns_cleaner_without_email(client, db):
    r = client.post("/api/cleaners", json=SIGNUP)
    assert r.status_code == 201
    data = r.json()
    assert data["name"] == "Grace Hopper" and data["is_seed"] is False
    assert "paypal_email" not in data
    assert db.get(Cleaner, data["id"]).paypal_email == "grace@example.com"


@pytest.mark.parametrize("body", [
    {"name": "Grace Hopper"},
    {"name": "Grace Hopper", "paypal_email": ""},
    {"name": "Grace Hopper", "paypal_email": "not-an-email"},
    {"name": "", "paypal_email": "grace@example.com"},
    {"name": "   ", "paypal_email": "grace@example.com"},
])
def test_sign_up_requires_name_and_valid_paypal_email(client, body):
    assert client.post("/api/cleaners", json=body).status_code == 422


def test_sign_up_trims_whitespace(client, db):
    r = client.post("/api/cleaners", json={"name": "  Grace  ", "paypal_email": " grace@example.com "})
    assert r.status_code == 201 and r.json()["name"] == "Grace"
    assert db.get(Cleaner, r.json()["id"]).paypal_email == "grace@example.com"


def test_the_same_email_from_a_new_browser_is_refused_until_confirmed(client, db):
    first = client.post("/api/cleaners", json=SIGNUP)
    other = {"name": "Someone Else", "paypal_email": "GRACE@Example.com "}
    r = client.post("/api/cleaners", json=other)
    assert first.status_code == 201 and r.status_code == 409 and "already exists" in r.json()["detail"]
    again = client.post("/api/cleaners", json={**other, "confirmed": True})
    assert again.status_code == 200
    assert again.json()["id"] == first.json()["id"] and again.json()["name"] == "Grace Hopper"
    assert db.query(Cleaner).filter(Cleaner.paypal_email.ilike("grace@example.com")).count() == 1


def test_the_same_browser_resumes_without_confirming(client):
    first = client.post("/api/cleaners", json=SIGNUP).json()
    again = client.post("/api/cleaners", json={**SIGNUP, "known_id": first["id"]})
    assert again.status_code == 200 and again.json()["id"] == first["id"]
    # A different cleaner's id is not proof.
    other = client.post("/api/cleaners", json={**SIGNUP, "known_id": "00000000-0000-0000-0000-000000000000"})
    assert other.status_code == 409


def test_a_refused_sign_up_does_not_restart_the_clock(client, db, make_cleaner):
    c = make_cleaner("Grace", age=dt.timedelta(hours=20))
    before = c.last_used_at
    assert client.post("/api/cleaners", json={"name": "Grace", "paypal_email": "grace@example.com"}).status_code == 409
    db.refresh(c)
    assert c.last_used_at == before


def test_confirmed_sign_up_restarts_the_clock_of_the_existing_cleaner(client, db, make_cleaner):
    c = make_cleaner("Grace", age=dt.timedelta(hours=20))
    body = {"name": "Grace", "paypal_email": "grace@example.com", "confirmed": True}
    assert client.post("/api/cleaners", json=body).status_code == 200
    db.refresh(c)
    assert dt.datetime.now(dt.timezone.utc) - c.last_used_at < dt.timedelta(minutes=1)


def test_an_expired_cleaner_does_not_block_signing_up_with_its_email(client, db, make_cleaner):
    old = make_cleaner("Grace", age=dt.timedelta(hours=25))
    r = client.post("/api/cleaners", json={"name": "Grace", "paypal_email": "grace@example.com"})
    assert r.status_code == 201 and r.json()["id"] != str(old.id)


def test_the_default_cleaners_email_is_not_reused_by_sign_up(client, make_cleaner):
    seed = make_cleaner("Grace", is_seed=True)
    r = client.post("/api/cleaners", json={"name": "Grace", "paypal_email": "grace@example.com"})
    assert r.status_code == 201 and r.json()["id"] != str(seed.id)


# --- roster and availability ---------------------------------------------------------------------

def test_roster_marks_a_booked_cleaner_unavailable_only_on_that_day(client, db, make_job, make_cleaner, no_default):
    busy, free = make_cleaner("Busy"), make_cleaner("Free")
    book(db, make_job, busy)
    assert roster(client)["Busy"]["available"] is False
    assert roster(client)["Free"]["available"] is True
    assert roster(client, DAY + dt.timedelta(days=1))["Busy"]["available"] is True


def test_available_filter_hides_booked_cleaners(client, db, make_job, make_cleaner, no_default):
    book(db, make_job, make_cleaner("Busy"))
    make_cleaner("Free")
    assert set(roster(client, available="true")) == {"Free"}
    assert set(roster(client)) == {"Busy", "Free"}


def test_unpaid_booking_holds_the_cleaner_for_30_minutes_only(client, db, make_job, make_cleaner, no_default):
    c = make_cleaner("Held")
    book(db, make_job, c, status="BOOKED", age=dt.timedelta(minutes=5))
    assert roster(client)["Held"]["available"] is False
    db.execute(text("UPDATE jobs SET created_at = now() - interval '31 minutes'"))
    assert roster(client)["Held"]["available"] is True


def test_old_booked_job_does_not_release_an_authorized_one(client, db, make_job, make_cleaner, no_default):
    c = make_cleaner("Busy")
    book(db, make_job, c, status="BOOKED", age=dt.timedelta(hours=2))
    book(db, make_job, c, status="AUTHORIZED", age=dt.timedelta(hours=2))
    assert roster(client)["Busy"]["available"] is False


def test_paid_out_job_frees_the_cleaner_for_that_day(client, db, make_job, make_cleaner, no_default):
    c = make_cleaner("Done")
    book(db, make_job, c, status="PAID_OUT")
    assert roster(client)["Done"]["available"] is True
    assert set(roster(client, available="true")) == {"Done"}


def test_captured_job_still_holds_the_day_until_paid_out(client, db, make_job, make_cleaner, no_default):
    book(db, make_job, make_cleaner("Waiting"), status="CAPTURED")
    assert roster(client)["Waiting"]["available"] is False


def test_paid_out_job_does_not_release_another_active_job_that_day(client, db, make_job, make_cleaner, no_default):
    c = make_cleaner("Busy")
    book(db, make_job, c, status="PAID_OUT")
    book(db, make_job, c, status="AUTHORIZED")
    assert roster(client)["Busy"]["available"] is False


def test_roster_needs_a_valid_date(client):
    assert client.get("/api/cleaners").status_code == 422
    assert client.get("/api/cleaners", params={"date": "tomorrow"}).status_code == 422


# --- expiry --------------------------------------------------------------------------------------

def test_signups_expire_after_24_hours_but_the_default_does_not(client, db, make_cleaner, no_default):
    make_cleaner("Fresh", age=dt.timedelta(hours=23))
    old = make_cleaner("Stale", age=dt.timedelta(hours=25))
    make_cleaner("Default", age=dt.timedelta(days=30), is_seed=True)
    assert set(roster(client)) == {"Fresh", "Default"}
    assert client.get(f"/api/cleaners/{old.id}").status_code == 404


def test_expiry_counts_from_last_use_not_sign_up(client, db, make_cleaner, no_default):
    c = make_cleaner("Used", age=dt.timedelta(hours=30))
    c.created_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=48)
    c.last_used_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)
    db.commit()
    assert set(roster(client)) == {"Used"}


def _age(db, cleaner, hours):
    cleaner.last_used_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)
    db.commit()


def _used_recently(db, cleaner) -> bool:
    db.refresh(cleaner)
    return dt.datetime.now(dt.timezone.utc) - cleaner.last_used_at < dt.timedelta(minutes=1)


def test_looking_up_the_cleaner_and_their_jobs_restarts_the_clock(client, db, make_cleaner, no_default):
    c = make_cleaner("Busy")
    for call in (lambda: client.get(f"/api/cleaners/{c.id}"), lambda: client.get("/api/jobs", params={"cleaner_id": str(c.id)})):
        _age(db, c, 20)
        assert call().status_code == 200
        assert _used_recently(db, c)


def test_a_cleaner_side_action_on_a_job_restarts_the_clock(client, db, make_job, make_cleaner, no_default):
    c = make_cleaner("Busy")
    job = book(db, make_job, c)
    _age(db, c, 20)
    assert client.get(f"/api/jobs/{job.id}/photos").status_code == 200
    assert _used_recently(db, c)


def test_touching_is_throttled_and_never_revives_an_expired_cleaner(db, make_cleaner):
    fresh = make_cleaner("Fresh", age=dt.timedelta(seconds=10))
    before = fresh.last_used_at
    touch_cleaner(db, fresh.id)
    db.refresh(fresh)
    assert fresh.last_used_at == before  # under a minute old: no write
    stale = make_cleaner("Stale", age=dt.timedelta(hours=25))
    touch_cleaner(db, stale.id)
    db.refresh(stale)
    assert dt.datetime.now(dt.timezone.utc) - stale.last_used_at > dt.timedelta(hours=24)


def test_get_cleaner(client, make_cleaner, no_default):
    c = make_cleaner("Fresh")
    r = client.get(f"/api/cleaners/{c.id}")
    assert r.status_code == 200 and r.json()["name"] == "Fresh" and "paypal_email" not in r.json()
    assert client.get("/api/cleaners/00000000-0000-0000-0000-000000000000").status_code == 404


# --- the default cleaner -------------------------------------------------------------------------

def test_default_cleaner_comes_from_env_and_is_idempotent(db, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "paypal_cleaner_email", "default@example.com")
    monkeypatch.setattr(settings, "default_cleaner_name", "Sparkle Crew")
    first = ensure_default_cleaner(db)
    second = ensure_default_cleaner(db)
    assert first.id == second.id and first.is_seed
    assert (first.name, first.paypal_email) == ("Sparkle Crew", "default@example.com")
    assert len(db.scalars(select(Cleaner).where(Cleaner.is_seed)).all()) == 1


def test_default_cleaner_follows_env_changes(db, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "paypal_cleaner_email", "one@example.com")
    first = ensure_default_cleaner(db)
    monkeypatch.setattr(settings, "paypal_cleaner_email", "two@example.com")
    monkeypatch.setattr(settings, "default_cleaner_name", "New Name")
    second = ensure_default_cleaner(db)
    assert second.id == first.id and (second.name, second.paypal_email) == ("New Name", "two@example.com")


def test_no_default_cleaner_without_paypal_cleaner_email(db, no_default):
    assert ensure_default_cleaner(db) is None
    assert db.scalars(select(Cleaner)).all() == []


def test_roster_creates_the_default_cleaner_and_lists_it_first(client, make_cleaner, monkeypatch):
    monkeypatch.setattr(get_settings(), "paypal_cleaner_email", "default@example.com")
    make_cleaner("Newcomer")
    r = client.get("/api/cleaners", params={"date": DAY.isoformat()}).json()
    assert [c["name"] for c in r] == ["Sparkle Crew", "Newcomer"]
    assert r[0]["is_seed"] is True and "paypal_email" not in r[0]


def test_default_cleaner_survives_losing_the_creation_race(db, monkeypatch):
    """Another worker inserts the default cleaner between our SELECT and INSERT."""
    monkeypatch.setattr(get_settings(), "paypal_cleaner_email", "default@example.com")
    real_scalar, calls = db.scalar, []

    def scalar_after_rival_insert(*a, **kw):
        result = real_scalar(*a, **kw)
        if not calls:  # first lookup finds nothing; then the rival sneaks in
            calls.append(1)
            db.execute(text("INSERT INTO cleaners (id, name, paypal_email, is_seed) "
                            "VALUES (gen_random_uuid(), 'Rival', 'rival@example.com', true)"))
        return result

    monkeypatch.setattr(db, "scalar", scalar_after_rival_insert)
    cleaner = ensure_default_cleaner(db)
    assert cleaner.is_seed and cleaner.name == "Rival"
    assert len(db.scalars(select(Cleaner).where(Cleaner.is_seed)).all()) == 1


def test_database_allows_only_one_default_cleaner(db, make_cleaner):
    make_cleaner("A", is_seed=True)
    with pytest.raises(IntegrityError):
        make_cleaner("B", is_seed=True)
    db.rollback()


# --- jobs ----------------------------------------------------------------------------------------

def test_jobs_list_filters_by_cleaner_and_exposes_service_date(client, db, make_job, make_cleaner, no_default):
    mine, other = make_cleaner("Mine"), make_cleaner("Other")
    job = book(db, make_job, mine)
    book(db, make_job, other)
    rows = client.get("/api/jobs", params={"cleaner_id": str(mine.id)}).json()
    assert [r["id"] for r in rows] == [str(job.id)]
    assert rows[0]["cleaner_id"] == str(mine.id) and rows[0]["service_date"] == DAY.isoformat()


def test_jobs_list_never_returns_another_cleaners_jobs(client, db, make_job, make_cleaner, no_default):
    mine, other = make_cleaner("Mine"), make_cleaner("Other")
    book(db, make_job, other)
    make_job("AUTHORIZED")  # unassigned
    assert client.get("/api/jobs", params={"cleaner_id": str(mine.id)}).json() == []


def test_deleting_a_cleaner_keeps_the_job(db, make_job, make_cleaner):
    c = make_cleaner("Gone")
    job = book(db, make_job, c)
    db.delete(c)
    db.commit()
    db.refresh(job)
    assert job.cleaner_id is None and job.service_date == DAY


# --- migration -----------------------------------------------------------------------------------

def test_migration_round_trip_and_backfill():
    """Downgrade past this migration, add a job, upgrade: it gets a service_date and no cleaner."""
    cfg = Config("alembic.ini")
    try:
        command.downgrade(cfg, "a1f3c9d2e7b4")
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO jobs (id, status, customer_name, customer_email, address, service_type, scheduled_at, amount, currency)"
                " VALUES ('11111111-1111-1111-1111-111111111111', 'BOOKED', 'M', 'm@example.com', 'a', 'basic',"
                " '2026-11-10T23:30:00+00', 10, 'USD')"))
        command.upgrade(cfg, "head")
        with engine.begin() as conn:
            row = conn.execute(text("SELECT service_date, cleaner_id FROM jobs WHERE id = '11111111-1111-1111-1111-111111111111'")).one()
            conn.execute(text("DELETE FROM jobs WHERE id = '11111111-1111-1111-1111-111111111111'"))
        assert row.service_date == dt.date(2026, 11, 10) and row.cleaner_id is None
    finally:
        command.upgrade(cfg, "head")

from decimal import Decimal

import pytest
from sqlalchemy import select, update

from app.audit import verify_chain
from app.config import get_settings
from app.models import AuditLog, Job, Payment, Payout
from app.paypal.client import PayPalError
from app.settlement import mark_paid, settle
from app.state_machine import InvalidTransition
from tests.fakes import FakePayPal

CLEANER = "cleaner@example.com"


@pytest.fixture(autouse=True)
def cleaner_email(monkeypatch):
    monkeypatch.setattr(get_settings(), "paypal_cleaner_email", CLEANER)


@pytest.fixture
def paypal():
    return FakePayPal()


@pytest.fixture
def released(db, make_job):
    def _make(amount="10.00", status="RELEASED"):
        job = make_job(status)
        job.amount = Decimal(amount)
        db.add(Payment(job_id=job.id, order_id=f"O-{job.id}", authorization_id="A1",
                       authorized_amount=job.amount, status="AUTHORIZED"))
        db.commit()
        return job

    return _make


def events(db):
    return [r.event for r in db.scalars(select(AuditLog).order_by(AuditLog.id))]


def payouts(db):
    return list(db.scalars(select(Payout)))


# --- capture ---

def test_capture_moves_released_to_captured_and_creates_payout(db, released, paypal):
    job = released()
    settle(db, job, paypal)

    db.refresh(job)
    assert job.status == "CAPTURED"
    payment = db.scalar(select(Payment).where(Payment.job_id == job.id))
    assert (payment.capture_id, payment.status) == ("CAP1", "CAPTURED")
    assert paypal.capture_calls == [("A1", Decimal("10.00"), "USD")]
    (payout,) = payouts(db)
    assert (payout.batch_id, payout.status, payout.amount) == ("BATCH1", "PENDING", Decimal("10.00"))
    assert events(db) == ["CAPTURE_COMPLETED", "PAYOUT_CREATED"]
    capture_row = db.scalars(select(AuditLog).order_by(AuditLog.id)).first()
    assert (capture_row.actor, capture_row.from_status, capture_row.to_status) == (
        "paypal", "RELEASED", "CAPTURED")
    assert capture_row.payload["debug_id"] == "capdbg"
    assert verify_chain(db) is None


def test_capture_error_leaves_released_and_retry_succeeds(db, released, paypal):
    job = released()
    paypal.capture_error = PayPalError("boom", status_code=500, debug_id="d1")
    settle(db, job, paypal)

    db.refresh(job)
    assert job.status == "RELEASED"
    assert events(db) == ["CAPTURE_ERROR"]
    assert payouts(db) == []

    paypal.capture_error = None
    settle(db, job, paypal)
    db.refresh(job)
    assert job.status == "CAPTURED"
    assert len(payouts(db)) == 1


@pytest.fixture
def committed_job():
    """A RELEASED job committed for real, so separate sessions/threads can see it.

    The `db` fixture rolls everything back, so it can't be shared across connections.
    """
    from datetime import datetime, timezone

    from sqlalchemy import text

    from app.db import SessionLocal, engine
    from tests.conftest import TABLES

    with SessionLocal() as s:
        job = Job(status="RELEASED", customer_name="C", customer_email="c@example.com",
                  address="1 Test St", service_type="basic", currency="USD",
                  scheduled_at=datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc),
                  amount=Decimal("10.00"))
        s.add(job)
        s.flush()
        s.add(Payment(job_id=job.id, order_id=f"O-{job.id}", authorization_id="A1",
                      authorized_amount=job.amount, status="AUTHORIZED"))
        s.commit()
        job_id = job.id
    yield job_id
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))


def test_two_concurrent_settles_record_the_capture_once(committed_job):
    """Two real sessions on two threads. A barrier inside the PayPal capture call makes both
    capture before either records it, so the real transition() row lock decides the winner."""
    import threading

    from app.db import SessionLocal

    barrier = threading.Barrier(2, timeout=10)

    class RacingPayPal(FakePayPal):
        def capture_authorization(self, authorization_id, amount, currency):
            result = super().capture_authorization(authorization_id, amount, currency)
            barrier.wait()  # both threads now hold a capture; neither has touched the DB yet
            return result

    paypal = RacingPayPal()
    errors = []

    def run():
        try:
            with SessionLocal() as s:
                settle(s, s.get(Job, committed_job), paypal)
        except Exception as exc:  # surfaced below so a thread failure fails the test
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)

    assert errors == []
    assert len(paypal.capture_calls) == 2  # both really raced past PayPal
    with SessionLocal() as s:
        assert s.get(Job, committed_job).status == "CAPTURED"
        assert events(s).count("CAPTURE_COMPLETED") == 1
        payment = s.scalar(select(Payment).where(Payment.job_id == committed_job))
        assert (payment.capture_id, payment.status) == ("CAP1", "CAPTURED")
        assert len(payouts(s)) == 1
        assert verify_chain(s) is None


def test_stale_capture_with_unexpected_status_is_not_swallowed(db, released, paypal, monkeypatch):
    """If the transition fails and the job is NOT captured/paid, the error must propagate."""
    job = released()

    def bad_transition(*args, **kwargs):
        raise InvalidTransition("RELEASED", "CAPTURED")

    monkeypatch.setattr("app.settlement.transition", bad_transition)
    with pytest.raises(InvalidTransition):
        settle(db, job, paypal)
    db.refresh(job)
    assert job.status == "RELEASED"
    assert payouts(db) == []


def test_db_failure_after_capture_logs_rolls_back_and_retry_recaptures(
        db, released, paypal, monkeypatch, caplog):
    """The customer was charged but recording it failed. Everything the transition wrote must be rolled
    back, the capture id logged for recovery, and the error raised. A retry captures again."""
    import app.settlement as settlement

    job = released()
    real_transition = settlement.transition
    calls = []

    def transition_then_fail(*args, **kwargs):
        calls.append(1)
        result = real_transition(*args, **kwargs)  # status + audit row are flushed...
        if len(calls) == 1:
            raise RuntimeError("db down")          # ...then the write fails, so rollback matters
        return result

    monkeypatch.setattr(settlement, "transition", transition_then_fail)
    with caplog.at_level("ERROR", logger="app.settlement"):
        with pytest.raises(RuntimeError, match="db down"):
            settle(db, job, paypal)

    assert "CAP1" in caplog.text
    db.refresh(job)
    assert job.status == "RELEASED"
    assert events(db) == []
    payment = db.scalar(select(Payment).where(Payment.job_id == job.id))
    assert (payment.capture_id, payment.status) == (None, "AUTHORIZED")
    assert payouts(db) == []

    settle(db, job, paypal)  # retry
    db.refresh(job)
    assert job.status == "CAPTURED"
    assert len(paypal.capture_calls) == 2
    assert events(db) == ["CAPTURE_COMPLETED", "PAYOUT_CREATED"]
    assert verify_chain(db) is None


@pytest.mark.parametrize("status", ["PENDING", "DECLINED"])
def test_capture_not_completed_does_not_advance(db, released, paypal, status):
    job = released()
    paypal.capture_status = status
    settle(db, job, paypal)

    db.refresh(job)
    assert job.status == "RELEASED"
    assert events(db) == ["CAPTURE_ERROR"]
    assert paypal.payout_calls == []
    payment = db.scalar(select(Payment).where(Payment.job_id == job.id))
    assert payment.capture_id is None


def test_missing_authorization_is_a_capture_error(db, released, paypal):
    job = released()
    db.scalar(select(Payment).where(Payment.job_id == job.id)).authorization_id = None
    db.commit()
    settle(db, job, paypal)
    db.refresh(job)
    assert job.status == "RELEASED"
    assert events(db) == ["CAPTURE_ERROR"]
    assert paypal.capture_calls == []


# --- duplicate error rows ---

def test_repeated_identical_error_is_audited_once_even_if_debug_id_differs(db, released, paypal):
    job = released()
    for n in range(3):
        paypal.capture_error = PayPalError("boom", status_code=500, debug_id=f"d{n}")
        settle(db, job, paypal)
    assert events(db) == ["CAPTURE_ERROR"]
    first = db.scalars(select(AuditLog)).first()
    assert first.payload["debug_id"] == "d0"  # the first debug id is the one kept


def test_different_error_is_audited_again(db, released, paypal):
    job = released()
    paypal.capture_error = PayPalError("boom", status_code=500, debug_id="d1")
    settle(db, job, paypal)
    paypal.capture_error = PayPalError("nope", status_code=422, debug_id="d2")
    settle(db, job, paypal)
    assert events(db) == ["CAPTURE_ERROR", "CAPTURE_ERROR"]


def test_same_error_after_an_intervening_row_is_audited_again(db, released, paypal):
    job = released()
    err = PayPalError("boom", status_code=500, debug_id="d1")
    paypal.batch_error = err
    paypal.payout_error = err
    settle(db, job, paypal)  # captured, PAYOUT_ERROR
    paypal.payout_error = None
    settle(db, job, paypal)  # PAYOUT_CREATED resets the dedupe
    settle(db, job, paypal)  # poll fails
    settle(db, job, paypal)  # poll fails again: deduped
    assert events(db) == ["CAPTURE_COMPLETED", "PAYOUT_ERROR", "PAYOUT_CREATED", "PAYOUT_POLL_ERROR"]


# --- payout ---

def test_payout_error_leaves_captured_without_row_and_retry_succeeds(db, released, paypal):
    job = released()
    paypal.payout_error = PayPalError("boom", status_code=500, debug_id="d2")
    settle(db, job, paypal)

    db.refresh(job)
    assert job.status == "CAPTURED"
    assert payouts(db) == []
    assert events(db) == ["CAPTURE_COMPLETED", "PAYOUT_ERROR"]

    paypal.payout_error = None
    settle(db, job, paypal)
    assert len(payouts(db)) == 1
    assert events(db)[-1] == "PAYOUT_CREATED"
    assert len(paypal.capture_calls) == 1  # not captured again
    assert verify_chain(db) is None


def test_no_cleaner_email_is_a_payout_error(db, released, paypal, monkeypatch):
    monkeypatch.setattr(get_settings(), "paypal_cleaner_email", "")
    job = released()
    settle(db, job, paypal)
    db.refresh(job)
    assert job.status == "CAPTURED"
    assert paypal.payout_calls == []
    assert events(db)[-1] == "PAYOUT_ERROR"


def test_payout_created_audit_row_records_receiver_and_amount(db, released, paypal):
    job = released("20.00")
    settle(db, job, paypal)
    row = db.scalars(select(AuditLog).where(AuditLog.event == "PAYOUT_CREATED")).one()
    assert (row.actor, row.job_id) == ("system", job.id)
    assert row.payload == {"batch_id": "BATCH1", "receiver": CLEANER,
                           "amount": "20.00", "currency": "USD"}


def test_payout_db_write_failure_logs_batch_id_and_rolls_back(db, released, paypal, monkeypatch, caplog):
    """PayPal accepted the payout but recording it failed: the batch id must be logged for recovery,
    nothing half-written may remain, and the error must propagate."""
    import app.settlement as settlement

    job = released()
    real_append_audit = settlement.append_audit

    def failing_append_audit(db, **kwargs):
        if kwargs["event"] == "PAYOUT_CREATED":
            raise RuntimeError("db down")
        return real_append_audit(db, **kwargs)

    monkeypatch.setattr(settlement, "append_audit", failing_append_audit)
    with caplog.at_level("ERROR", logger="app.settlement"):
        with pytest.raises(RuntimeError, match="db down"):
            settle(db, job, paypal)

    assert any(r.name == "app.settlement" and r.levelname == "ERROR" and "BATCH1" in r.getMessage()
               for r in caplog.records)
    assert len(paypal.payout_calls) == 1
    db.refresh(job)
    assert job.status == "CAPTURED"  # the capture was committed before the payout step
    assert payouts(db) == []
    assert "PAYOUT_CREATED" not in events(db)


@pytest.mark.parametrize("amount", ["10.00", "20.00", "30.00"])
def test_payout_amount_equals_job_amount(db, released, paypal, amount):
    job = released(amount)
    settle(db, job, paypal)
    assert paypal.payout_calls == [(job.id, CLEANER, Decimal(amount), "USD")]
    assert payouts(db)[0].amount == Decimal(amount)


def test_settling_twice_never_pays_twice(db, released, paypal):
    job = released()
    settle(db, job, paypal)
    paypal.batch_item_status = "PENDING"  # still processing at PayPal
    settle(db, job, paypal)
    settle(db, job, paypal)

    assert len(paypal.capture_calls) == 1
    assert len(paypal.payout_calls) == 1
    assert len(payouts(db)) == 1
    db.refresh(job)
    assert job.status == "CAPTURED"


# --- polling fallback / mark_paid ---

def test_polling_fallback_marks_job_paid(db, released, paypal):
    job = released()
    settle(db, job, paypal)  # captured + payout pending
    settle(db, job, paypal)  # batch fetched: item succeeded

    db.refresh(job)
    assert job.status == "PAID_OUT"
    assert paypal.batch_calls == ["BATCH1"]
    (payout,) = payouts(db)
    assert (payout.status, payout.item_id) == ("SUCCESS", "ITEM1")
    assert events(db)[-1] == "PAYOUT_SUCCEEDED"
    assert verify_chain(db) is None


def test_polling_with_item_still_pending_changes_nothing(db, released, paypal):
    job = released()
    settle(db, job, paypal)
    paypal.batch_item_status = "PENDING"
    settle(db, job, paypal)
    db.refresh(job)
    assert job.status == "CAPTURED"
    assert payouts(db)[0].status == "PENDING"


def test_polling_error_changes_nothing_but_is_audited(db, released, paypal):
    job = released()
    settle(db, job, paypal)
    paypal.batch_error = PayPalError("boom", status_code=503, debug_id="pd1")
    settle(db, job, paypal)
    db.refresh(job)
    assert job.status == "CAPTURED"
    assert payouts(db)[0].status == "PENDING"
    assert events(db) == ["CAPTURE_COMPLETED", "PAYOUT_CREATED", "PAYOUT_POLL_ERROR"]
    row = db.scalars(select(AuditLog).order_by(AuditLog.id.desc())).first()
    assert row.payload == {"batch_id": "BATCH1", "http_status": 503, "debug_id": "pd1"}
    assert verify_chain(db) is None


def test_settling_a_job_whose_payout_failed_does_nothing(db, released, paypal, caplog):
    """A FAILED payout needs a human (plan: failed payouts stay CAPTURED). settle must not call
    PayPal or write audit rows, but must say why it is skipping."""
    job = released(status="CAPTURED")
    db.add(Payout(job_id=job.id, batch_id="B9", amount=job.amount, status="FAILED"))
    db.commit()

    with caplog.at_level("WARNING", logger="app.settlement"):
        settle(db, job, paypal)

    assert paypal.capture_calls == paypal.payout_calls == paypal.batch_calls == []
    db.refresh(job)
    assert job.status == "CAPTURED"
    assert [p.status for p in payouts(db)] == ["FAILED"]
    assert events(db) == []
    assert "B9" in caplog.text


def test_mark_paid_sets_success_and_paid_out(db, released):
    job = released(status="CAPTURED")
    payout = Payout(job_id=job.id, batch_id="B9", amount=job.amount, status="PENDING")
    db.add(payout)
    db.commit()

    mark_paid(db, payout)
    db.commit()

    db.refresh(job)
    assert (job.status, payout.status) == ("PAID_OUT", "SUCCESS")
    row = db.scalars(select(AuditLog).order_by(AuditLog.id.desc())).first()
    assert (row.actor, row.event, row.to_status) == ("paypal", "PAYOUT_SUCCEEDED", "PAID_OUT")


def test_mark_paid_on_an_already_paid_job_raises_and_changes_nothing(db, released):
    """A replayed webhook: the job is already PAID_OUT. mark_paid must refuse, not write a second row."""
    job = released(status="PAID_OUT")
    payout = Payout(job_id=job.id, batch_id="B9", amount=job.amount, status="SUCCESS")
    db.add(payout)
    db.commit()

    with pytest.raises(InvalidTransition):
        mark_paid(db, payout)
    db.rollback()

    db.refresh(job)
    assert (job.status, payout.status) == ("PAID_OUT", "SUCCESS")
    assert events(db) == []


# --- other statuses ---

@pytest.mark.parametrize("status", ["BOOKED", "AUTHORIZED", "SUBMITTED", "VERIFIED",
                                    "PENDING_APPROVAL", "REJECTED", "PAID_OUT"])
def test_other_statuses_do_nothing(db, released, paypal, status):
    job = released(status=status)
    settle(db, job, paypal)
    assert paypal.capture_calls == paypal.payout_calls == paypal.batch_calls == []
    assert events(db) == []

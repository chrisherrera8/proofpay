"""Cleaner rules: who is still around, who is free on a date, and the permanent default cleaner."""
import datetime as dt
import logging
import threading
import time
import uuid

from sqlalchemy import and_, delete, exists, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import append_audit
from app.config import DEFAULT_CLEANER_NAME, get_settings
from app.models import Approval, ChecklistItem, Cleaner, Job, JobStatus, Payment, Payout, Photo, Verification

log = logging.getLogger(__name__)

CLEANER_TTL = dt.timedelta(hours=24)
# The roster endpoint purges as a side effect (Render's free tier has no cron), at most this often per process.
PURGE_EVERY_SECONDS = 60
# A job that never got authorized stops holding its cleaner for the day after this long.
UNPAID_HOLD = dt.timedelta(minutes=30)
# touch_cleaner() writes at most this often per cleaner.
TOUCH_EVERY = dt.timedelta(minutes=1)


def active_cleaner_filter():
    """SQL condition: the default cleaner, or a sign-up used within the last 24 hours. Expired rows are hidden at
    once, even before anything has deleted them."""
    return or_(Cleaner.is_seed, Cleaner.last_used_at > func.now() - CLEANER_TTL)


def touch_cleaner(db: Session, cleaner_id: uuid.UUID | None) -> None:
    """Record that the workflow just used this cleaner, which restarts its 24-hour clock. Does not commit: the
    caller's own commit carries it. Skipped when the stored value is under a minute old, so a polling page
    doesn't turn every read into a write. A missing or already expired cleaner is left alone (it must not be revived)."""
    if cleaner_id is None:
        return
    db.execute(
        update(Cleaner)
        .where(Cleaner.id == cleaner_id, active_cleaner_filter(), Cleaner.last_used_at < func.now() - TOUCH_EVERY)
        .values(last_used_at=func.now())
    )


def find_by_email(db: Session, email: str) -> Cleaner | None:
    """The active, non-default cleaner with this PayPal email (case-insensitive), if any. The newest wins if
    older duplicates exist."""
    return db.scalar(
        select(Cleaner)
        .where(~Cleaner.is_seed, func.lower(Cleaner.paypal_email) == email.strip().lower(), active_cleaner_filter())
        .order_by(Cleaner.created_at.desc())
        .limit(1)
    )


class CleanerExists(Exception):
    """The PayPal email already belongs to an active cleaner and the caller hasn't said it's theirs."""


def sign_up_or_resume(
    db: Session, name: str, paypal_email: str, *, confirmed: bool = False, known_id: uuid.UUID | None = None
) -> tuple[Cleaner, bool]:
    """(cleaner, created). A PayPal email already held by an active cleaner returns that cleaner (name unchanged)
    instead of adding a second one, and its 24-hour clock restarts. That only happens when the caller is the same
    browser (`known_id` is that cleaner's id) or has confirmed it's them; otherwise CleanerExists is raised and
    nothing changes, so a failed attempt can't keep someone else's account alive. There are no passwords, so the
    confirmation is an honest-user check, not security. Commits."""
    # Serialise sign-ups for the same email so two simultaneous requests can't both create one.
    db.execute(select(func.pg_advisory_xact_lock(func.hashtext(paypal_email.strip().lower()))))
    cleaner = find_by_email(db, paypal_email)
    created = cleaner is None
    if created:
        cleaner = Cleaner(name=name, paypal_email=paypal_email)
        db.add(cleaner)
    elif not (confirmed or known_id == cleaner.id):
        db.rollback()  # release the lock
        raise CleanerExists
    else:
        cleaner.last_used_at = func.now()  # an explicit sign-in always counts, whatever touch_cleaner's throttle says
    db.commit()
    return cleaner, created


def get_active_cleaner(db: Session, cleaner_id: uuid.UUID) -> Cleaner | None:
    return db.scalar(select(Cleaner).where(Cleaner.id == cleaner_id, active_cleaner_filter()))


def _still_holds_the_day():
    """SQL condition on Job: the job still keeps its cleaner busy for its day.

    Anything past BOOKED counts, and a BOOKED job counts for UNPAID_HOLD. PAID_OUT does not: the work is done and
    paid, so the cleaner can be booked again that day. REJECTED counts on purpose: it can be re-cleaned."""
    return and_(Job.status != JobStatus.PAID_OUT.value,
                or_(Job.status != JobStatus.BOOKED.value, Job.created_at > func.now() - UNPAID_HOLD))


def booked_on(date: dt.date):
    """SQL condition: this cleaner has a job that day that still holds the day (see _still_holds_the_day)."""
    holds = and_(Job.cleaner_id == Cleaner.id, Job.service_date == date, _still_holds_the_day())
    return exists().where(holds)


def day_is_claimed_by_another(db: Session, job: Job) -> bool:
    """True if a different job already holds this job's cleaner for its day (jobs with no cleaner never conflict)."""
    if job.cleaner_id is None or job.service_date is None:
        return False
    holds = and_(Job.cleaner_id == job.cleaner_id, Job.service_date == job.service_date, Job.id != job.id,
                 _still_holds_the_day())
    return bool(db.scalar(select(exists().where(holds))))


def list_cleaners(db: Session, date: dt.date) -> list[tuple[Cleaner, bool]]:
    """Active cleaners with whether each is free on `date`; the default cleaner first, then newest sign-ups."""
    taken = booked_on(date)
    rows = db.execute(
        select(Cleaner, ~taken).where(active_cleaner_filter()).order_by(Cleaner.is_seed.desc(), Cleaner.created_at.desc())
    )
    return [(c, bool(free)) for c, free in rows]


def resolve_payee(job: Job) -> tuple[str, str] | None:
    """(PayPal email, "cleaner" | "default") for the job's payout, or None if there is nowhere to send it.

    The booked cleaner is paid. If the job has none (an old job, or the cleaner's data was deleted after 24 hours),
    the default PAYPAL_CLEANER_EMAIL is paid instead.
    """
    if job.cleaner is not None:
        return job.cleaner.paypal_email, "cleaner"
    fallback = get_settings().paypal_cleaner_email.strip()
    return (fallback, "default") if fallback else None


def ensure_default_cleaner(db: Session) -> Cleaner | None:
    """Create or update the one permanent cleaner from PAYPAL_CLEANER_EMAIL and DEFAULT_CLEANER_NAME.

    With no PAYPAL_CLEANER_EMAIL there is no default cleaner (and none is created). Idempotent.
    """
    settings = get_settings()
    email = settings.paypal_cleaner_email.strip()
    if not email:
        return None
    name = settings.default_cleaner_name.strip() or DEFAULT_CLEANER_NAME
    cleaner = db.scalar(select(Cleaner).where(Cleaner.is_seed))
    if cleaner is None:
        try:
            with db.begin_nested():
                cleaner = Cleaner(name=name, paypal_email=email, is_seed=True)
                db.add(cleaner)
        except IntegrityError:  # another worker created it first (uq_cleaners_one_seed)
            cleaner = db.scalar(select(Cleaner).where(Cleaner.is_seed))
        db.commit()
    elif (cleaner.name, cleaner.paypal_email) != (name, email):
        cleaner.name, cleaner.paypal_email = name, email
        db.commit()
    return cleaner


def purge_expired(db: Session) -> dict[str, int]:
    """Delete expired cleaners and everything of theirs: their jobs, and those jobs' photos, checks, payments,
    payouts and checklists. The default cleaner never expires.

    Audit rows stay (they're append-only and hold ids and counts, never names or emails), so the hash chain is
    never touched. Idempotent; writes one count-only audit row only when it deleted something. Commits.
    """
    expired = select(Cleaner.id).where(~Cleaner.is_seed, ~active_cleaner_filter())
    job_ids = select(Job.id).where(Job.cleaner_id.in_(expired))
    photos = db.execute(delete(Photo).where(Photo.job_id.in_(job_ids))).rowcount
    for child in (Verification, Payout, Approval, Payment, ChecklistItem):
        db.execute(delete(child).where(child.job_id.in_(job_ids)))
    jobs = db.execute(delete(Job).where(Job.id.in_(job_ids))).rowcount
    # RETURNING, so a concurrent purge that got there first is not counted twice.
    cleaners = len(db.execute(delete(Cleaner).where(Cleaner.id.in_(expired)).returning(Cleaner.id)).all())
    if cleaners:
        append_audit(db, job_id=None, actor="system", event="CLEANERS_PURGED",
                     payload={"cleaners": cleaners, "jobs": jobs, "photos": photos})
    db.commit()
    return {"cleaners": cleaners, "jobs": jobs, "photos": photos}


_last_purge = 0.0
_purge_lock = threading.Lock()


def purge_if_due(db: Session) -> None:
    """purge_expired() at most once a minute per process. A failure is logged, never raised: the caller is a
    request that has nothing to do with the purge."""
    global _last_purge
    with _purge_lock:
        now = time.monotonic()
        if _last_purge and now - _last_purge < PURGE_EVERY_SECONDS:
            return
        _last_purge = now
    try:
        purge_expired(db)
    except Exception:
        db.rollback()
        log.exception("Purging expired cleaners failed")

"""Cleaner rules: who is still around, who is free on a date, and the permanent default cleaner."""
import datetime as dt
import uuid

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import DEFAULT_CLEANER_NAME, get_settings
from app.models import Cleaner, Job, JobStatus

CLEANER_TTL = dt.timedelta(hours=24)
# A job that never got authorized stops holding its cleaner for the day after this long.
UNPAID_HOLD = dt.timedelta(minutes=30)


def active_cleaner_filter():
    """SQL condition: the default cleaner, or a sign-up younger than 24 hours. Expired rows are hidden at once,
    even before anything has deleted them."""
    return or_(Cleaner.is_seed, Cleaner.created_at > func.now() - CLEANER_TTL)


def get_active_cleaner(db: Session, cleaner_id: uuid.UUID) -> Cleaner | None:
    return db.scalar(select(Cleaner).where(Cleaner.id == cleaner_id, active_cleaner_filter()))


def booked_on(date: dt.date):
    """SQL condition: this cleaner has a job that day that still counts (anything past BOOKED, or a recent BOOKED).

    REJECTED counts on purpose: a rejected job can be re-cleaned, so the cleaner still owns the day."""
    holds = and_(Job.cleaner_id == Cleaner.id, Job.service_date == date,
                 or_(Job.status != JobStatus.BOOKED.value, Job.created_at > func.now() - UNPAID_HOLD))
    return exists().where(holds)


def day_is_claimed_by_another(db: Session, job: Job) -> bool:
    """True if a different job already holds this job's cleaner for its day (jobs with no cleaner never conflict)."""
    if job.cleaner_id is None or job.service_date is None:
        return False
    holds = and_(Job.cleaner_id == job.cleaner_id, Job.service_date == job.service_date, Job.id != job.id,
                 or_(Job.status != JobStatus.BOOKED.value, Job.created_at > func.now() - UNPAID_HOLD))
    return bool(db.scalar(select(exists().where(holds))))


def list_cleaners(db: Session, date: dt.date) -> list[tuple[Cleaner, bool]]:
    """Active cleaners with whether each is free on `date`; the default cleaner first, then newest sign-ups."""
    taken = booked_on(date)
    rows = db.execute(
        select(Cleaner, ~taken).where(active_cleaner_filter()).order_by(Cleaner.is_seed.desc(), Cleaner.created_at.desc())
    )
    return [(c, bool(free)) for c, free in rows]


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

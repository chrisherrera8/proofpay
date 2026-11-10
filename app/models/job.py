import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, Numeric, String, and_, func, select
from sqlalchemy.orm import Mapped, aliased, mapped_column, relationship

from app.db import Base


class JobStatus(str, enum.Enum):
    BOOKED = "BOOKED"
    AUTHORIZED = "AUTHORIZED"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    RELEASED = "RELEASED"
    REJECTED = "REJECTED"
    CAPTURED = "CAPTURED"
    PAID_OUT = "PAID_OUT"


_STATUS_LIST = ", ".join(f"'{s.value}'" for s in JobStatus)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(f"status IN ({_STATUS_LIST})", name="ck_jobs_status"),
        CheckConstraint("amount > 0", name="ck_jobs_amount_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    status: Mapped[str] = mapped_column(String(32), default=JobStatus.BOOKED.value, index=True)
    customer_name: Mapped[str] = mapped_column(String(200))
    customer_email: Mapped[str] = mapped_column(String(320))
    address: Mapped[str] = mapped_column(String(500))
    service_type: Mapped[str] = mapped_column(String(64))
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    authorized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The cleaner is booked for this whole day. cleaner_id goes NULL when the cleaner is purged (the job stays).
    cleaner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cleaners.id", ondelete="SET NULL"), index=True)
    service_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    checklist_items: Mapped[list["ChecklistItem"]] = relationship(
        back_populates="job", order_by="ChecklistItem.position", cascade="all, delete-orphan"
    )
    payment: Mapped["Payment | None"] = relationship(back_populates="job", uselist=False)  # noqa: F821
    # Only the newest verification (a re-clean produces a new one), so listing jobs doesn't load every row.
    verification: Mapped["Verification | None"] = relationship(  # noqa: F821
        primaryjoin=lambda: _latest_verification_join(), viewonly=True, uselist=False
    )
    # The booked cleaner; None for old jobs and after the cleaner's data was deleted.
    cleaner: Mapped["Cleaner | None"] = relationship(viewonly=True)  # noqa: F821
    # One payout per job (unique job_id), eager-loaded so listing jobs needs no per-job query.
    payout: Mapped["Payout | None"] = relationship(viewonly=True, uselist=False)  # noqa: F821
    # The newest POLICY_DECIDED audit row, loaded the same way, so the API can show the decision.
    decision_event: Mapped["AuditLog | None"] = relationship(  # noqa: F821
        primaryjoin=lambda: _latest_decision_join(), viewonly=True, uselist=False
    )

    @property
    def decision(self) -> dict | None:
        """{outcome, reasons} from the latest POLICY_DECIDED audit row, or None before a decision."""
        event = self.decision_event
        if event is None:
            return None
        return {"outcome": event.payload.get("outcome"), "reasons": event.payload.get("reasons", [])}


def _latest_verification_join():
    from app.models.misc import Verification

    newer = aliased(Verification)
    latest_id = select(func.max(newer.id)).where(newer.job_id == Job.id).correlate(Job).scalar_subquery()
    return and_(Verification.job_id == Job.id, Verification.id == latest_id)


def _latest_decision_join():
    from app.models.audit import AuditLog

    newer = aliased(AuditLog)
    latest_id = (
        select(func.max(newer.id))
        .where(newer.job_id == Job.id, newer.event == "POLICY_DECIDED")
        .correlate(Job)
        .scalar_subquery()
    )
    return and_(AuditLog.job_id == Job.id, AuditLog.id == latest_id)


class ChecklistItem(Base):
    __tablename__ = "checklist_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id"), index=True)
    label: Mapped[str] = mapped_column(String(300))
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    position: Mapped[int] = mapped_column(Integer, default=0)

    job: Mapped[Job] = relationship(back_populates="checklist_items")

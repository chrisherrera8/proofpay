import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    checklist_items: Mapped[list["ChecklistItem"]] = relationship(
        back_populates="job", order_by="ChecklistItem.position", cascade="all, delete-orphan"
    )
    payment: Mapped["Payment | None"] = relationship(back_populates="job", uselist=False)  # noqa: F821


class ChecklistItem(Base):
    __tablename__ = "checklist_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id"), index=True)
    label: Mapped[str] = mapped_column(String(300))
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    position: Mapped[int] = mapped_column(Integer, default=0)

    job: Mapped[Job] = relationship(back_populates="checklist_items")

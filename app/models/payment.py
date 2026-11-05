import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id"), unique=True)
    order_id: Mapped[str] = mapped_column(String(64), unique=True)
    # Mutable: reauthorization returns a new ID. Always capture against the latest.
    authorization_id: Mapped[str | None] = mapped_column(String(64))
    capture_id: Mapped[str | None] = mapped_column(String(64))
    authorized_amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    authorized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), default="ORDER_CREATED")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    job: Mapped["Job"] = relationship(back_populates="payment")  # noqa: F821

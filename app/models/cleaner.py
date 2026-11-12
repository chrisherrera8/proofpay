import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Cleaner(Base):
    """A demo cleaner. Real sign-ups expire after 24 hours; the single default cleaner (is_seed) never does."""

    __tablename__ = "cleaners"
    __table_args__ = (
        # Exactly one permanent default cleaner, so ensure_default_cleaner() can't race into two.
        Index("uq_cleaners_one_seed", "is_seed", unique=True, postgresql_where=text("is_seed")),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    paypal_email: Mapped[str] = mapped_column(String(320))
    is_seed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

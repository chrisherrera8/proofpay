import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.misc import JsonB


class AuditLog(Base):
    """Append-only (DB trigger blocks UPDATE/DELETE) and hash-chained."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # No foreign key: the 24-hour purge deletes jobs, and these rows (ids and counts only) outlive them.
    job_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    actor: Mapped[str] = mapped_column(String(100))
    event: Mapped[str] = mapped_column(String(100))
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str | None] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JsonB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64), unique=True)

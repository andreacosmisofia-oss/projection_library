"""ORM models (Milestone M2).

Defines the ``projects`` table. Soft delete is implemented via
``deleted_at``: rows with a non-null timestamp are filtered out by the
API layer but kept in the database for audit purposes.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.infrastructure.db.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_uuid() -> str:
    return str(uuid.uuid4())


class Project(Base):
    """Pilot project: top-level entity for every flow downstream."""

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sector_pack: Mapped[str] = mapped_column(String(64), nullable=False)
    perimeter: Mapped[str | None] = mapped_column(String(64), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="EUR")
    country: Mapped[str | None] = mapped_column(String(64), nullable=True)
    accounting_standard: Mapped[str] = mapped_column(
        String(16), nullable=False, default="IFRS"
    )
    horizon_years: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    tier_level: Mapped[str | None] = mapped_column(String(32), nullable=True)
    etr_default: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )


__all__ = ["Project"]

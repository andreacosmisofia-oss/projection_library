"""ORM models (Milestones M2 + M3).

M2 defines the ``projects`` table. M3 adds ``balances`` and
``raw_voices`` for the Case 1 (gestionale) intake flow described in
``flows/01_data_intake.md``. Soft delete is implemented via
``deleted_at`` on ``projects`` and ``balances``: rows with a non-null
timestamp are filtered out by the API layer but kept in the database
for audit purposes.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

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


class Balance(Base):
    """Uploaded balance file metadata (M3, Case 1: gestionale only).

    A project has at most one *active* balance at a time. ``DELETE`` on
    the upload endpoint, or a re-upload, sets ``deleted_at`` and the row
    drops out of the ``raw_voices`` join used by downstream flows.
    """

    __tablename__ = "balances"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    raw_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    years_present: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    voice_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    raw_voices: Mapped[list["RawVoice"]] = relationship(
        "RawVoice",
        back_populates="balance",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class RawVoice(Base):
    """A single (label, year) datapoint extracted from the uploaded file.

    Long format on purpose: one row per (voice, year). Sparse years are
    represented by absent rows, not by null rows. ``lfl_flag`` defaults
    to True; the ``PATCH .../lfl`` endpoint flips every row of a given
    year for the balance.
    """

    __tablename__ = "raw_voices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    balance_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("balances.id", ondelete="CASCADE"),
        nullable=False,
    )
    voice_user_label: Mapped[str] = mapped_column(String(255), nullable=False)
    voice_user_section: Mapped[str | None] = mapped_column(String(32), nullable=True)
    year: Mapped[str] = mapped_column(String(8), nullable=False)
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    lfl_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    balance: Mapped[Balance] = relationship("Balance", back_populates="raw_voices")

    __table_args__ = (
        Index("ix_raw_voices_balance_year", "balance_id", "year"),
    )


__all__ = ["Balance", "Project", "RawVoice"]

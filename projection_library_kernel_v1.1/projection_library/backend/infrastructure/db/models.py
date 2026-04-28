"""ORM models (Milestones M2 + M3 + M5 + M6 + M7 + M8).

M2 defines the ``projects`` table. M3 adds ``balances`` and
``raw_voices`` for the Case 1 (gestionale) intake flow described in
``flows/01_data_intake.md``. M5 adds ``mappings`` (consumed by the
historical validator and the KPI calculator; M4 will populate it via
the auto-suggest flow when it lands), ``historical_kpis``,
``quality_scores`` and ``validation_reports`` (see
``flows/03_validation_historical.md`` and ``flows/10_quality_score.md``).
M6 adds ``method_configs`` (Expert mode subset of
``flows/04_method_selection.md``). M7 adds ``drivers`` (historical
management drivers from ``flows/05_driver_intake.md``). M8 adds
``assumptions`` and ``assumption_curve_configs`` (forward-looking
parameter compilation from ``flows/06_assumption_compilation.md``).
Soft delete is implemented via ``deleted_at`` on ``projects`` and
``balances``: rows with a non-null timestamp are filtered out by the
API layer but kept in the database for audit purposes.
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


class Mapping(Base):
    """User-confirmed mapping ``raw_voices.voice_user_label`` → ``voice_id``.

    M5 only reads from this table (the M4 auto-suggest API will own
    inserts/updates once it lands). Uniqueness on
    ``(project_id, voice_user_label, voice_user_section)`` mirrors the
    raw_voices grain so a label disambiguates by section when the same
    string appears in P&L and SP.
    """

    __tablename__ = "mappings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    voice_user_label: Mapped[str] = mapped_column(String(255), nullable=False)
    voice_user_section: Mapped[str | None] = mapped_column(String(32), nullable=True)
    voice_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    confirmed_by_user: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        Index(
            "ix_mappings_project_label_section",
            "project_id",
            "voice_user_label",
            "voice_user_section",
            unique=True,
        ),
    )


class HistoricalKPI(Base):
    """One row per ``(project, kpi, year)`` plus an ``AGG`` row per KPI.

    The ``AGG`` row carries the aggregated default used to seed forward
    assumptions (``default_for_projection``) and the per-KPI
    ``calibration_score``; per-year rows carry the raw computed value.
    Rows persist between reruns: the calculator deletes a project's
    KPIs and re-inserts in a single transaction (idempotent).
    """

    __tablename__ = "historical_kpis"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kpi_id: Mapped[str] = mapped_column(String(128), nullable=False)
    year: Mapped[str] = mapped_column(String(8), nullable=False)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    not_computable_reason: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    default_for_projection: Mapped[float | None] = mapped_column(Float, nullable=True)
    calibration_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    lfl_warning: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        Index(
            "ix_historical_kpis_project_kpi_year",
            "project_id",
            "kpi_id",
            "year",
            unique=True,
        ),
    )


class QualityScore(Base):
    """Latest computed quality score per project (one active row).

    The scorer upserts on ``(project_id)``: there is always at most one
    "current" score visible to the UI. ``components_detail`` keeps the
    explainable breakdown for the modal in ``flows/10_quality_score.md``.
    ``score_method_calibration`` is nullable because M5 ships before M6
    method selection — it stays NULL until method configs exist, and
    the total renormalises the remaining 3 weights.
    """

    __tablename__ = "quality_scores"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        unique=True,
    )
    score_total: Mapped[float] = mapped_column(Float, nullable=False)
    score_history: Mapped[float] = mapped_column(Float, nullable=False)
    score_completeness: Mapped[float] = mapped_column(Float, nullable=False)
    score_consistency: Mapped[float] = mapped_column(Float, nullable=False)
    score_method_calibration: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    classification: Mapped[str] = mapped_column(String(16), nullable=False)
    components_detail: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class ValidationReport(Base):
    """Persisted output of the historical validator.

    One row per ``(project_id, phase)``; ``phase='historical'`` for M5.
    The full issue list lives in JSON to keep the schema flat (the
    validator can produce dozens of issues per run; a relational layout
    is pure overhead at pilot scale).
    """

    __tablename__ = "validation_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    phase: Mapped[str] = mapped_column(String(32), nullable=False)
    summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    issues: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    can_proceed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        Index(
            "ix_validation_reports_project_phase",
            "project_id",
            "phase",
            unique=True,
        ),
    )


class MethodConfig(Base):
    """Per-voice projection method choice for a project (M6 Expert mode).

    Lazy persistence: a row is written only when the default is
    materialised (e.g. by a future ``init`` endpoint) or when the user
    overrides via ``PUT``. Voices without a row inherit
    ``voice.default_method`` from the registry at read time.

    ``is_default`` mirrors whether ``method_id`` matches the registry
    default at the moment of write — recomputed on each upsert so a
    user can revert to the default by re-PUTting it. ``source`` keeps
    the provenance: ``registry_default`` (materialised default),
    ``sector_pack`` (reserved for ``apply-pack``, not used yet) or
    ``user_override``.
    """

    __tablename__ = "method_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    voice_id: Mapped[str] = mapped_column(String(128), nullable=False)
    method_id: Mapped[str] = mapped_column(String(64), nullable=False)
    method_technical_code: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    configured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    __table_args__ = (
        Index(
            "ix_method_configs_project_voice",
            "project_id",
            "voice_id",
            unique=True,
        ),
    )


class Driver(Base):
    """Historical management driver (M7, ``flows/05_driver_intake.md``).

    One physical table covers the four polymorphic types declared in
    ``driver_registry.schema.json``: ``scalar_per_year``,
    ``static_parameters``, ``time_series`` and ``aging_bucket``. Only
    the columns relevant to a row's ``type`` are populated; the others
    stay NULL.

    ``year`` is part of the unique key for ``scalar_per_year`` rows
    (one value per historical year). For the other types ``year`` is
    the empty string ``""`` so a single row exists per
    ``(project_id, driver_id)``. The empty-string convention sidesteps
    SQLite's "NULLs are distinct" rule, which would otherwise make the
    unique index ineffective on those types.

    Skip is modelled as a marker row (``skipped=True``, no data
    columns set, ``year=""``). The route layer treats any row with
    ``skipped=True`` as authoritative for the ``(project, driver)``
    pair, regardless of other rows.
    """

    __tablename__ = "drivers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    driver_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    year: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    static_parameters: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    time_series: Mapped[list | None] = mapped_column(JSON, nullable=True)
    aging_buckets: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    skipped: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        Index(
            "ix_drivers_project_driver_year",
            "project_id",
            "driver_id",
            "year",
            unique=True,
        ),
    )


class Assumption(Base):
    """Forward-looking parameter value for a single year (M8).

    One row per ``(project_id, voice_id, method_id, assumption_name,
    year)`` where ``year`` is in ``Y1/Y2/Y3``. Per-year persistence
    matches the UI grain — a PATCH on one year doesn't touch the
    others — and lets ``source`` track provenance independently per
    cell so flat defaults stay distinguishable from a user override.

    ``validation_range_*`` are stamped at populate time (heuristic on
    the assumption name) so the warning logic doesn't need to consult
    the registry on every PATCH; ``user_modified_at`` flips to ``now``
    the first time the user touches a default.
    """

    __tablename__ = "assumptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    voice_id: Mapped[str] = mapped_column(String(128), nullable=False)
    method_id: Mapped[str] = mapped_column(String(64), nullable=False)
    assumption_name: Mapped[str] = mapped_column(String(128), nullable=False)
    year: Mapped[str] = mapped_column(String(8), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    default_kpi_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    calibration_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    validation_range_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    validation_range_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    parameterized: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    user_modified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        Index(
            "ix_assumptions_project_voice_method_name_year",
            "project_id",
            "voice_id",
            "method_id",
            "assumption_name",
            "year",
            unique=True,
        ),
    )


class AssumptionCurveConfig(Base):
    """Curve shape config for one ``(voice, method, assumption)`` (M8).

    Separated from :class:`Assumption` because the curve choice lives
    above the per-year cells — the audit M1.0 §12 explicitly puts it
    at ``(voice, assumption)`` grain. ``method_id`` is included in the
    unique key so a method swap (M6 PUT) doesn't accidentally inherit
    a curve config that no longer applies.
    """

    __tablename__ = "assumption_curve_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    voice_id: Mapped[str] = mapped_column(String(128), nullable=False)
    method_id: Mapped[str] = mapped_column(String(64), nullable=False)
    assumption_name: Mapped[str] = mapped_column(String(128), nullable=False)
    curve_type: Mapped[str] = mapped_column(String(32), nullable=False)
    configured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    __table_args__ = (
        Index(
            "ix_assumption_curves_project_voice_method_name",
            "project_id",
            "voice_id",
            "method_id",
            "assumption_name",
            unique=True,
        ),
    )


__all__ = [
    "Assumption",
    "AssumptionCurveConfig",
    "Balance",
    "Driver",
    "HistoricalKPI",
    "Mapping",
    "MethodConfig",
    "Project",
    "QualityScore",
    "RawVoice",
    "ValidationReport",
]

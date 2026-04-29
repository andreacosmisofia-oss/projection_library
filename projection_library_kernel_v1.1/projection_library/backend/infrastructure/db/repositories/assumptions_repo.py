"""Repository for the M8 assumptions tables.

Two tables, two contracts:

* ``assumptions`` — pre-populated by
  :func:`backend.domain.assumptions.populator.populate_defaults` and
  mutated single-row by the PATCH route. ``bulk_upsert_defaults``
  preserves rows whose ``source`` is ``user_input`` (the populator
  must never clobber a user choice).
* ``assumption_curve_configs`` — one row per
  ``(project, voice, method, assumption_name)``; absence of a row
  means "flat" (the default). ``upsert_curve_config`` flips the row.

Same convention as the other repos: routes own the transaction
boundary, repo functions only ``flush``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import and_, delete, or_, select, tuple_
from sqlalchemy.orm import Session

from backend.infrastructure.db.models import Assumption, AssumptionCurveConfig


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


def list_assumptions(db: Session, project_id: str) -> list[Assumption]:
    return list(
        db.execute(
            select(Assumption)
            .where(Assumption.project_id == project_id)
            .order_by(
                Assumption.voice_id,
                Assumption.method_id,
                Assumption.assumption_name,
                Assumption.year,
            )
        ).scalars()
    )


def list_curve_configs(
    db: Session, project_id: str
) -> list[AssumptionCurveConfig]:
    return list(
        db.execute(
            select(AssumptionCurveConfig)
            .where(AssumptionCurveConfig.project_id == project_id)
            .order_by(
                AssumptionCurveConfig.voice_id,
                AssumptionCurveConfig.method_id,
                AssumptionCurveConfig.assumption_name,
            )
        ).scalars()
    )


def get_assumption(
    db: Session,
    *,
    project_id: str,
    voice_id: str,
    method_id: str,
    assumption_name: str,
    year: str,
) -> Assumption | None:
    return db.execute(
        select(Assumption).where(
            Assumption.project_id == project_id,
            Assumption.voice_id == voice_id,
            Assumption.method_id == method_id,
            Assumption.assumption_name == assumption_name,
            Assumption.year == year,
        )
    ).scalars().first()


def list_assumption_triplet(
    db: Session,
    *,
    project_id: str,
    voice_id: str,
    method_id: str,
    assumption_name: str,
) -> list[Assumption]:
    """Return the (Y1, Y2, Y3) rows for one ``(voice, method, name)`` triplet."""
    return list(
        db.execute(
            select(Assumption)
            .where(
                Assumption.project_id == project_id,
                Assumption.voice_id == voice_id,
                Assumption.method_id == method_id,
                Assumption.assumption_name == assumption_name,
            )
            .order_by(Assumption.year)
        ).scalars()
    )


def get_curve_config(
    db: Session,
    *,
    project_id: str,
    voice_id: str,
    method_id: str,
    assumption_name: str,
) -> AssumptionCurveConfig | None:
    return db.execute(
        select(AssumptionCurveConfig).where(
            AssumptionCurveConfig.project_id == project_id,
            AssumptionCurveConfig.voice_id == voice_id,
            AssumptionCurveConfig.method_id == method_id,
            AssumptionCurveConfig.assumption_name == assumption_name,
        )
    ).scalars().first()


# ---------------------------------------------------------------------------
# Write — populator
# ---------------------------------------------------------------------------


def bulk_upsert_defaults(
    db: Session,
    project_id: str,
    entries: Iterable[dict],
) -> tuple[int, int]:
    """Upsert default rows; preserve ``user_input``.

    Each entry must carry: ``voice_id, method_id, assumption_name,
    year, value, source, default_kpi_id, validation_range``. Rows
    flagged ``source='user_input'`` already in DB are kept untouched
    (the populator must never clobber a user choice — flow §"populate-
    defaults: idempotent"). Returns ``(inserted, updated)``.
    """
    inserted = 0
    updated = 0
    now = datetime.now(timezone.utc)
    for entry in entries:
        existing = get_assumption(
            db,
            project_id=project_id,
            voice_id=entry["voice_id"],
            method_id=entry["method_id"],
            assumption_name=entry["assumption_name"],
            year=entry["year"],
        )
        if existing is None:
            row = Assumption(
                project_id=project_id,
                voice_id=entry["voice_id"],
                method_id=entry["method_id"],
                assumption_name=entry["assumption_name"],
                year=entry["year"],
                value=entry["value"],
                source=entry["source"],
                default_kpi_id=entry.get("default_kpi_id"),
                validation_range=entry.get("validation_range"),
                user_modified_at=None,
                created_at=now,
            )
            db.add(row)
            inserted += 1
            continue
        if existing.source == "user_input":
            # User edits are sticky across re-populate calls.
            continue
        existing.value = entry["value"]
        existing.source = entry["source"]
        existing.default_kpi_id = entry.get("default_kpi_id")
        existing.validation_range = entry.get("validation_range")
        updated += 1
    db.flush()
    return inserted, updated


def delete_orphan_pairs(
    db: Session,
    project_id: str,
    valid_pairs: Iterable[tuple[str, str]],
) -> int:
    """Drop assumption rows whose ``(voice, method)`` is no longer configured.

    Used when ``method_configs`` change between populate runs (TC-06-04
    in the flow): if the user switched ``volume_price`` →
    ``historical_avg_growth`` for a voice, the old rows for the
    superseded method must disappear so the read API doesn't return
    stale assumptions. ``valid_pairs`` is the current set of
    ``(voice_id, method_id)`` from ``method_configs``; anything else
    on the project is orphan.
    """
    valid = {(v, m) for v, m in valid_pairs}
    if not valid:
        # No method_configs at all: drop every assumption row.
        result = db.execute(
            delete(Assumption).where(Assumption.project_id == project_id)
        )
        db.execute(
            delete(AssumptionCurveConfig).where(
                AssumptionCurveConfig.project_id == project_id
            )
        )
        db.flush()
        return result.rowcount or 0

    # Build a NOT IN tuple filter compatible with SQLite (no row-value
    # NOT IN). Iterate Python-side: small N (≤ ~250 voices).
    rows = db.execute(
        select(Assumption).where(Assumption.project_id == project_id)
    ).scalars()
    deleted = 0
    for row in rows:
        if (row.voice_id, row.method_id) not in valid:
            db.delete(row)
            deleted += 1
    curves = db.execute(
        select(AssumptionCurveConfig).where(
            AssumptionCurveConfig.project_id == project_id
        )
    ).scalars()
    for curve in curves:
        if (curve.voice_id, curve.method_id) not in valid:
            db.delete(curve)
    db.flush()
    return deleted


# ---------------------------------------------------------------------------
# Write — single-row mutations
# ---------------------------------------------------------------------------


def update_value(
    db: Session, row: Assumption, *, value: float
) -> Assumption:
    """Apply a user edit; flip ``source`` to ``user_input``."""
    row.value = value
    row.source = "user_input"
    row.user_modified_at = datetime.now(timezone.utc)
    db.flush()
    return row


def upsert_value(
    db: Session,
    *,
    project_id: str,
    voice_id: str,
    method_id: str,
    assumption_name: str,
    year: str,
    value: float,
    default_kpi_id: str | None = None,
    validation_range: list[float] | None = None,
) -> Assumption:
    """Used by the curve endpoint: write a per-year value as user_input.

    If the row doesn't exist yet (rare: populate hasn't run) we create
    it on the fly so the curve op stays self-contained.
    """
    existing = get_assumption(
        db,
        project_id=project_id,
        voice_id=voice_id,
        method_id=method_id,
        assumption_name=assumption_name,
        year=year,
    )
    now = datetime.now(timezone.utc)
    if existing is None:
        row = Assumption(
            project_id=project_id,
            voice_id=voice_id,
            method_id=method_id,
            assumption_name=assumption_name,
            year=year,
            value=value,
            source="user_input",
            default_kpi_id=default_kpi_id,
            validation_range=validation_range,
            user_modified_at=now,
            created_at=now,
        )
        db.add(row)
        db.flush()
        return row
    existing.value = value
    existing.source = "user_input"
    existing.user_modified_at = now
    db.flush()
    return existing


def upsert_curve_config(
    db: Session,
    *,
    project_id: str,
    voice_id: str,
    method_id: str,
    assumption_name: str,
    curve_type: str,
) -> AssumptionCurveConfig:
    existing = get_curve_config(
        db,
        project_id=project_id,
        voice_id=voice_id,
        method_id=method_id,
        assumption_name=assumption_name,
    )
    if existing is None:
        row = AssumptionCurveConfig(
            project_id=project_id,
            voice_id=voice_id,
            method_id=method_id,
            assumption_name=assumption_name,
            curve_type=curve_type,
        )
        db.add(row)
        db.flush()
        return row
    existing.curve_type = curve_type
    db.flush()
    return existing


__all__ = [
    "bulk_upsert_defaults",
    "delete_orphan_pairs",
    "get_assumption",
    "get_curve_config",
    "list_assumption_triplet",
    "list_assumptions",
    "list_curve_configs",
    "update_value",
    "upsert_curve_config",
    "upsert_value",
]

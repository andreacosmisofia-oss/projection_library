"""Read-side composition: DB rows → API payload (``flows/06`` §"GET").

Groups three ``Assumption`` rows (Y1/Y2/Y3) into a single API row,
attaches the ``calibration_score`` from the source KPI's AGG row,
classifies validation status against the persisted range, and joins
the curve config (default ``flat`` when absent).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.assumptions.validator import (
    ValidationStatus,
    classify_triplet,
)
from backend.infrastructure.db.models import HistoricalKPI
from backend.infrastructure.db.repositories.assumptions_repo import (
    list_assumptions,
    list_curve_configs,
)


@dataclass
class AssumptionRowDTO:
    """One UI-facing assumption row (three years collapsed)."""

    voice_id: str
    method_id: str
    assumption_name: str
    values: dict[str, float]
    source: str
    default_kpi_id: str | None
    calibration_score: float | None
    validation_status: ValidationStatus
    validation_range: list[float] | None
    curve_type: str
    user_modified_at: datetime | None


def _index_kpi_calibration(
    db: Session, project_id: str
) -> dict[str, float | None]:
    """Map ``kpi_id`` → calibration_score from the AGG row."""
    rows = db.execute(
        select(HistoricalKPI).where(
            HistoricalKPI.project_id == project_id,
            HistoricalKPI.year == "AGG",
        )
    ).scalars()
    return {r.kpi_id: r.calibration_score for r in rows}


def _aggregate_source(sources: list[str]) -> str:
    """Collapse three per-year sources into one row-level source.

    Preference order matches the UI semantics: any user edit on the
    triplet flips the row to ``user_input``; otherwise ``default_kpi``
    wins over ``fallback`` (a single fallback year still degrades).
    """
    if "user_input" in sources:
        return "user_input"
    if "fallback" in sources and "default_kpi" not in sources:
        return "fallback"
    if "fallback" in sources:
        # Mixed: at least one year is fallback, others are KPI-based.
        # Surface the weaker source so the UI doesn't claim "calibrated".
        return "fallback"
    return "default_kpi"


def compose_assumption_list(
    db: Session, project_id: str
) -> list[AssumptionRowDTO]:
    """Return the API rows for ``GET /assumptions``."""
    raw = list_assumptions(db, project_id)
    curves = {
        (c.voice_id, c.method_id, c.assumption_name): c.curve_type
        for c in list_curve_configs(db, project_id)
    }
    kpi_calibration = _index_kpi_calibration(db, project_id)

    grouped: dict[tuple[str, str, str], list[Any]] = {}
    for row in raw:
        key = (row.voice_id, row.method_id, row.assumption_name)
        grouped.setdefault(key, []).append(row)

    out: list[AssumptionRowDTO] = []
    for (voice_id, method_id, name), rows in grouped.items():
        rows_by_year = {r.year: r for r in rows}
        values = {y: rows_by_year[y].value for y in rows_by_year}
        # Take the most recent user_modified_at across the triplet.
        last_edits = [
            r.user_modified_at for r in rows if r.user_modified_at is not None
        ]
        user_modified_at = max(last_edits) if last_edits else None

        # ``default_kpi_id`` and ``validation_range`` are repeated
        # per-year for the same triplet; pick any non-null value.
        default_kpi_id = next(
            (r.default_kpi_id for r in rows if r.default_kpi_id), None
        )
        validation_range = next(
            (r.validation_range for r in rows if r.validation_range), None
        )

        calibration = (
            kpi_calibration.get(default_kpi_id) if default_kpi_id else None
        )

        status = classify_triplet(
            [r.value for r in rows], validation_range
        )
        source = _aggregate_source([r.source for r in rows])
        curve_type = curves.get((voice_id, method_id, name), "flat")

        out.append(
            AssumptionRowDTO(
                voice_id=voice_id,
                method_id=method_id,
                assumption_name=name,
                values=values,
                source=source,
                default_kpi_id=default_kpi_id,
                calibration_score=calibration,
                validation_status=status,
                validation_range=validation_range,
                curve_type=curve_type,
                user_modified_at=user_modified_at,
            )
        )

    out.sort(
        key=lambda d: (d.voice_id, d.method_id, d.assumption_name)
    )
    return out


__all__ = ["AssumptionRowDTO", "compose_assumption_list"]

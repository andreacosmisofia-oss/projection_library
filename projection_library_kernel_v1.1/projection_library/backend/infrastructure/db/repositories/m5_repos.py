"""Repositories for the M5 tables.

Each function takes a live :class:`~sqlalchemy.orm.Session` and either
mutates it (without committing) or runs a read query. The route layer
owns the commit boundary, mirroring the pattern in
``balance_repo.py``.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.domain.intake.validator_historical import HistoricalValidationReport
from backend.domain.kpi.calculator import HistoricalKPISnapshot
from backend.domain.quality.scorer import QualityScoreResult
from backend.infrastructure.db.models import (
    HistoricalKPI,
    Mapping,
    QualityScore,
    ValidationReport,
)


# ---------------------------------------------------------------------------
# Mappings (read-only here; M4 will own writes)
# ---------------------------------------------------------------------------


def list_confirmed_mappings(db: Session, project_id: str) -> list[Mapping]:
    return list(
        db.execute(
            select(Mapping).where(
                Mapping.project_id == project_id,
                Mapping.confirmed_by_user.is_(True),
            )
        ).scalars()
    )


def upsert_mapping(
    db: Session,
    project_id: str,
    voice_user_label: str,
    voice_user_section: str | None,
    voice_id: str,
    confidence: float | None = None,
    confirmed_by_user: bool = True,
) -> Mapping:
    """Insert or update one mapping row.

    Used by M5 tests / fixtures and by future M4 endpoints. The unique
    index ``(project_id, voice_user_label, voice_user_section)`` keeps
    relabelling deterministic.
    """
    existing = db.execute(
        select(Mapping).where(
            Mapping.project_id == project_id,
            Mapping.voice_user_label == voice_user_label,
            Mapping.voice_user_section.is_(voice_user_section)
            if voice_user_section is None
            else Mapping.voice_user_section == voice_user_section,
        )
    ).scalars().first()
    if existing is None:
        row = Mapping(
            project_id=project_id,
            voice_user_label=voice_user_label,
            voice_user_section=voice_user_section,
            voice_id=voice_id,
            confidence=confidence,
            confirmed_by_user=confirmed_by_user,
        )
        db.add(row)
        return row
    existing.voice_id = voice_id
    existing.confidence = confidence
    existing.confirmed_by_user = confirmed_by_user
    return existing


# ---------------------------------------------------------------------------
# Historical KPIs
# ---------------------------------------------------------------------------


def replace_historical_kpis(
    db: Session, project_id: str, snapshot: HistoricalKPISnapshot
) -> int:
    """Delete the project's KPIs and re-insert from the snapshot.

    Returns the number of rows inserted. Idempotent: re-running with
    the same input produces the same DB state.
    """
    db.execute(delete(HistoricalKPI).where(HistoricalKPI.project_id == project_id))
    db.flush()

    rows: list[HistoricalKPI] = []
    now = datetime.now(timezone.utc)
    for kpi in snapshot.computed:
        for year, value in kpi.values_by_year.items():
            rows.append(
                HistoricalKPI(
                    project_id=project_id,
                    kpi_id=kpi.kpi_id,
                    year=year,
                    value=value,
                    not_computable_reason=None,
                    default_for_projection=None,
                    calibration_score=None,
                    lfl_warning=False,
                    computed_at=now,
                )
            )
        rows.append(
            HistoricalKPI(
                project_id=project_id,
                kpi_id=kpi.kpi_id,
                year="AGG",
                value=None,
                not_computable_reason=kpi.not_computable_reason,
                default_for_projection=kpi.default_for_projection,
                calibration_score=kpi.calibration_score,
                lfl_warning=kpi.lfl_warning,
                computed_at=now,
            )
        )
    if rows:
        db.add_all(rows)
    return len(rows)


def list_historical_kpis(db: Session, project_id: str) -> list[HistoricalKPI]:
    return list(
        db.execute(
            select(HistoricalKPI)
            .where(HistoricalKPI.project_id == project_id)
            .order_by(HistoricalKPI.kpi_id, HistoricalKPI.year)
        ).scalars()
    )


# ---------------------------------------------------------------------------
# Quality score
# ---------------------------------------------------------------------------


def upsert_quality_score(
    db: Session, project_id: str, result: QualityScoreResult
) -> QualityScore:
    existing = db.execute(
        select(QualityScore).where(QualityScore.project_id == project_id)
    ).scalars().first()
    now = datetime.now(timezone.utc)
    if existing is None:
        row = QualityScore(
            project_id=project_id,
            score_total=result.score_total,
            score_history=result.score_history,
            score_completeness=result.score_completeness,
            score_consistency=result.score_consistency,
            score_method_calibration=result.score_method_calibration,
            classification=result.classification,
            components_detail=result.components_detail,
            computed_at=now,
        )
        db.add(row)
        return row
    existing.score_total = result.score_total
    existing.score_history = result.score_history
    existing.score_completeness = result.score_completeness
    existing.score_consistency = result.score_consistency
    existing.score_method_calibration = result.score_method_calibration
    existing.classification = result.classification
    existing.components_detail = result.components_detail
    existing.computed_at = now
    return existing


def get_quality_score(db: Session, project_id: str) -> QualityScore | None:
    return db.execute(
        select(QualityScore).where(QualityScore.project_id == project_id)
    ).scalars().first()


# ---------------------------------------------------------------------------
# Validation report
# ---------------------------------------------------------------------------


def _serialize_issue(issue) -> dict:
    return {
        "rule_id": issue.rule_id,
        "severity": issue.severity,
        "voice_id": issue.voice_id,
        "year": issue.year,
        "message": issue.message,
        "context": issue.context,
    }


def upsert_validation_report(
    db: Session,
    project_id: str,
    phase: str,
    report: HistoricalValidationReport,
) -> ValidationReport:
    existing = db.execute(
        select(ValidationReport).where(
            ValidationReport.project_id == project_id,
            ValidationReport.phase == phase,
        )
    ).scalars().first()
    summary = report.summary()
    issues = [_serialize_issue(i) for i in report.issues]
    now = datetime.now(timezone.utc)
    if existing is None:
        row = ValidationReport(
            project_id=project_id,
            phase=phase,
            summary=summary,
            issues=issues,
            can_proceed=report.can_proceed,
            computed_at=now,
        )
        db.add(row)
        return row
    existing.summary = summary
    existing.issues = issues
    existing.can_proceed = report.can_proceed
    existing.computed_at = now
    return existing


def get_validation_report(
    db: Session, project_id: str, phase: str
) -> ValidationReport | None:
    return db.execute(
        select(ValidationReport).where(
            ValidationReport.project_id == project_id,
            ValidationReport.phase == phase,
        )
    ).scalars().first()


__all__ = [
    "get_quality_score",
    "get_validation_report",
    "list_confirmed_mappings",
    "list_historical_kpis",
    "replace_historical_kpis",
    "upsert_mapping",
    "upsert_quality_score",
    "upsert_validation_report",
]

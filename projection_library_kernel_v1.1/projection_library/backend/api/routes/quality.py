"""Quality score routes — Milestone M5 (``flows/10_quality_score.md``).

The score is **derived**: POST recomputes from the latest validation
report + mapped values. If validation has not been run yet, POST runs
it implicitly so the score never drifts away from the underlying
data.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.api.schemas.quality import QualityScoreResponse
from backend.domain.intake import (
    HistoricalValidationIssue,
    HistoricalValidationReport,
    resolve_mapped_values,
    run_historical_validation,
)
from backend.domain.quality import compute_quality_score
from backend.domain.quality.scorer import WEIGHTS
from backend.infrastructure.db.database import get_db
from backend.infrastructure.db.models import Project
from backend.infrastructure.db.repositories.m5_repos import (
    get_quality_score,
    get_validation_report,
    upsert_quality_score,
    upsert_validation_report,
)
from backend.infrastructure.registry import get_cache

router = APIRouter(prefix="/api/projects/{project_id}", tags=["quality"])


def _get_project_or_404(db: Session, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if project is None or project.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"project '{project_id}' not found",
        )
    return project


def _to_response(row, project_id: str) -> QualityScoreResponse:
    return QualityScoreResponse(
        project_id=project_id,
        score_total=row.score_total,
        score_history=row.score_history,
        score_completeness=row.score_completeness,
        score_consistency=row.score_consistency,
        score_method_calibration=row.score_method_calibration,
        classification=row.classification,
        weights=dict(WEIGHTS),
        components_detail=row.components_detail or {},
        computed_at=row.computed_at,
    )


def _hydrate_validation_report(stored) -> HistoricalValidationReport:
    issues = [
        HistoricalValidationIssue(
            rule_id=i["rule_id"],
            severity=i["severity"],
            voice_id=i.get("voice_id"),
            year=i.get("year"),
            message=i["message"],
            context=i.get("context") or {},
        )
        for i in stored.issues or []
    ]
    return HistoricalValidationReport(issues=issues)


@router.post(
    "/quality-score",
    response_model=QualityScoreResponse,
    status_code=status.HTTP_200_OK,
)
def compute(
    project_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> QualityScoreResponse:
    project = _get_project_or_404(db, project_id)
    try:
        values = resolve_mapped_values(db, project_id)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc

    registries = get_cache().get()

    stored_report = get_validation_report(db, project_id, "historical")
    if stored_report is None:
        report = run_historical_validation(values, registries, project)
        upsert_validation_report(db, project_id, "historical", report)
    else:
        report = _hydrate_validation_report(stored_report)

    result = compute_quality_score(
        values, report, registries, project.tier_level
    )
    row = upsert_quality_score(db, project_id, result)
    db.commit()
    db.refresh(row)
    return _to_response(row, project_id)


@router.get("/quality-score", response_model=QualityScoreResponse)
def get_score(
    project_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> QualityScoreResponse:
    _get_project_or_404(db, project_id)
    row = get_quality_score(db, project_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"no quality score for project '{project_id}' — "
                f"POST /quality-score first"
            ),
        )
    return _to_response(row, project_id)


__all__ = ["router"]

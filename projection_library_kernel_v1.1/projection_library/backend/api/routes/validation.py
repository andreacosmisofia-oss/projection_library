"""Historical validation routes — Milestone M5.

Wires :mod:`backend.domain.intake.validator_historical` into HTTP. The
endpoint runs the validator over the project's mapped values, persists
the report, and returns the same payload directly so the UI can show
the issues without a follow-up GET.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.api.schemas.validation import (
    ValidationIssueDTO,
    ValidationReportResponse,
    ValidationSummary,
)
from backend.domain.intake import (
    resolve_mapped_values,
    run_historical_validation,
)
from backend.infrastructure.db.database import get_db
from backend.infrastructure.db.models import Project
from backend.infrastructure.db.repositories.m5_repos import (
    get_validation_report,
    upsert_validation_report,
)
from backend.infrastructure.registry import get_cache

router = APIRouter(prefix="/api/projects/{project_id}", tags=["validation"])


def _get_project_or_404(db: Session, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if project is None or project.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"project '{project_id}' not found",
        )
    return project


def _to_response(row, project_id: str) -> ValidationReportResponse:
    summary = row.summary or {}
    return ValidationReportResponse(
        project_id=project_id,
        phase=row.phase,
        summary=ValidationSummary(**summary),
        issues=[ValidationIssueDTO(**issue) for issue in row.issues or []],
        can_proceed=row.can_proceed,
        computed_at=row.computed_at,
    )


@router.post(
    "/validate-historical",
    response_model=ValidationReportResponse,
    status_code=status.HTTP_200_OK,
)
def run_validation(
    project_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> ValidationReportResponse:
    project = _get_project_or_404(db, project_id)
    try:
        values = resolve_mapped_values(db, project_id)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc

    registries = get_cache().get()
    report = run_historical_validation(values, registries, project)
    row = upsert_validation_report(db, project_id, "historical", report)
    db.commit()
    db.refresh(row)
    return _to_response(row, project_id)


@router.get(
    "/validation-report/historical",
    response_model=ValidationReportResponse,
)
def get_report(
    project_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> ValidationReportResponse:
    _get_project_or_404(db, project_id)
    row = get_validation_report(db, project_id, "historical")
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"no historical validation report for project "
                f"'{project_id}' — POST /validate-historical first"
            ),
        )
    return _to_response(row, project_id)


__all__ = ["router"]

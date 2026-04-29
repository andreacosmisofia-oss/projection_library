"""Snapshot routes — Milestone M10 (``flows/08_output_presentation.md``).

Three endpoints:

* ``POST /api/projects/{id}/run`` — invoke ``run_engine`` and persist
  the result as a new ``snapshots`` row plus the normalised
  ``snapshot_values`` derived from the post-run :class:`ModelState`.
* ``GET /api/projects/{id}/snapshot/latest`` — return the most recent
  snapshot, with values eager-loaded.
* ``GET /api/projects/{id}/snapshots`` — return the latest N snapshot
  headers (default 5, max 20) ordered ``created_at DESC``.

E0 hard blocks (raised by ``run_engine`` as :class:`ProjectNotReady`)
are surfaced as ``422 Unprocessable Entity`` with the block messages
in the response detail. Other exceptions bubble up as ``500``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.api.schemas.snapshots import (
    ApproximationLogResponse,
    LatestValidationReport,
    SnapshotDetail,
    SnapshotList,
    SnapshotSummary,
)
from backend.domain.engine.executor import (
    ProjectNotReady,
    run_engine,
)
from backend.domain.engine.snapshot_builder import (
    build_snapshot_values,
    build_validation_summary,
    serialise_validation_issues,
)
from backend.infrastructure.db.database import get_db
from backend.infrastructure.db.models import Project
from backend.infrastructure.db.repositories.snapshots_repo import (
    create_snapshot,
    get_latest_snapshot,
    list_snapshots,
)
from backend.infrastructure.registry import Registries, get_cache

router = APIRouter(prefix="/api/projects/{project_id}", tags=["snapshots"])


def _get_project_or_404(db: Session, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if project is None or project.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"project '{project_id}' not found",
        )
    return project


def _registries() -> Registries:
    return get_cache().get()


@router.post(
    "/run",
    response_model=SnapshotSummary,
    status_code=status.HTTP_201_CREATED,
)
def run_project(
    project_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> SnapshotSummary:
    _get_project_or_404(db, project_id)

    try:
        result = run_engine(project_id, db, _registries())
    except ProjectNotReady as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    state = result.final_state
    if state is None:
        # run_engine populates final_state on success; treat absence as
        # a server-side bug rather than swallowing it silently.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="engine did not expose final_state",
        )

    snapshot = create_snapshot(
        db,
        project_id=project_id,
        run_timestamp=result.run_timestamp,
        status=result.status,
        duration_ms=result.duration_ms,
        validation_summary=build_validation_summary(state),
        validation_issues=serialise_validation_issues(state),
        approximation_log=list(result.approximation_log),
        pl_data=result.pl_data,
        sp_data=result.sp_data,
        cf_data=result.cf_data,
        projected_kpis=result.projected_kpis,
        error_message=None,
        values=build_snapshot_values(state),
    )
    db.commit()
    db.refresh(snapshot)
    return SnapshotSummary.model_validate(snapshot)


@router.get("/snapshot/latest", response_model=SnapshotDetail)
def get_latest(
    project_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> SnapshotDetail:
    _get_project_or_404(db, project_id)
    snapshot = get_latest_snapshot(db, project_id)
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no snapshot found for project '{project_id}'",
        )
    return SnapshotDetail.model_validate(snapshot)


@router.get(
    "/validation-report/latest",
    response_model=LatestValidationReport,
)
def get_latest_validation_report(
    project_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> LatestValidationReport:
    """Return the engine-time validation issues from the latest snapshot.

    Distinct from M5's ``GET /validation-report/historical``: this view
    shows the issues accumulated during the most recent engine run
    (``state.validation_issues``). M12 dashboard panel reads from here.
    """
    _get_project_or_404(db, project_id)
    snapshot = get_latest_snapshot(db, project_id)
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"no snapshot found for project '{project_id}' — "
                f"POST /run first"
            ),
        )
    return LatestValidationReport(
        project_id=project_id,
        snapshot_id=snapshot.id,
        run_timestamp=snapshot.run_timestamp,
        status=snapshot.status,
        summary=snapshot.validation_summary or {},
        issues=list(snapshot.validation_issues or []),
    )


@router.get(
    "/approximation-log",
    response_model=ApproximationLogResponse,
)
def get_approximation_log(
    project_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> ApproximationLogResponse:
    """Return the approximation log captured during the latest engine run."""
    _get_project_or_404(db, project_id)
    snapshot = get_latest_snapshot(db, project_id)
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"no snapshot found for project '{project_id}' — "
                f"POST /run first"
            ),
        )
    return ApproximationLogResponse(
        project_id=project_id,
        snapshot_id=snapshot.id,
        run_timestamp=snapshot.run_timestamp,
        approximation_log=list(snapshot.approximation_log or []),
    )


@router.get("/snapshots", response_model=SnapshotList)
def list_recent(
    project_id: str,
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
) -> SnapshotList:
    _get_project_or_404(db, project_id)
    items = list_snapshots(db, project_id, limit=limit)
    return SnapshotList(
        project_id=project_id,
        count=len(items),
        items=[SnapshotSummary.model_validate(s) for s in items],
    )


__all__ = ["router"]

"""Override CRUD routes — Milestone M11 (``flows/09_iteration.md``).

Four endpoints under ``/api/projects/{id}/overrides``:

* ``POST`` — validate the request against
  :mod:`backend.domain.override.policy`, persist the row with the
  resolved ``override_policy_class``, and trigger an automatic
  re-run of the engine (M11 acceptance: snapshot reflects the
  override propagation).
* ``GET`` — list overrides ordered ``created_at DESC``; ``?active_only``
  filters out deactivated rows.
* ``PATCH`` — toggle ``is_active`` (only mutable field in pilot
  v1.1), stamp ``deactivated_at`` on transitions, and re-run.
* ``DELETE`` — hard delete and re-run.

The re-run uses :func:`backend.domain.override.resolver.run_with_overrides`
so the snapshot is created in the same DB transaction as the
override mutation, keeping the override list and the latest
snapshot pairwise consistent.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from backend.api.schemas.overrides import (
    OverrideCreate,
    OverrideList,
    OverrideResponse,
    OverrideUpdate,
)
from backend.api.schemas.snapshots import SnapshotSummary
from backend.domain.engine.executor import ProjectNotReady
from backend.domain.engine.snapshot_builder import (
    build_snapshot_values,
    build_validation_summary,
    serialise_validation_issues,
)
from backend.domain.override.policy import (
    OverrideValidationError,
    validate_override_request,
)
from backend.domain.override.resolver import run_with_overrides
from backend.infrastructure.db.database import get_db
from backend.infrastructure.db.models import Project
from backend.infrastructure.db.repositories.overrides_repo import (
    create_override,
    delete_override,
    get_override,
    list_overrides,
    set_override_active,
)
from backend.infrastructure.db.repositories.snapshots_repo import create_snapshot
from backend.infrastructure.registry import Registries, get_cache

router = APIRouter(
    prefix="/api/projects/{project_id}/overrides",
    tags=["overrides"],
)


def _registries() -> Registries:
    return get_cache().get()


def _get_project_or_404(db: Session, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if project is None or project.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"project '{project_id}' not found",
        )
    return project


def _trigger_rerun(
    db: Session, project_id: str, registries: Registries
) -> None:
    """Run the engine with overrides applied and persist a new snapshot.

    Mutations to the ``overrides`` table flushed by the route are
    visible to the engine via :func:`build_initial_state` (it queries
    the DB inside the same session), so the rerun reflects the new
    override list. Failures from ``ProjectNotReady`` are surfaced as
    422; we deliberately don't roll back the override mutation —
    the user can fix the project state and re-toggle the override.
    """
    try:
        result = run_with_overrides(project_id, db, registries)
    except ProjectNotReady as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"engine pre-conditions not met: {exc}",
        ) from exc

    state = result.final_state
    if state is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="engine did not expose final_state",
        )

    create_snapshot(
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


@router.post(
    "",
    response_model=OverrideResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_override(
    project_id: str,
    payload: OverrideCreate,
    db: Annotated[Session, Depends(get_db)],
) -> OverrideResponse:
    _get_project_or_404(db, project_id)
    registries = _registries()

    try:
        match = validate_override_request(
            voice_id=payload.voice_id,
            year=payload.year,
            delta_amount=payload.delta_amount,
            nature=payload.nature,
            registries=registries,
        )
    except OverrideValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    row = create_override(
        db,
        project_id=project_id,
        voice_id=payload.voice_id,
        year=payload.year,
        delta_amount=float(payload.delta_amount),
        nature=payload.nature,
        override_policy_class=match.policy_class,
        user_note=payload.user_note,
    )

    _trigger_rerun(db, project_id, registries)
    db.commit()
    db.refresh(row)
    return OverrideResponse.model_validate(row)


@router.get("", response_model=OverrideList)
def get_overrides(
    project_id: str,
    db: Annotated[Session, Depends(get_db)],
    active_only: Annotated[bool, Query()] = False,
) -> OverrideList:
    _get_project_or_404(db, project_id)
    rows = list_overrides(db, project_id, active_only=active_only)
    return OverrideList(
        project_id=project_id,
        count=len(rows),
        items=[OverrideResponse.model_validate(r) for r in rows],
    )


@router.patch(
    "/{override_id}",
    response_model=OverrideResponse,
)
def patch_override(
    project_id: str,
    override_id: str,
    payload: OverrideUpdate,
    db: Annotated[Session, Depends(get_db)],
) -> OverrideResponse:
    _get_project_or_404(db, project_id)
    row = get_override(db, project_id, override_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"override '{override_id}' not found",
        )

    if row.is_active == payload.is_active:
        # No-op toggle: don't bother re-running the engine.
        return OverrideResponse.model_validate(row)

    set_override_active(db, row, is_active=payload.is_active)
    db.flush()

    _trigger_rerun(db, project_id, _registries())
    db.commit()
    db.refresh(row)
    return OverrideResponse.model_validate(row)


@router.delete(
    "/{override_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_override_route(
    project_id: str,
    override_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    _get_project_or_404(db, project_id)
    row = get_override(db, project_id, override_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"override '{override_id}' not found",
        )

    was_active = row.is_active
    delete_override(db, row)
    db.flush()

    if was_active:
        # Only re-run when the deletion actually changes the active set.
        _trigger_rerun(db, project_id, _registries())

    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router", "SnapshotSummary"]

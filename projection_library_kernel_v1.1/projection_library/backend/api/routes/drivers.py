"""Driver intake routes — Milestone M7.

Implements the three pilot endpoints described in
``flows/05_driver_intake.md`` API section:

* ``GET    /api/projects/{id}/drivers/required``       — required list
* ``POST   /api/projects/{id}/drivers/upload``         — upsert a driver
* ``PATCH  /api/projects/{id}/drivers/{driver_id}/skip`` — skip a driver

Excel templates and multipart upload are deferred to M7.b. Required
drivers are derived dynamically from ``method_configs`` × method
registry (no pre-population step), which keeps the surface in line
with the lazy persistence chosen for ``method_configs`` in M6.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.api.schemas.drivers import (
    DriverRequirementEntry,
    DriverRequirementsList,
    DriverRequirementsSummary,
    DriverUpload,
)
from backend.domain.methods import (
    DRIVER_TYPE_SCALAR,
    DRIVER_TYPE_STATIC_PARAMETERS,
    RequiredDriver,
    compute_required_drivers,
)
from backend.infrastructure.db.database import get_db
from backend.infrastructure.db.models import Driver, Project
from backend.infrastructure.db.repositories.drivers_repo import (
    DRIVER_STATUS_ACTIVE,
    DRIVER_STATUS_SKIPPED,
    list_drivers,
    mark_driver_skipped,
    upsert_driver,
)
from backend.infrastructure.db.repositories.method_configs_repo import (
    list_method_configs,
)
from backend.infrastructure.registry import Registries, get_cache

router = APIRouter(prefix="/api/projects/{project_id}/drivers", tags=["drivers"])


_STATUS_MISSING = "missing"
_STATUS_PARTIAL = "partial"
_STATUS_COMPLETE = "complete"
_STATUS_SKIPPED = "skipped"


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


def _required_index(
    db: Session, project_id: str, registries: Registries
) -> dict[str, RequiredDriver]:
    configs = list_method_configs(db, project_id)
    return {r.driver_id: r for r in compute_required_drivers(configs, registries)}


def _resolve_status(req: RequiredDriver, row: Driver | None) -> str:
    if row is not None and row.status == DRIVER_STATUS_SKIPPED:
        return _STATUS_SKIPPED
    if row is None:
        return _STATUS_MISSING
    if req.type == DRIVER_TYPE_SCALAR:
        values = row.values or {}
        present = [
            y for y in req.years_required
            if values.get(y) is not None
        ]
        if not present:
            return _STATUS_MISSING
        if len(present) < len(req.years_required):
            return _STATUS_PARTIAL
        return _STATUS_COMPLETE
    if req.type == DRIVER_TYPE_STATIC_PARAMETERS:
        params = row.static_parameters or {}
        # Pilot v1 does not enumerate per-driver mandatory fields. Any
        # non-empty payload counts as complete; an empty/null payload
        # keeps the row in missing.
        if not params:
            return _STATUS_MISSING
        return _STATUS_COMPLETE
    return _STATUS_MISSING


def _entry_from(req: RequiredDriver, row: Driver | None) -> DriverRequirementEntry:
    return DriverRequirementEntry(
        driver_id=req.driver_id,
        type=req.type,
        required_by_methods=list(req.required_by_methods),
        required_for_voices=list(req.required_for_voices),
        years_required=list(req.years_required),
        unit=row.unit if row is not None else req.unit,
        current_status=_resolve_status(req, row),
        values=row.values if row is not None else None,
        static_parameters=row.static_parameters if row is not None else None,
        uploaded_at=row.uploaded_at if row is not None else None,
        updated_at=row.updated_at if row is not None else None,
    )


def _summarise(entries: list[DriverRequirementEntry]) -> DriverRequirementsSummary:
    counts = {
        _STATUS_COMPLETE: 0,
        _STATUS_PARTIAL: 0,
        _STATUS_MISSING: 0,
        _STATUS_SKIPPED: 0,
    }
    for entry in entries:
        if entry.current_status in counts:
            counts[entry.current_status] += 1
    return DriverRequirementsSummary(
        total=len(entries),
        complete=counts[_STATUS_COMPLETE],
        partial=counts[_STATUS_PARTIAL],
        missing=counts[_STATUS_MISSING],
        skipped=counts[_STATUS_SKIPPED],
    )


@router.get("/required", response_model=DriverRequirementsList)
def get_required_drivers(
    project_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> DriverRequirementsList:
    _get_project_or_404(db, project_id)
    reg = _registries()

    required = _required_index(db, project_id, reg)
    rows_by_driver: dict[str, Driver] = {
        r.driver_id: r for r in list_drivers(db, project_id)
    }

    entries: list[DriverRequirementEntry] = [
        _entry_from(req, rows_by_driver.get(driver_id))
        for driver_id, req in sorted(required.items())
    ]

    return DriverRequirementsList(
        project_id=project_id,
        count=len(entries),
        summary=_summarise(entries),
        items=entries,
    )


def _validate_upload_against_requirement(
    payload: DriverUpload, req: RequiredDriver
) -> None:
    if req.type == DRIVER_TYPE_SCALAR:
        if payload.static_parameters is not None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"driver '{req.driver_id}' is scalar_per_year; "
                    f"static_parameters not accepted"
                ),
            )
        values = payload.values or {}
        unknown = sorted(set(values.keys()) - set(req.years_required))
        if unknown:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"driver '{req.driver_id}' accepts years "
                    f"{req.years_required}; unexpected: {unknown}"
                ),
            )
    elif req.type == DRIVER_TYPE_STATIC_PARAMETERS:
        if payload.values is not None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"driver '{req.driver_id}' is static_parameters; "
                    f"per-year values not accepted"
                ),
            )


@router.post("/upload", response_model=DriverRequirementEntry)
def upload_driver(
    project_id: str,
    payload: DriverUpload,
    db: Annotated[Session, Depends(get_db)],
) -> DriverRequirementEntry:
    _get_project_or_404(db, project_id)
    reg = _registries()

    required = _required_index(db, project_id, reg)
    req = required.get(payload.driver_id)
    if req is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"driver '{payload.driver_id}' is not required by any "
                f"method config of this project"
            ),
        )

    _validate_upload_against_requirement(payload, req)

    row = upsert_driver(
        db,
        project_id=project_id,
        driver_id=payload.driver_id,
        driver_type=req.type,
        values=payload.values,
        static_parameters=payload.static_parameters,
        unit=payload.unit,
    )
    db.commit()
    db.refresh(row)
    return _entry_from(req, row)


@router.patch(
    "/{driver_id:path}/skip",
    response_model=DriverRequirementEntry,
)
def skip_driver(
    project_id: str,
    driver_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> DriverRequirementEntry:
    _get_project_or_404(db, project_id)
    reg = _registries()

    required = _required_index(db, project_id, reg)
    req = required.get(driver_id)
    if req is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"driver '{driver_id}' is not required by any method "
                f"config of this project"
            ),
        )

    row = mark_driver_skipped(
        db,
        project_id=project_id,
        driver_id=driver_id,
        driver_type=req.type,
    )
    db.commit()
    db.refresh(row)
    return _entry_from(req, row)


__all__ = ["router", "DRIVER_STATUS_ACTIVE", "DRIVER_STATUS_SKIPPED"]

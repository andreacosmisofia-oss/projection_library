"""Driver intake routes — Milestone M7 (``flows/05_driver_intake.md``).

Three endpoints:

* ``GET /api/projects/{id}/drivers/required`` — derive the per-project
  driver requirement list from method_configs × method_registry,
  joined with the persisted state for status/year roll-up.
* ``POST /api/projects/{id}/drivers/upload`` — replace the rows for
  a single driver with the supplied payload (full overwrite).
* ``PATCH /api/projects/{id}/drivers/{driver_id}/skip`` — mark a
  driver as skipped (idempotent), wiping any previously uploaded
  values.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.api.schemas.drivers import (
    DriverSkipResponse,
    DriverUpload,
    DriverUploadResponse,
    RequiredDriver,
    RequiredDriverList,
    RequiredDriverSummary,
)
from backend.domain.drivers import (
    STATUS_COMPLETE,
    STATUS_MISSING,
    STATUS_PARTIAL,
    STATUS_SKIPPED,
    compute_driver_status,
    compute_required_drivers,
)
from backend.domain.methods import resolve_default_method
from backend.infrastructure.db.database import get_db
from backend.infrastructure.db.models import Balance, Driver, MethodConfig, Project
from backend.infrastructure.db.repositories.drivers_repo import (
    list_drivers,
    list_drivers_for_id,
    mark_driver_skipped,
    replace_driver_data,
)
from backend.infrastructure.registry import Registries, get_cache
from sqlalchemy import select

router = APIRouter(prefix="/api/projects/{project_id}/drivers", tags=["drivers"])


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


def _project_method_configs(
    db: Session, project_id: str, registries: Registries
) -> list[tuple[str, str]]:
    """Build the ``(voice_id, method_id)`` list M7 reasons over.

    Voices with a persisted ``method_configs`` row use that row's
    ``method_id``; voices without a row inherit the registry default
    (mirrors the M6 GET semantics). Voices whose default is the
    ``(utente sceglie)`` sentinel and which haven't been configured
    are skipped — they don't yet declare a method, so they don't yet
    declare drivers.
    """
    rows = db.execute(
        select(MethodConfig).where(MethodConfig.project_id == project_id)
    ).scalars().all()
    by_voice = {row.voice_id: row.method_id for row in rows}

    configs: list[tuple[str, str]] = []
    for voice_id, voice in registries.voices.items():
        method_id = by_voice.get(voice_id)
        if method_id is None:
            method_id = resolve_default_method(voice)
        if not method_id:
            continue
        configs.append((voice_id, method_id))
    return configs


def _years_required_for_project(db: Session, project_id: str) -> list[str]:
    """Pull the historical years from the active balance, falling back
    to ``["Y0"]`` when no balance has been uploaded yet.

    The drivers run in parallel to the balance: a project with Y-1/Y0
    balance data needs Y-1/Y0 driver values too. Sorting matches the
    natural Y-N → Y0 ordering so the response is stable.
    """
    balance = db.execute(
        select(Balance).where(
            Balance.project_id == project_id,
            Balance.deleted_at.is_(None),
        )
    ).scalars().first()
    if balance is None or not balance.years_present:
        return ["Y0"]
    return sorted(balance.years_present, key=_year_sort_key)


def _year_sort_key(year: str) -> tuple[int, int]:
    """Sort ``Y-3, Y-2, Y-1, Y0, Y1, …`` numerically."""
    if year.startswith("Y"):
        try:
            return (0, int(year[1:]))
        except ValueError:
            return (1, 0)
    return (1, 0)


def _index_drivers(rows: list[Driver]) -> dict[str, list[Driver]]:
    out: dict[str, list[Driver]] = {}
    for row in rows:
        out.setdefault(row.driver_id, []).append(row)
    return out


def _build_required_entry(
    requirement,
    rows: list[Driver],
    years_required: list[str],
) -> RequiredDriver:
    skipped = any(r.skipped for r in rows)
    data_rows = [r for r in rows if not r.skipped]
    present_years = sorted(
        {r.year for r in data_rows if r.year and r.type == requirement.type
         and requirement.type == "scalar_per_year"},
        key=_year_sort_key,
    )
    has_static = any(
        r.type == "static_parameters" and r.static_parameters for r in data_rows
    )
    has_time_series = any(
        r.type == "time_series" and r.time_series for r in data_rows
    )
    has_aging = any(
        r.type == "aging_bucket" and r.aging_buckets for r in data_rows
    )
    unit = next((r.unit for r in data_rows if r.unit), None)

    current_status = compute_driver_status(
        driver_type=requirement.type,
        skipped=skipped,
        present_years=set(present_years),
        required_years=set(years_required),
        has_static_parameters=has_static,
        has_time_series=has_time_series,
        has_aging_buckets=has_aging,
    )

    return RequiredDriver(
        driver_id=requirement.driver_id,
        type=requirement.type,
        required_by_methods=list(requirement.required_by_methods),
        required_for_voices=list(requirement.required_for_voices),
        years_required=list(years_required),
        current_status=current_status,
        parameterized=requirement.parameterized,
        unresolved_placeholders=list(requirement.unresolved_placeholders),
        unit=unit,
        present_years=present_years,
    )


def _summarise(items: list[RequiredDriver]) -> RequiredDriverSummary:
    counts = {
        STATUS_COMPLETE: 0,
        STATUS_PARTIAL: 0,
        STATUS_MISSING: 0,
        STATUS_SKIPPED: 0,
    }
    for item in items:
        counts[item.current_status] = counts.get(item.current_status, 0) + 1
    return RequiredDriverSummary(
        total=len(items),
        complete=counts[STATUS_COMPLETE],
        partial=counts[STATUS_PARTIAL],
        missing=counts[STATUS_MISSING],
        skipped=counts[STATUS_SKIPPED],
    )


@router.get("/required", response_model=RequiredDriverList)
def get_required_drivers(
    project_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> RequiredDriverList:
    _get_project_or_404(db, project_id)
    reg = _registries()

    method_configs = _project_method_configs(db, project_id, reg)
    requirements = compute_required_drivers(method_configs, reg)

    rows_by_driver = _index_drivers(list_drivers(db, project_id))
    years_required = _years_required_for_project(db, project_id)

    items = [
        _build_required_entry(
            req, rows_by_driver.get(req.driver_id, []), years_required
        )
        for req in requirements
    ]

    return RequiredDriverList(
        project_id=project_id,
        count=len(items),
        summary=_summarise(items),
        items=items,
    )


def _materialise_upload(
    project_id: str, payload: DriverUpload, now: datetime
) -> list[Driver]:
    """Turn a single upload payload into the rows the repo will persist."""
    rows: list[Driver] = []
    if payload.type == "scalar_per_year":
        assert payload.values is not None  # guaranteed by validator
        for year, value in payload.values.items():
            rows.append(
                Driver(
                    project_id=project_id,
                    driver_id=payload.driver_id,
                    type=payload.type,
                    year=year,
                    value=value,
                    unit=payload.unit,
                    static_parameters=None,
                    time_series=None,
                    aging_buckets=None,
                    skipped=False,
                    uploaded_at=now,
                )
            )
        return rows
    # Non-time-varying types collapse into a single row keyed by
    # ``year=""``; the unique index keeps re-uploads idempotent.
    rows.append(
        Driver(
            project_id=project_id,
            driver_id=payload.driver_id,
            type=payload.type,
            year="",
            value=None,
            unit=payload.unit,
            static_parameters=(
                dict(payload.static_parameters)
                if payload.type == "static_parameters" else None
            ),
            time_series=(
                list(payload.time_series)
                if payload.type == "time_series" else None
            ),
            aging_buckets=(
                dict(payload.aging_buckets)
                if payload.type == "aging_bucket" else None
            ),
            skipped=False,
            uploaded_at=now,
        )
    )
    return rows


@router.post(
    "/upload",
    response_model=DriverUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
def upload_driver(
    project_id: str,
    payload: DriverUpload,
    db: Annotated[Session, Depends(get_db)],
) -> DriverUploadResponse:
    _get_project_or_404(db, project_id)

    now = datetime.now(timezone.utc)
    rows = _materialise_upload(project_id, payload, now)
    written = replace_driver_data(db, project_id, payload.driver_id, rows)
    db.commit()

    return DriverUploadResponse(
        project_id=project_id,
        driver_id=payload.driver_id,
        type=payload.type,
        rows_written=len(written),
        uploaded_at=now,
    )


@router.patch(
    "/{driver_id:path}/skip",
    response_model=DriverSkipResponse,
)
def patch_driver_skip(
    project_id: str,
    driver_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> DriverSkipResponse:
    _get_project_or_404(db, project_id)
    if not driver_id.startswith("driver."):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"driver_id '{driver_id}' must start with 'driver.' "
                f"(see flows/05_driver_intake.md)"
            ),
        )

    marker = mark_driver_skipped(db, project_id, driver_id)
    db.commit()
    db.refresh(marker)

    return DriverSkipResponse(
        project_id=project_id,
        driver_id=driver_id,
        skipped=True,
        skipped_at=marker.uploaded_at,
    )


# Convenience read used by tests and (eventually) the engine, exposed
# under the same prefix so the route table stays cohesive.
@router.get("/{driver_id:path}", response_model=list[dict])
def get_driver_rows(
    project_id: str,
    driver_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> list[dict]:
    _get_project_or_404(db, project_id)
    rows = list_drivers_for_id(db, project_id, driver_id)
    return [
        {
            "id": r.id,
            "driver_id": r.driver_id,
            "type": r.type,
            "year": r.year,
            "value": r.value,
            "unit": r.unit,
            "static_parameters": r.static_parameters,
            "time_series": r.time_series,
            "aging_buckets": r.aging_buckets,
            "skipped": r.skipped,
            "uploaded_at": r.uploaded_at.isoformat() if r.uploaded_at else None,
        }
        for r in rows
    ]


__all__ = ["router"]

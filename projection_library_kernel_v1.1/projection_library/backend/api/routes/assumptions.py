"""Assumption-compilation routes — Milestone M8.

Four endpoints, modelled on the M7 driver-intake routes
(``backend/api/routes/drivers.py``):

* ``POST /api/projects/{id}/assumptions/populate-defaults`` — derive the
  per-(voice, method, assumption_name) defaults from
  ``method_configs`` × ``method_registry`` × ``historical_kpis`` and
  persist them flat across Y1/Y2/Y3. Idempotent: ``user_input`` rows
  are preserved.
* ``GET /api/projects/{id}/assumptions`` — pivoted view of the persisted
  rows (one entry per (voice, method, assumption_name) with a values
  dict keyed by year), plus the curve config.
* ``PATCH /api/projects/{id}/assumptions/{voice_id:path}/{name}/{year}``
  — update one cell, force ``source=user_input``, recompute
  ``validation_status``.
* ``POST /api/projects/{id}/assumptions/{voice_id:path}/{name}/curve``
  — apply a flat/linear_drift/custom curve and persist the curve
  config.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.schemas.assumptions import (
    AssumptionCurveRequest,
    AssumptionCurveResponse,
    AssumptionEntry,
    AssumptionListResponse,
    AssumptionListSummary,
    AssumptionPatchRequest,
    AssumptionPatchResponse,
    AssumptionPopulateResponse,
)
from backend.domain.assumptions import (
    SOURCE_DEFAULT_KPI,
    SOURCE_FALLBACK,
    SOURCE_USER_INPUT,
    VALIDATION_OK,
    VALIDATION_WARNING_RANGE,
    apply_curve,
    compute_assumption_defaults,
    validate_value_in_range,
)
from backend.domain.assumptions.curves import CURVE_FLAT
from backend.domain.intake.mapping_resolver import resolve_mapped_values
from backend.domain.methods import resolve_default_method
from backend.infrastructure.db.database import get_db
from backend.infrastructure.db.models import (
    Assumption,
    AssumptionCurveConfig,
    HistoricalKPI,
    MethodConfig,
    Project,
)
from backend.infrastructure.db.repositories.assumptions_repo import (
    find_assumptions_for_voice_name,
    list_assumptions,
    list_curves,
    replace_defaults_for_project,
    upsert_assumption_value,
    upsert_assumption_value_for_year,
    upsert_curve,
)
from backend.infrastructure.registry import Registries, get_cache


router = APIRouter(
    prefix="/api/projects/{project_id}/assumptions", tags=["assumptions"]
)


# ---------------------------------------------------------------------------
# Common helpers (mirrors of the M7 route patterns)
# ---------------------------------------------------------------------------


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
    """Build the active ``(voice_id, method_id)`` list (M7 mirror).

    Voices with a persisted ``method_configs`` row use that row's
    ``method_id``; voices without a row inherit the registry default.
    Voices whose default is the user-choice sentinel are skipped:
    they don't yet declare a method, so they don't yet declare any
    assumptions.
    """
    rows = list(
        db.execute(
            select(MethodConfig).where(MethodConfig.project_id == project_id)
        ).scalars()
    )
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


def _kpi_agg_index(
    db: Session, project_id: str
) -> dict[str, tuple[float | None, float | None]]:
    """Pull the AGG rows for the project into a ``{kpi_id: (default, calib)}``."""
    rows = list(
        db.execute(
            select(HistoricalKPI).where(
                HistoricalKPI.project_id == project_id,
                HistoricalKPI.year == "AGG",
            )
        ).scalars()
    )
    return {
        row.kpi_id: (row.default_for_projection, row.calibration_score)
        for row in rows
    }


def _validation_status_for(
    value: float, row: Assumption | None = None,
    *,
    range_min: float | None = None,
    range_max: float | None = None,
) -> str:
    """Apply the heuristic range to ``value`` against the persisted bounds."""
    if row is not None:
        range_min = row.validation_range_min
        range_max = row.validation_range_max
    return validate_value_in_range(value, range_min, range_max)


# ---------------------------------------------------------------------------
# POST /populate-defaults
# ---------------------------------------------------------------------------


@router.post(
    "/populate-defaults",
    response_model=AssumptionPopulateResponse,
    status_code=status.HTTP_200_OK,
)
def populate_defaults(
    project_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> AssumptionPopulateResponse:
    """Re-seed defaults from ``historical_kpis`` and the active methods.

    Preserves ``user_input`` rows whose ``(voice, method, name)`` is
    still present in the new defaults; drops everything else.
    """
    _get_project_or_404(db, project_id)
    registries = _registries()

    configs = _project_method_configs(db, project_id, registries)
    kpi_index = _kpi_agg_index(db, project_id)

    # Mapped values are optional — they're only consulted by the
    # template-KPI fallback. A project without a balance still gets
    # defaults (zero fallback for those rows).
    try:
        mapped = resolve_mapped_values(db, project_id)
    except LookupError:
        mapped = None

    defaults = compute_assumption_defaults(
        configs, registries, kpi_index, mapped_values=mapped
    )
    counts = replace_defaults_for_project(db, project_id, defaults)
    db.commit()

    return AssumptionPopulateResponse(
        project_id=project_id,
        populated=counts["populated"],
        kpi_default_used=counts["kpi_default_used"],
        fallback_used=counts["fallback_used"],
        preserved_user_input=counts["preserved_user_input"],
        populated_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# GET /
# ---------------------------------------------------------------------------


def _pivot_rows_to_entries(
    rows: list[Assumption],
    curves: list[AssumptionCurveConfig],
    registries: Registries,
) -> list[AssumptionEntry]:
    """Group per-year rows into one :class:`AssumptionEntry` per name."""
    by_key: dict[
        tuple[str, str, str], list[Assumption]
    ] = defaultdict(list)
    for row in rows:
        by_key[(row.voice_id, row.method_id, row.assumption_name)].append(row)

    curve_by_key = {
        (c.voice_id, c.method_id, c.assumption_name): c.curve_type
        for c in curves
    }

    entries: list[AssumptionEntry] = []
    for (voice_id, method_id, name), bucket in by_key.items():
        # Sort years deterministically (Y1 < Y2 < Y3 lexicographically already).
        bucket.sort(key=lambda r: r.year)
        first = bucket[0]
        voice = registries.voices.get(voice_id, {})
        validation_range: tuple[float | None, float | None] | None
        if (
            first.validation_range_min is None
            and first.validation_range_max is None
        ):
            validation_range = None
        else:
            validation_range = (
                first.validation_range_min,
                first.validation_range_max,
            )

        values: dict[str, float] = {}
        sources: dict[str, str] = {}
        statuses: dict[str, str] = {}
        modified: dict[str, datetime] = {}
        for row in bucket:
            values[row.year] = row.value
            sources[row.year] = row.source
            statuses[row.year] = (
                VALIDATION_WARNING_RANGE
                if _validation_status_for(row.value, row)
                == VALIDATION_WARNING_RANGE
                else VALIDATION_OK
            )
            if row.user_modified_at is not None:
                modified[row.year] = row.user_modified_at

        entries.append(
            AssumptionEntry(
                voice_id=voice_id,
                voice_statement=voice.get("statement"),
                voice_section=voice.get("section"),
                method_id=method_id,
                assumption_name=name,
                parameterized=first.parameterized,
                values=values,
                source=sources,
                validation_status=statuses,
                user_modified_at=modified,
                default_kpi_id=first.default_kpi_id,
                calibration_score=first.calibration_score,
                validation_range=validation_range,
                curve_type=curve_by_key.get(
                    (voice_id, method_id, name), CURVE_FLAT
                ),
            )
        )

    entries.sort(
        key=lambda e: (
            e.voice_statement or "",
            e.voice_section or "",
            e.voice_id,
            e.method_id,
            e.assumption_name,
        )
    )
    return entries


def _summarise(entries: list[AssumptionEntry]) -> AssumptionListSummary:
    """Aggregate per-cell counts across every entry into the response summary."""
    total = 0
    default_kpi = 0
    user_input = 0
    fallback = 0
    warnings = 0
    for entry in entries:
        for year, src in entry.source.items():
            total += 1
            if src == SOURCE_DEFAULT_KPI:
                default_kpi += 1
            elif src == SOURCE_USER_INPUT:
                user_input += 1
            elif src == SOURCE_FALLBACK:
                fallback += 1
            if entry.validation_status.get(year) == VALIDATION_WARNING_RANGE:
                warnings += 1
    return AssumptionListSummary(
        total=total,
        default_kpi=default_kpi,
        user_input=user_input,
        fallback=fallback,
        warning_range=warnings,
    )


@router.get("", response_model=AssumptionListResponse)
def list_project_assumptions(
    project_id: str,
    db: Annotated[Session, Depends(get_db)],
    voice_id: Annotated[
        str | None,
        Query(description="Optional filter on a single voice_id"),
    ] = None,
) -> AssumptionListResponse:
    _get_project_or_404(db, project_id)
    registries = _registries()

    rows = list_assumptions(db, project_id)
    if voice_id is not None:
        rows = [r for r in rows if r.voice_id == voice_id]
    curves = list_curves(db, project_id)
    if voice_id is not None:
        curves = [c for c in curves if c.voice_id == voice_id]

    entries = _pivot_rows_to_entries(rows, curves, registries)
    return AssumptionListResponse(
        project_id=project_id,
        count=len(entries),
        summary=_summarise(entries),
        items=entries,
    )


# ---------------------------------------------------------------------------
# PATCH /{voice_id:path}/{assumption_name}/{year}
# ---------------------------------------------------------------------------


_VALID_YEARS = frozenset({"Y1", "Y2", "Y3"})


def _resolve_method_for_voice_name(
    db: Session,
    project_id: str,
    voice_id: str,
    assumption_name: str,
) -> str:
    """Pick the unique active ``method_id`` for (project, voice, name).

    The unique index on ``method_configs(project_id, voice_id)`` keeps
    one method per voice, so the persisted assumption rows for one
    name normally share a method. If we somehow find more than one
    (stale rows after a manual DB edit) we surface 409 and let the
    user resolve via populate-defaults.
    """
    rows = find_assumptions_for_voice_name(
        db, project_id, voice_id, assumption_name
    )
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"no assumption found for voice '{voice_id}' / "
                f"assumption '{assumption_name}'; run populate-defaults first"
            ),
        )
    methods = {row.method_id for row in rows}
    if len(methods) > 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"multiple methods found for voice '{voice_id}' / "
                f"assumption '{assumption_name}': {sorted(methods)}; "
                f"run populate-defaults to reconcile"
            ),
        )
    return methods.pop()


@router.patch(
    "/{voice_id:path}/{assumption_name}/{year}",
    response_model=AssumptionPatchResponse,
)
def patch_assumption(
    project_id: str,
    voice_id: str,
    assumption_name: str,
    year: str,
    payload: AssumptionPatchRequest,
    db: Annotated[Session, Depends(get_db)],
) -> AssumptionPatchResponse:
    _get_project_or_404(db, project_id)

    if year not in _VALID_YEARS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"year must be one of {sorted(_VALID_YEARS)}",
        )

    method_id = _resolve_method_for_voice_name(
        db, project_id, voice_id, assumption_name
    )
    try:
        row = upsert_assumption_value(
            db,
            project_id=project_id,
            voice_id=voice_id,
            method_id=method_id,
            assumption_name=assumption_name,
            year=year,
            value=payload.value,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    db.commit()
    db.refresh(row)

    return AssumptionPatchResponse(
        voice_id=row.voice_id,
        method_id=row.method_id,
        assumption_name=row.assumption_name,
        year=row.year,
        value=row.value,
        source=row.source,
        validation_status=_validation_status_for(row.value, row),
        validation_range=(
            (row.validation_range_min, row.validation_range_max)
            if row.validation_range_min is not None
            or row.validation_range_max is not None
            else None
        ),
        user_modified_at=row.user_modified_at,
    )


# ---------------------------------------------------------------------------
# POST /{voice_id:path}/{assumption_name}/curve
# ---------------------------------------------------------------------------


@router.post(
    "/{voice_id:path}/{assumption_name}/curve",
    response_model=AssumptionCurveResponse,
)
def post_assumption_curve(
    project_id: str,
    voice_id: str,
    assumption_name: str,
    payload: AssumptionCurveRequest,
    db: Annotated[Session, Depends(get_db)],
) -> AssumptionCurveResponse:
    _get_project_or_404(db, project_id)

    method_id = _resolve_method_for_voice_name(
        db, project_id, voice_id, assumption_name
    )

    expanded = apply_curve(
        payload.curve_type,
        y1=payload.y1,
        y3=payload.y3,
        values=payload.values,
    )

    # Persist all three values + the curve config in one transaction.
    last_range_min: float | None = None
    last_range_max: float | None = None
    for year, value in expanded.items():
        try:
            row = upsert_assumption_value_for_year(
                db,
                project_id=project_id,
                voice_id=voice_id,
                method_id=method_id,
                assumption_name=assumption_name,
                year=year,
                value=value,
            )
        except LookupError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
            ) from exc
        last_range_min = row.validation_range_min
        last_range_max = row.validation_range_max

    curve_row = upsert_curve(
        db,
        project_id=project_id,
        voice_id=voice_id,
        method_id=method_id,
        assumption_name=assumption_name,
        curve_type=payload.curve_type,
    )
    db.commit()
    db.refresh(curve_row)

    statuses = {
        year: validate_value_in_range(value, last_range_min, last_range_max)
        for year, value in expanded.items()
    }

    return AssumptionCurveResponse(
        voice_id=voice_id,
        method_id=method_id,
        assumption_name=assumption_name,
        curve_type=curve_row.curve_type,
        values=expanded,
        validation_status=statuses,
        validation_range=(
            (last_range_min, last_range_max)
            if last_range_min is not None or last_range_max is not None
            else None
        ),
        configured_at=curve_row.configured_at,
    )


__all__ = ["router"]

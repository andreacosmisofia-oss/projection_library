"""Assumption routes — Milestone M8 (``flows/06_assumption_compilation.md``).

Four endpoints under ``/api/projects/{project_id}/assumptions``:

* ``POST /populate-defaults`` — seed Y1/Y2/Y3 rows from KPI AGGs;
* ``GET ""`` — collapsed Y1/Y2/Y3 rows + curve + calibration;
* ``PATCH /{voice_id}/{assumption_name}/{year}`` — single-value edit;
* ``POST /{voice_id}/{assumption_name}/curve`` — apply curve shape.

None of these endpoints triggers an engine re-run: the user owns the
"Refresh" button. The dashboard store flips ``isModelDirty`` on the
client side after every mutation (see ``frontend/src/api/useAssumptions.ts``).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.api.schemas.assumptions import (
    AssumptionCurveRequest,
    AssumptionList,
    AssumptionPatch,
    AssumptionRow,
    PopulateReport,
)
from backend.domain.assumptions.curve import YEARS, apply_curve
from backend.domain.assumptions.populator import populate_defaults
from backend.domain.assumptions.service import compose_assumption_list
from backend.domain.assumptions.validator import classify_triplet
from backend.infrastructure.db.database import get_db
from backend.infrastructure.db.models import HistoricalKPI, Project
from backend.infrastructure.db.repositories.assumptions_repo import (
    get_assumption,
    get_curve_config,
    list_assumption_triplet,
    update_value,
    upsert_curve_config,
    upsert_value,
)
from backend.infrastructure.db.repositories.method_configs_repo import (
    get_method_config,
)
from backend.infrastructure.registry import Registries, get_cache

router = APIRouter(
    prefix="/api/projects/{project_id}/assumptions",
    tags=["assumptions"],
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


def _resolve_method_id(
    db: Session, project_id: str, voice_id: str
) -> str:
    """Look up the configured method for a voice, or 422.

    The PATCH/curve paths don't carry ``method_id`` (UI-friendly),
    so we resolve it through ``method_configs``. A missing config
    means the user hasn't completed M6 — surface that as 422 rather
    than fabricating a default.
    """
    config = get_method_config(db, project_id, voice_id)
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"voice '{voice_id}' has no method configured; "
                "set one via /api/projects/{id}/methods first"
            ),
        )
    return config.method_id


def _kpi_calibration(
    db: Session, project_id: str, kpi_id: str | None
) -> float | None:
    """Look up the AGG calibration score for a KPI (read-time field)."""
    if not kpi_id:
        return None
    from sqlalchemy import select

    row = db.execute(
        select(HistoricalKPI).where(
            HistoricalKPI.project_id == project_id,
            HistoricalKPI.kpi_id == kpi_id,
            HistoricalKPI.year == "AGG",
        )
    ).scalars().first()
    return row.calibration_score if row is not None else None


def _row_from_triplet(
    db: Session,
    project_id: str,
    voice_id: str,
    method_id: str,
    assumption_name: str,
) -> AssumptionRow:
    """Re-read the triplet and return the API row.

    Used by PATCH and the curve endpoint to return the freshly-mutated
    assumption with all derived fields recomputed. Reads from the
    same session, so committed-but-unflushed state is visible.
    """
    triplet = list_assumption_triplet(
        db,
        project_id=project_id,
        voice_id=voice_id,
        method_id=method_id,
        assumption_name=assumption_name,
    )
    if not triplet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"assumption '{voice_id}/{assumption_name}' has no rows; "
                "run populate-defaults first"
            ),
        )

    values = {r.year: r.value for r in triplet}
    sources = {r.source for r in triplet}
    if "user_input" in sources:
        source = "user_input"
    elif sources == {"fallback"}:
        source = "fallback"
    elif "fallback" in sources:
        source = "fallback"
    else:
        source = "default_kpi"

    default_kpi_id = next(
        (r.default_kpi_id for r in triplet if r.default_kpi_id), None
    )
    validation_range = next(
        (r.validation_range for r in triplet if r.validation_range), None
    )
    last_edits = [
        r.user_modified_at for r in triplet if r.user_modified_at is not None
    ]
    user_modified_at = max(last_edits) if last_edits else None

    curve = get_curve_config(
        db,
        project_id=project_id,
        voice_id=voice_id,
        method_id=method_id,
        assumption_name=assumption_name,
    )
    curve_type = curve.curve_type if curve is not None else "flat"

    calibration = _kpi_calibration(db, project_id, default_kpi_id)
    validation_status = classify_triplet(
        [r.value for r in triplet], validation_range
    )

    return AssumptionRow(
        voice_id=voice_id,
        method_id=method_id,
        assumption_name=assumption_name,
        values=values,  # type: ignore[arg-type]
        source=source,  # type: ignore[arg-type]
        default_kpi_id=default_kpi_id,
        calibration_score=calibration,
        validation_status=validation_status,
        validation_range=validation_range,
        curve_type=curve_type,  # type: ignore[arg-type]
        user_modified_at=user_modified_at,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/populate-defaults",
    response_model=PopulateReport,
    status_code=status.HTTP_200_OK,
)
def post_populate_defaults(
    project_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> PopulateReport:
    _get_project_or_404(db, project_id)
    report = populate_defaults(db, project_id, _registries())
    db.commit()
    return PopulateReport.model_validate(report.__dict__)


@router.get("", response_model=AssumptionList)
def get_assumptions_list(
    project_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> AssumptionList:
    _get_project_or_404(db, project_id)
    rows = compose_assumption_list(db, project_id)
    items = [
        AssumptionRow(
            voice_id=r.voice_id,
            method_id=r.method_id,
            assumption_name=r.assumption_name,
            values=r.values,  # type: ignore[arg-type]
            source=r.source,  # type: ignore[arg-type]
            default_kpi_id=r.default_kpi_id,
            calibration_score=r.calibration_score,
            validation_status=r.validation_status,
            validation_range=r.validation_range,
            curve_type=r.curve_type,  # type: ignore[arg-type]
            user_modified_at=r.user_modified_at,
        )
        for r in rows
    ]
    return AssumptionList(
        project_id=project_id, count=len(items), items=items
    )


@router.patch(
    "/{voice_id}/{assumption_name}/{year}",
    response_model=AssumptionRow,
)
def patch_assumption_value(
    project_id: str,
    voice_id: str,
    assumption_name: str,
    year: str,
    payload: AssumptionPatch,
    db: Annotated[Session, Depends(get_db)],
) -> AssumptionRow:
    _get_project_or_404(db, project_id)
    if year not in YEARS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"invalid year '{year}'; expected one of {YEARS}",
        )

    method_id = _resolve_method_id(db, project_id, voice_id)
    row = get_assumption(
        db,
        project_id=project_id,
        voice_id=voice_id,
        method_id=method_id,
        assumption_name=assumption_name,
        year=year,
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"assumption '{voice_id}/{assumption_name}/{year}' "
                "not found; run populate-defaults first"
            ),
        )

    update_value(db, row, value=float(payload.value))
    db.commit()

    return _row_from_triplet(
        db, project_id, voice_id, method_id, assumption_name
    )


@router.post(
    "/{voice_id}/{assumption_name}/curve",
    response_model=AssumptionRow,
)
def post_assumption_curve(
    project_id: str,
    voice_id: str,
    assumption_name: str,
    payload: AssumptionCurveRequest,
    db: Annotated[Session, Depends(get_db)],
) -> AssumptionRow:
    _get_project_or_404(db, project_id)
    method_id = _resolve_method_id(db, project_id, voice_id)

    triplet = list_assumption_triplet(
        db,
        project_id=project_id,
        voice_id=voice_id,
        method_id=method_id,
        assumption_name=assumption_name,
    )
    if not triplet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"assumption '{voice_id}/{assumption_name}' has no rows; "
                "run populate-defaults first"
            ),
        )
    current_values = {r.year: r.value for r in triplet}
    default_kpi_id = next(
        (r.default_kpi_id for r in triplet if r.default_kpi_id), None
    )
    validation_range = next(
        (r.validation_range for r in triplet if r.validation_range), None
    )

    try:
        new_values = apply_curve(
            payload.curve_type,
            y1=payload.y1,
            y3=payload.y3,
            current=current_values,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    for year, value in new_values.items():
        upsert_value(
            db,
            project_id=project_id,
            voice_id=voice_id,
            method_id=method_id,
            assumption_name=assumption_name,
            year=year,
            value=value,
            default_kpi_id=default_kpi_id,
            validation_range=validation_range,
        )
    upsert_curve_config(
        db,
        project_id=project_id,
        voice_id=voice_id,
        method_id=method_id,
        assumption_name=assumption_name,
        curve_type=payload.curve_type,
    )
    db.commit()

    return _row_from_triplet(
        db, project_id, voice_id, method_id, assumption_name
    )


__all__ = ["router"]

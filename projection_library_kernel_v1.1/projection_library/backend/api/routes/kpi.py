"""Historical KPI routes — Milestone M5.

POST computes + persists; GET returns the persisted snapshot grouped
by KPI for the UI.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.api.schemas.kpi import KPIComputeResponse, KPIListResponse, KPIRow
from backend.domain.intake import resolve_mapped_values
from backend.domain.kpi import compute_historical_kpis
from backend.infrastructure.db.database import get_db
from backend.infrastructure.db.models import Project
from backend.infrastructure.db.repositories.m5_repos import (
    list_historical_kpis,
    replace_historical_kpis,
)
from backend.infrastructure.registry import get_cache

router = APIRouter(prefix="/api/projects/{project_id}", tags=["kpi"])


def _get_project_or_404(db: Session, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if project is None or project.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"project '{project_id}' not found",
        )
    return project


@router.post(
    "/kpi-historical",
    response_model=KPIComputeResponse,
    status_code=status.HTTP_200_OK,
)
def compute(
    project_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> KPIComputeResponse:
    _get_project_or_404(db, project_id)
    try:
        values = resolve_mapped_values(db, project_id)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc

    registries = get_cache().get()
    snapshot = compute_historical_kpis(values, registries)
    replace_historical_kpis(db, project_id, snapshot)
    db.commit()
    return KPIComputeResponse(
        project_id=project_id,
        counts=snapshot.counts,
        stored_at=datetime.now(timezone.utc),
    )


@router.get("/kpi-historical", response_model=KPIListResponse)
def list_kpis(
    project_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> KPIListResponse:
    _get_project_or_404(db, project_id)
    rows = list_historical_kpis(db, project_id)
    if not rows:
        return KPIListResponse(project_id=project_id, kpis=[], counts={})

    by_kpi: dict[str, dict] = defaultdict(
        lambda: {
            "values": {},
            "default_for_projection": None,
            "calibration_score": None,
            "lfl_warning": False,
            "not_computable_reason": None,
        }
    )
    for row in rows:
        bucket = by_kpi[row.kpi_id]
        if row.year == "AGG":
            bucket["default_for_projection"] = row.default_for_projection
            bucket["calibration_score"] = row.calibration_score
            bucket["lfl_warning"] = row.lfl_warning
            bucket["not_computable_reason"] = row.not_computable_reason
        elif row.value is not None:
            bucket["values"][row.year] = row.value

    counts = {"total": len(by_kpi), "computed": 0, "not_computable": 0}
    kpis: list[KPIRow] = []
    for kpi_id, data in sorted(by_kpi.items()):
        is_computable = data["not_computable_reason"] is None and bool(
            data["values"]
        )
        if is_computable:
            counts["computed"] += 1
        else:
            counts["not_computable"] += 1
        kpis.append(KPIRow(kpi_id=kpi_id, **data))

    return KPIListResponse(project_id=project_id, kpis=kpis, counts=counts)


__all__ = ["router"]

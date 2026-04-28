"""Pydantic schemas for the M5 historical KPI endpoint."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class KPIRow(BaseModel):
    """One KPI's history + aggregated default + calibration metadata."""

    kpi_id: str
    values: dict[str, float] = Field(default_factory=dict)
    default_for_projection: float | None = None
    calibration_score: float | None = None
    lfl_warning: bool = False
    not_computable_reason: str | None = None
    used_aggregation: str | None = None


class KPIComputeResponse(BaseModel):
    """Response of ``POST .../kpi-historical``: counters + storage timestamp."""

    project_id: str
    counts: dict[str, int]
    stored_at: datetime


class KPIListResponse(BaseModel):
    """Response of ``GET .../kpi-historical``: full snapshot for the UI."""

    project_id: str
    kpis: list[KPIRow]
    counts: dict[str, int]


__all__ = ["KPIComputeResponse", "KPIListResponse", "KPIRow"]

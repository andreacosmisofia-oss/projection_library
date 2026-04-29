"""Pydantic schemas for the M8 assumptions resource.

Wire shapes mirror ``flows/06_assumption_compilation.md`` §"API"
exactly: each row collapses Y1/Y2/Y3 into a ``values`` map and
carries the read-time fields (``calibration_score``,
``validation_status``, ``curve_type``) the UI needs to render the
sidebar.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Year = Literal["Y1", "Y2", "Y3"]
Source = Literal["default_kpi", "user_input", "fallback"]
ValidationStatus = Literal["ok", "warning_range", "warning_continuity"]
CurveType = Literal["flat", "linear_drift", "custom"]


class AssumptionRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    voice_id: str
    method_id: str
    assumption_name: str
    values: dict[Year, float]
    source: Source
    default_kpi_id: str | None = None
    calibration_score: float | None = None
    validation_status: ValidationStatus
    validation_range: list[float] | None = None
    curve_type: CurveType
    user_modified_at: datetime | None = None


class AssumptionList(BaseModel):
    project_id: str
    count: int
    items: list[AssumptionRow]


class PopulateReport(BaseModel):
    populated: int
    kpi_default_used: int
    fallback_used: int
    user_input_preserved: int
    pairs_deleted: int
    methods_skipped: list[str] = Field(default_factory=list)


class AssumptionPatch(BaseModel):
    """Body of ``PATCH .../{voice_id}/{assumption_name}/{year}``."""

    value: float


class AssumptionCurveRequest(BaseModel):
    """Body of ``POST .../{voice_id}/{assumption_name}/curve``."""

    curve_type: CurveType
    y1: float | None = None
    y3: float | None = None


__all__ = [
    "AssumptionCurveRequest",
    "AssumptionList",
    "AssumptionPatch",
    "AssumptionRow",
    "CurveType",
    "PopulateReport",
    "Source",
    "ValidationStatus",
    "Year",
]

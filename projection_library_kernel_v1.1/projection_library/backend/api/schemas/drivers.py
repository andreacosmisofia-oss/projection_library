"""Pydantic schemas for the M7 driver-intake endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


DriverType = Literal[
    "scalar_per_year",
    "static_parameters",
    "time_series",
    "aging_bucket",
]

DriverStatus = Literal["missing", "partial", "complete", "skipped"]


class RequiredDriver(BaseModel):
    """One entry of ``GET /drivers/required``.

    ``parameterized`` flags drivers whose id still contains ``{...}``
    after voice substitution (nested templates that only resolve at
    runtime, e.g. ``driver.{voice}.bom_{m}_qty``). The UI surfaces
    those separately so the user is not asked to type a literal id
    with a template in it.
    """

    driver_id: str
    type: DriverType
    required_by_methods: list[str]
    required_for_voices: list[str]
    years_required: list[str]
    current_status: DriverStatus
    parameterized: bool = False
    unresolved_placeholders: list[str] = Field(default_factory=list)
    unit: str | None = None
    present_years: list[str] = Field(default_factory=list)


class RequiredDriverSummary(BaseModel):
    total: int
    complete: int
    partial: int
    missing: int
    skipped: int


class RequiredDriverList(BaseModel):
    project_id: str
    count: int
    summary: RequiredDriverSummary
    items: list[RequiredDriver]


class DriverUpload(BaseModel):
    """Body for ``POST /drivers/upload``.

    Only the fields relevant to ``type`` need to be populated; the
    others are ignored. Validation is deliberately loose so the
    endpoint accepts every shape the UI might send during incremental
    fill-in (single year, partial parameters, etc.). The repository
    replaces existing rows for the driver, so an incremental upload
    overwrites — clients must send the full intended state.
    """

    model_config = ConfigDict(extra="forbid")

    driver_id: Annotated[str, Field(min_length=1, max_length=255)]
    type: DriverType
    unit: str | None = None
    values: dict[str, float | None] | None = None
    static_parameters: dict[str, float] | None = None
    time_series: list[dict] | None = None
    aging_buckets: dict[str, float] | None = None

    @model_validator(mode="after")
    def _check_payload_matches_type(self) -> "DriverUpload":
        if self.type == "scalar_per_year":
            if not self.values:
                raise ValueError(
                    "scalar_per_year requires non-empty 'values'"
                )
        elif self.type == "static_parameters":
            if not self.static_parameters:
                raise ValueError(
                    "static_parameters requires non-empty 'static_parameters'"
                )
        elif self.type == "time_series":
            if not self.time_series:
                raise ValueError(
                    "time_series requires non-empty 'time_series'"
                )
        elif self.type == "aging_bucket":
            if not self.aging_buckets:
                raise ValueError(
                    "aging_bucket requires non-empty 'aging_buckets'"
                )
        return self


class DriverUploadResponse(BaseModel):
    project_id: str
    driver_id: str
    type: DriverType
    rows_written: int
    uploaded_at: datetime


class DriverSkipResponse(BaseModel):
    project_id: str
    driver_id: str
    skipped: bool
    skipped_at: datetime


__all__ = [
    "DriverSkipResponse",
    "DriverStatus",
    "DriverType",
    "DriverUpload",
    "DriverUploadResponse",
    "RequiredDriver",
    "RequiredDriverList",
    "RequiredDriverSummary",
]

"""Pydantic schemas for the M8 assumption-compilation endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


SourceLiteral = Literal["default_kpi", "user_input", "fallback"]
CurveTypeLiteral = Literal["flat", "linear_drift", "custom"]
ValidationStatusLiteral = Literal["ok", "warning_range"]


class AssumptionEntry(BaseModel):
    """One row of ``GET /assumptions``: pivoted across Y1/Y2/Y3.

    Per-year ``source`` and ``validation_status`` so the UI can flag a
    single year that's been overridden out of the plausible range
    without forcing a bulk recompute on the others. ``calibration_score``
    and ``default_kpi_id`` are stable across years (set at populate
    time on the seed); we surface them at the entry level rather than
    inside ``values`` to keep the payload compact.
    """

    voice_id: str
    voice_statement: str | None = None
    voice_section: str | None = None
    method_id: str
    assumption_name: str
    parameterized: bool = False
    values: dict[str, float] = Field(default_factory=dict)
    source: dict[str, SourceLiteral] = Field(default_factory=dict)
    validation_status: dict[str, ValidationStatusLiteral] = Field(
        default_factory=dict
    )
    user_modified_at: dict[str, datetime] = Field(default_factory=dict)
    default_kpi_id: str | None = None
    calibration_score: float | None = None
    validation_range: tuple[float | None, float | None] | None = None
    curve_type: CurveTypeLiteral = "flat"


class AssumptionListSummary(BaseModel):
    total: int
    default_kpi: int
    user_input: int
    fallback: int
    warning_range: int


class AssumptionListResponse(BaseModel):
    project_id: str
    count: int
    summary: AssumptionListSummary
    items: list[AssumptionEntry]


class AssumptionPopulateResponse(BaseModel):
    project_id: str
    populated: int
    kpi_default_used: int
    fallback_used: int
    preserved_user_input: int
    populated_at: datetime


class AssumptionPatchRequest(BaseModel):
    """Body for ``PATCH /assumptions/{voice}/{name}/{year}``."""

    model_config = ConfigDict(extra="forbid")

    value: float


class AssumptionPatchResponse(BaseModel):
    voice_id: str
    method_id: str
    assumption_name: str
    year: str
    value: float
    source: SourceLiteral
    validation_status: ValidationStatusLiteral
    validation_range: tuple[float | None, float | None] | None = None
    user_modified_at: datetime | None = None


class AssumptionCurveRequest(BaseModel):
    """Body for ``POST /assumptions/{voice}/{name}/curve``.

    ``flat`` takes ``y1``, ``linear_drift`` takes ``y1`` + ``y3``,
    ``custom`` takes ``values`` (a ``{Y1, Y2, Y3}`` dict). We validate
    the cross-field shape here so the route layer can call
    ``apply_curve`` straight without re-checking.
    """

    model_config = ConfigDict(extra="forbid")

    curve_type: CurveTypeLiteral
    y1: float | None = None
    y3: float | None = None
    values: dict[str, float] | None = None

    @model_validator(mode="after")
    def _check_shape(self) -> "AssumptionCurveRequest":
        if self.curve_type == "flat":
            if self.y1 is None:
                raise ValueError("curve_type='flat' requires 'y1'")
        elif self.curve_type == "linear_drift":
            if self.y1 is None or self.y3 is None:
                raise ValueError(
                    "curve_type='linear_drift' requires both 'y1' and 'y3'"
                )
        elif self.curve_type == "custom":
            if not self.values or set(self.values) != {"Y1", "Y2", "Y3"}:
                raise ValueError(
                    "curve_type='custom' requires 'values' with keys "
                    "Y1, Y2, Y3"
                )
        return self


class AssumptionCurveResponse(BaseModel):
    voice_id: str
    method_id: str
    assumption_name: str
    curve_type: CurveTypeLiteral
    values: dict[str, float]
    validation_status: dict[str, ValidationStatusLiteral]
    validation_range: tuple[float | None, float | None] | None = None
    configured_at: datetime


__all__ = [
    "AssumptionCurveRequest",
    "AssumptionCurveResponse",
    "AssumptionEntry",
    "AssumptionListResponse",
    "AssumptionListSummary",
    "AssumptionPatchRequest",
    "AssumptionPatchResponse",
    "AssumptionPopulateResponse",
    "CurveTypeLiteral",
    "SourceLiteral",
    "ValidationStatusLiteral",
]


# Pydantic v2 needs a tuple alias hint for the path parameter constraints
# used in ``routes/assumptions.py``; left here for clarity.
AssumptionNameField = Annotated[
    str, Field(min_length=1, max_length=128)
]

"""Pydantic request/response schemas for the ``projects`` resource (M2)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


_PILOT_CURRENCIES = {"EUR"}
_PILOT_HORIZON = 3


class ProjectBase(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=255)]
    company_name: Annotated[str | None, Field(max_length=255)] = None
    sector_pack: Annotated[str, Field(min_length=1, max_length=64)]
    perimeter: Annotated[str | None, Field(max_length=64)] = None
    currency: Annotated[str, Field(min_length=3, max_length=8)] = "EUR"
    country: Annotated[str | None, Field(max_length=64)] = None
    accounting_standard: Annotated[str, Field(min_length=1, max_length=16)] = "IFRS"
    horizon_years: Annotated[int, Field(ge=1, le=10)] = _PILOT_HORIZON
    tier_level: Annotated[str | None, Field(max_length=32)] = None
    etr_default: Annotated[float | None, Field(ge=0, le=1)] = None


class ProjectCreate(ProjectBase):
    """Body for ``POST /api/projects``.

    Pilot-time invariants (BUILD_PLAN M2 acceptance): currency forced to
    EUR, horizon_years forced to 3. Other values are rejected with 422.
    """

    @classmethod
    def __get_validators__(cls):  # pragma: no cover - pydantic v2 path
        yield from super().__get_validators__()

    def model_post_init(self, __context) -> None:  # type: ignore[override]
        if self.currency not in _PILOT_CURRENCIES:
            raise ValueError(
                f"currency must be one of {sorted(_PILOT_CURRENCIES)} in pilot v1.1"
            )
        if self.horizon_years != _PILOT_HORIZON:
            raise ValueError(
                f"horizon_years is fixed to {_PILOT_HORIZON} in pilot v1.1"
            )


class ProjectUpdate(BaseModel):
    """Body for ``PATCH /api/projects/{id}``.

    Currency, horizon_years and the immutable audit columns
    (id/created_at/updated_at/deleted_at) cannot be changed via PATCH.
    """

    name: Annotated[str | None, Field(min_length=1, max_length=255)] = None
    company_name: Annotated[str | None, Field(max_length=255)] = None
    sector_pack: Annotated[str | None, Field(min_length=1, max_length=64)] = None
    perimeter: Annotated[str | None, Field(max_length=64)] = None
    country: Annotated[str | None, Field(max_length=64)] = None
    accounting_standard: Annotated[str | None, Field(min_length=1, max_length=16)] = None
    tier_level: Annotated[str | None, Field(max_length=32)] = None
    etr_default: Annotated[float | None, Field(ge=0, le=1)] = None


class ProjectResponse(ProjectBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


class ProjectList(BaseModel):
    count: int
    items: list[ProjectResponse]


__all__ = [
    "ProjectCreate",
    "ProjectList",
    "ProjectResponse",
    "ProjectUpdate",
]

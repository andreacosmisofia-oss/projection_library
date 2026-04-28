"""Pydantic schemas for the M7 driver-intake endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class DriverRequirementEntry(BaseModel):
    """One row of the ``GET /drivers/required`` response.

    Mirrors the contract documented in ``flows/05_driver_intake.md``
    section 1, plus a ``current_status`` derived from the DB:

    * ``missing``  — no row in ``drivers`` for this id
    * ``partial``  — at least one expected datapoint is null/absent
    * ``complete`` — every expected datapoint is populated
    * ``skipped``  — user explicitly skipped the driver
    """

    driver_id: str
    type: str
    required_by_methods: list[str]
    required_for_voices: list[str]
    years_required: list[str]
    unit: str | None = None
    current_status: str
    values: dict[str, float | None] | None = None
    static_parameters: dict | None = None
    uploaded_at: datetime | None = None
    updated_at: datetime | None = None


class DriverRequirementsSummary(BaseModel):
    total: int
    complete: int
    partial: int
    missing: int
    skipped: int


class DriverRequirementsList(BaseModel):
    project_id: str
    count: int
    summary: DriverRequirementsSummary
    items: list[DriverRequirementEntry]


class DriverUpload(BaseModel):
    """Body for ``POST /api/projects/{id}/drivers/upload``.

    JSON-only in pilot M7 v1: the multipart Excel template path is
    deferred to M7.b. ``values`` is for ``scalar_per_year`` drivers,
    ``static_parameters`` for the term-loan-style blob; the handler
    enforces the correct shape against the type advertised by the
    requirements list.
    """

    model_config = ConfigDict(extra="forbid")

    driver_id: Annotated[str, Field(min_length=1, max_length=160)]
    values: dict[str, float | None] | None = None
    static_parameters: dict | None = None
    unit: Annotated[str | None, Field(default=None, max_length=32)] = None


__all__ = [
    "DriverRequirementEntry",
    "DriverRequirementsList",
    "DriverRequirementsSummary",
    "DriverUpload",
]

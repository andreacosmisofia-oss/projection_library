"""Pydantic schemas for the M3 balance intake flow.

Mirrors the response shape documented in
``flows/01_data_intake.md`` and the JSON Schema in
``data_contracts/balance_input.schema.json``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


SourceType = Literal["gestionale", "civilistico", "both"]
Severity = Literal["block", "error", "warning", "info"]
YearKey = Literal["Y-3", "Y-2", "Y-1", "Y0"]


class BalanceValidationItem(BaseModel):
    """One issue produced by parser post-checks (BC_001..BC_005)."""

    code: str
    severity: Severity
    message: str
    context: dict[str, object] = Field(default_factory=dict)


class BalanceValidationReport(BaseModel):
    errors: list[BalanceValidationItem] = Field(default_factory=list)
    warnings: list[BalanceValidationItem] = Field(default_factory=list)
    info: list[BalanceValidationItem] = Field(default_factory=list)


class ParsedVoice(BaseModel):
    user_label: str
    user_section: str | None = None
    values: dict[str, float | None]


class ParsedBalance(BaseModel):
    """Output of ``parse_balance``: pure data, no DB ids yet."""

    source_type: SourceType
    raw_filename: str
    years_present: list[str]
    voice_count: int
    voices: list[ParsedVoice]
    validation: BalanceValidationReport


class BalanceUploadResponse(BaseModel):
    """API response for ``POST /api/projects/{id}/balance/upload``."""

    balance_id: str
    source_type: SourceType
    raw_filename: str
    years_present: list[str]
    voice_count: int
    uploaded_at: datetime
    voices: list[ParsedVoice]
    validation: BalanceValidationReport


class BalanceLflPatch(BaseModel):
    year: YearKey
    lfl: bool


class BalanceLflResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    balance_id: str
    year: str
    lfl: bool
    rows_updated: int


class BalanceErrorResponse(BaseModel):
    """Body returned with HTTP 422 when parsing or post-checks block."""

    detail: str
    validation: BalanceValidationReport


__all__ = [
    "BalanceErrorResponse",
    "BalanceLflPatch",
    "BalanceLflResponse",
    "BalanceUploadResponse",
    "BalanceValidationItem",
    "BalanceValidationReport",
    "ParsedBalance",
    "ParsedVoice",
    "SourceType",
    "YearKey",
]

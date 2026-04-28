"""Pydantic schemas for the M5 historical validation endpoint."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


Severity = Literal["block", "error", "warning", "info"]


class ValidationIssueDTO(BaseModel):
    rule_id: str
    severity: Severity
    voice_id: str | None = None
    year: str | None = None
    message: str
    context: dict = Field(default_factory=dict)


class ValidationSummary(BaseModel):
    block: int = 0
    error: int = 0
    warning: int = 0
    info: int = 0


class ValidationReportResponse(BaseModel):
    project_id: str
    phase: Literal["historical"] = "historical"
    summary: ValidationSummary
    issues: list[ValidationIssueDTO]
    can_proceed: bool
    computed_at: datetime


__all__ = [
    "Severity",
    "ValidationIssueDTO",
    "ValidationReportResponse",
    "ValidationSummary",
]

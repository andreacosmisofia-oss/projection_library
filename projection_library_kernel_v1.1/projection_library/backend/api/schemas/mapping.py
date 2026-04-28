"""Pydantic schemas for the M4 mapping endpoints.

Mirrors the contract documented in ``flows/02_mapping.md`` §API. The
suggest endpoint returns candidates + stats + sign-flip hints; the
confirm endpoint accepts a flat list of confirmed/skipped lines plus
the user's sign-flip decision.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


CandidateReason = Literal[
    "company_history",
    "synonym_match",
    "label_exact",
    "fuzzy",
]


class MappingCandidate(BaseModel):
    voice_id: str
    confidence: float = Field(ge=0.0, le=1.0)
    reason: CandidateReason


class MappingSuggestion(BaseModel):
    user_label: str
    user_section: str | None = None
    candidates: list[MappingCandidate] = Field(default_factory=list)


class MappingStats(BaseModel):
    total_voices: int
    high_confidence: int
    medium_confidence: int
    low_confidence: int
    no_match: int


class MappingSuggestResponse(BaseModel):
    """Body returned by ``POST /api/projects/{id}/mapping/suggest``."""

    suggestions: list[MappingSuggestion]
    stats: MappingStats
    sign_flip_detected: bool = False
    suggested_flip: bool = False


class MappingConfirmItem(BaseModel):
    user_label: str
    user_section: str | None = None
    voice_id_system: str | None = None
    skipped: bool = False
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    auto_suggested: bool = False

    @field_validator("voice_id_system")
    @classmethod
    def _voice_or_skip(cls, v: str | None) -> str | None:
        # A row must either map to a voice OR be marked skipped.
        # The cross-field check happens at the request level; this
        # validator only normalises empty strings to None.
        if v is None:
            return None
        v = v.strip()
        return v or None


class MappingConfirmRequest(BaseModel):
    """Body for ``PUT /api/projects/{id}/mapping``."""

    mappings: list[MappingConfirmItem]
    sign_flip_applied: bool = False


class MappingValidationIssue(BaseModel):
    code: str
    severity: Literal["block", "error", "warning", "info"]
    message: str


class MappingConfirmResponse(BaseModel):
    saved: int
    validation_issues: list[MappingValidationIssue] = Field(default_factory=list)
    ready_for_validation: bool


class MappingItem(BaseModel):
    """One row as stored in the ``mappings`` table."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    voice_user_label: str
    voice_user_section: str | None = None
    voice_id_system: str | None = None
    confidence: float | None = None
    auto_suggested: bool
    confirmed_by_user: bool
    skipped: bool
    sign_flip_applied: bool
    created_at: datetime
    updated_at: datetime


class MappingListResponse(BaseModel):
    count: int
    items: list[MappingItem]


__all__ = [
    "CandidateReason",
    "MappingCandidate",
    "MappingConfirmItem",
    "MappingConfirmRequest",
    "MappingConfirmResponse",
    "MappingItem",
    "MappingListResponse",
    "MappingStats",
    "MappingSuggestResponse",
    "MappingSuggestion",
    "MappingValidationIssue",
]

"""Pydantic schemas for the M6 method-selection endpoints (Expert)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class MethodConfigEntry(BaseModel):
    """One row of the merged registry × DB view exposed by GET.

    ``method_id`` is ``None`` for voices whose registry default is the
    ``(utente sceglie)`` sentinel and which the user has not yet
    configured. ``configured_at`` is ``None`` for rows that exist only
    as in-memory defaults (no DB row yet).
    """

    model_config = ConfigDict(from_attributes=True)

    voice_id: str
    voice_statement: str | None = None
    voice_section: str | None = None
    method_id: str | None = None
    method_technical_code: str | None = None
    is_default: bool
    source: str
    requires_user_choice: bool = False
    configured_at: datetime | None = None


class MethodConfigSummary(BaseModel):
    total: int
    registry_default: int
    user_override: int
    sector_pack: int
    user_choice_required: int


class MethodConfigList(BaseModel):
    project_id: str
    count: int
    summary: MethodConfigSummary
    items: list[MethodConfigEntry]


class MethodUpdate(BaseModel):
    """Body for ``PUT /api/projects/{id}/methods/{voice_id}``."""

    method_id: Annotated[str, Field(min_length=1, max_length=64)]


__all__ = [
    "MethodConfigEntry",
    "MethodConfigList",
    "MethodConfigSummary",
    "MethodUpdate",
]

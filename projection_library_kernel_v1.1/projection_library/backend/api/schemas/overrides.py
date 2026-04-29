"""Pydantic schemas for the ``overrides`` resource (M11).

Three response shapes:

* :class:`OverrideCreate` — body of ``POST``; ``override_policy_class``
  is resolved server-side and persisted on the row.
* :class:`OverrideUpdate` — body of ``PATCH``; only ``is_active`` is
  editable in pilot v1.1 (the spec explicitly avoids mutable
  ``delta_amount`` to keep the audit trail unambiguous).
* :class:`OverrideResponse` — the full row, returned by every
  endpoint and wrapped by :class:`OverrideList`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class OverrideCreate(BaseModel):
    """Body of ``POST /api/projects/{id}/overrides``."""

    voice_id: Annotated[str, Field(min_length=1, max_length=128)]
    year: Annotated[str, Field(min_length=1, max_length=8)]
    delta_amount: float
    nature: Annotated[str, Field(min_length=1, max_length=16)]
    user_note: Annotated[str | None, Field(max_length=1024)] = None


class OverrideUpdate(BaseModel):
    """Body of ``PATCH /api/projects/{id}/overrides/{oid}``."""

    is_active: bool


class OverrideResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    voice_id: str
    year: str
    delta_amount: float
    nature: str
    override_policy_class: str
    is_active: bool
    user_note: str | None = None
    created_at: datetime
    deactivated_at: datetime | None = None


class OverrideList(BaseModel):
    project_id: str
    count: int
    items: list[OverrideResponse]


__all__ = [
    "OverrideCreate",
    "OverrideList",
    "OverrideResponse",
    "OverrideUpdate",
]

"""Pydantic schemas for the M5 quality score endpoint."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class QualityScoreResponse(BaseModel):
    project_id: str
    score_total: float
    score_history: float
    score_completeness: float
    score_consistency: float
    score_method_calibration: float | None = None
    classification: str
    weights: dict[str, float] = Field(default_factory=dict)
    components_detail: dict = Field(default_factory=dict)
    computed_at: datetime


__all__ = ["QualityScoreResponse"]

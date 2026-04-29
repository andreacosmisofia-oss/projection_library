"""Pydantic request/response schemas for the M10 snapshot resource.

Three response shapes:

* :class:`SnapshotSummary` — header only, used by ``POST /run`` and the
  list endpoint. Excludes the ``values`` array so the list payload
  stays small even when the dashboard pages backwards through history.
* :class:`SnapshotDetail` — header + normalised values, used by
  ``GET /snapshot/latest``.
* :class:`SnapshotList` — pagination wrapper around summaries.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SnapshotValueOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    voice_id: str
    year: str
    value: float | None
    base_value: float | None
    override_delta: float


class SnapshotSummary(BaseModel):
    """Snapshot header — no ``values`` array."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    run_timestamp: datetime
    status: str
    duration_ms: int
    error_message: str | None = None
    validation_summary: dict
    approximation_log: list
    created_at: datetime


class SnapshotDetail(SnapshotSummary):
    """Snapshot header + full payload for the dashboard initial load."""

    validation_issues: list
    pl_data: dict
    sp_data: dict
    cf_data: dict
    projected_kpis: dict
    values: list[SnapshotValueOut]


class SnapshotList(BaseModel):
    project_id: str
    count: int
    items: list[SnapshotSummary]


class LatestValidationReport(BaseModel):
    """Engine-stage validation issues attached to the most recent snapshot.

    Distinct from M5's ``GET /validation-report/historical`` which
    returns the *intake-time* validator output. This view exposes
    ``state.validation_issues`` accumulated during the engine run
    (E0..E8) and is what M12 wants displayed in the dashboard panel.
    """

    project_id: str
    snapshot_id: str
    run_timestamp: datetime
    status: str
    summary: dict
    issues: list


class ApproximationLogResponse(BaseModel):
    project_id: str
    snapshot_id: str
    run_timestamp: datetime
    approximation_log: list


__all__ = [
    "ApproximationLogResponse",
    "LatestValidationReport",
    "SnapshotDetail",
    "SnapshotList",
    "SnapshotSummary",
    "SnapshotValueOut",
]

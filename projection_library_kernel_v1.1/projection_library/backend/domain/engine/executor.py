"""Engine entry point: orchestrate E0 setup + year loop over E1..E8.

Implements the orchestration described in flows/07_engine_execution.md
§"Year loop". The executor is intentionally thin: each phase is a pure
``(state) -> state`` function imported from ``phases/``. M9.0 wires the
framework with stubs; M9.1-M9.11 fills in phase logic.

Lifetime invariants (ARCHITECTURE.md §"Engine execution"):
* Phases never mutate the DB — only the API caller persists snapshots.
* The year loop is sequential: Y1 finishes before Y2 starts.
* ``state.base_values`` carries pure engine output; overrides live in
  ``state.overrides`` and are composed on read by ``resolve_voice_value``.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy.orm import Session

from backend.domain.engine.phases import (
    phase_e0_setup,
    phase_e1,
    phase_e2,
    phase_e3,
    phase_e3_1,
    phase_e4,
    phase_e5,
    phase_e6,
    phase_e7,
    phase_e7_5,
    phase_e8,
)
from backend.domain.engine.value_resolver import ModelState
from backend.infrastructure.db.models import Project
from backend.infrastructure.db.repositories.drivers_repo import list_drivers
from backend.infrastructure.db.repositories.m5_repos import list_historical_kpis
from backend.infrastructure.db.repositories.method_configs_repo import (
    list_method_configs,
)

logger = logging.getLogger(__name__)


PROJECTION_YEARS: tuple[str, ...] = ("Y1", "Y2", "Y3")

# (phase_id, callable). Driving the year loop from a list keeps the
# executor body trivial and lets tests swap individual phases via
# monkeypatching the module attribute.
PHASE_SEQUENCE: list[tuple[str, Callable[[ModelState], ModelState]]] = [
    ("E1", phase_e1),
    ("E2", phase_e2),
    ("E3", phase_e3),
    ("E3.1", phase_e3_1),
    ("E4", phase_e4),
    ("E5", phase_e5),
    ("E6", phase_e6),
    ("E7", phase_e7),
    ("E7.5", phase_e7_5),
    ("E8", phase_e8),
]


class ProjectNotReady(Exception):
    """Pre-conditions for engine run not satisfied (Flow 07 §Pre-condizioni)."""


@dataclass
class ProjectionResult:
    """Engine output. M9.0 returns an empty snapshot; M9.1+ populates it."""

    project_id: str
    run_timestamp: datetime
    status: str  # "success" | "error"
    duration_ms: int
    pl_data: dict[str, Any] = field(default_factory=dict)
    sp_data: dict[str, Any] = field(default_factory=dict)
    cf_data: dict[str, Any] = field(default_factory=dict)
    projected_kpis: dict[str, Any] = field(default_factory=dict)
    validation_report: dict[str, Any] = field(default_factory=dict)
    approximation_log: list[Any] = field(default_factory=list)
    overrides_applied: list[Any] = field(default_factory=list)


def build_initial_state(
    project_id: str, db: Session, registries: Any
) -> ModelState:
    """Hydrate a :class:`ModelState` from DB + registries.

    Reads what's already persisted by M2-M7:
    * Project row (raises ``ProjectNotReady`` if missing).
    * Historical KPIs from ``historical_kpis`` (skipping ``AGG`` rows
      and ``not_computable`` entries).
    * Drivers from ``drivers`` (skip markers excluded; per-type payload
      flattened into a single ``dict[year_or_param, value]``).
    * Method configs from ``method_configs`` keyed by ``voice_id``.

    ``assumptions`` is intentionally empty: M8 (assumption compilation)
    has not shipped yet, so there's no DB table to read from. The slot
    exists on ``ModelState`` so M9.x phases can be wired ahead of M8.
    """
    project = db.get(Project, project_id)
    if project is None:
        raise ProjectNotReady(f"Project {project_id} not found")

    historical_data: dict[str, dict[str, float]] = {}
    for row in list_historical_kpis(db, project_id):
        if row.year == "AGG" or row.value is None:
            continue
        historical_data.setdefault(row.kpi_id, {})[row.year] = row.value

    drivers: dict[str, dict[str, Any]] = {}
    for row in list_drivers(db, project_id):
        if row.skipped:
            continue
        bucket = drivers.setdefault(row.driver_id, {})
        if row.type == "scalar_per_year" and row.year:
            bucket[row.year] = row.value
        elif row.type == "static_parameters":
            bucket["static_parameters"] = row.static_parameters
        elif row.type == "time_series":
            bucket["time_series"] = row.time_series
        elif row.type == "aging_bucket":
            bucket["aging_buckets"] = row.aging_buckets

    method_configs = {
        row.voice_id: row for row in list_method_configs(db, project_id)
    }

    return ModelState(
        project=project,
        registries=registries,
        historical_data=historical_data,
        drivers=drivers,
        assumptions={},
        method_configs=method_configs,
        base_values={},
        overrides=[],
        current_year="",
        current_phase="",
        validation_issues=[],
        approximation_log=[],
    )


def run_engine(
    project_id: str, db: Session, registries: Any
) -> ProjectionResult:
    """Run E0 + year loop over E1..E8 for Y1, Y2, Y3.

    Returns a :class:`ProjectionResult` with ``status="success"`` when
    the loop completes. Persistence is the caller's responsibility:
    the executor is pure orchestration over ``ModelState``.
    """
    started_at = datetime.now(timezone.utc)
    t0 = time.perf_counter()

    state = build_initial_state(project_id, db, registries)

    state.current_phase = "E0"
    state = phase_e0_setup(state)

    for year in PROJECTION_YEARS:
        state.current_year = year
        for phase_id, phase_fn in PHASE_SEQUENCE:
            state.current_phase = phase_id
            state = phase_fn(state)

    duration_ms = int((time.perf_counter() - t0) * 1000)
    logger.info(
        "engine run complete project=%s duration_ms=%d", project_id, duration_ms
    )

    return ProjectionResult(
        project_id=project_id,
        run_timestamp=started_at,
        status="success",
        duration_ms=duration_ms,
    )


__all__ = [
    "PHASE_SEQUENCE",
    "PROJECTION_YEARS",
    "ProjectNotReady",
    "ProjectionResult",
    "build_initial_state",
    "run_engine",
]

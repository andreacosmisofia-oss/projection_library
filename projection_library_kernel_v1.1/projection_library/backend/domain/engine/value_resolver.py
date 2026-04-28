"""ModelState + resolve_voice_value: single source of truth for voice values.

Implements the override-as-overlay pattern described in ARCHITECTURE.md
section "Override layer pattern". The engine writes pure ``base_value``
into ``state.base_values``; overrides live separately and are composed
on read via ``resolve_voice_value``. Every call site that reads a voice
value (formulas, derived rules, validation, CF identity, output) must
go through this function — otherwise the overlay is bypassed.

Year semantics:
* Historical years (``Y-3`` .. ``Y0``): values come from
  ``state.historical_data`` (uploaded actuals). Overrides do not apply.
* Projection years (``Y1``, ``Y2``, ``Y3``): values come from
  ``state.base_values`` (engine output) + active overrides as overlay.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


_YEAR_RE = re.compile(r"^Y(-?\d+)$")


@dataclass
class Override:
    voice_id: str
    year: str
    delta_amount: float
    is_active: bool = True
    nature: str = "organic"  # "organic" | "one_shot"


@dataclass
class ValidationIssue:
    """Lightweight engine-side validation issue.

    Distinct from ``HistoricalValidationIssue`` (M5 intake validator)
    because the engine produces issues in-memory during a run, without
    persisting them as a standalone report — they ride alongside the
    snapshot via ``ProjectionResult.validation_report``.
    """

    rule_id: str
    severity: str  # "block" | "error" | "warning" | "info"
    message: str
    voice_id: str | None = None
    year: str | None = None
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class ModelState:
    project: Any = None
    registries: Any = None

    # voice_id -> year -> value (historical actuals, from intake).
    historical_data: dict[str, dict[str, float]] = field(default_factory=dict)
    # kpi_id -> year -> value (computed by M5 KPI calculator).
    historical_kpis: dict[str, dict[str, float]] = field(default_factory=dict)

    drivers: dict[str, dict[str, Any]] = field(default_factory=dict)
    assumptions: dict[str, dict[str, dict[str, float]]] = field(default_factory=dict)
    method_configs: dict[str, Any] = field(default_factory=dict)

    base_values: dict[str, dict[str, float]] = field(default_factory=dict)
    overrides: list[Override] = field(default_factory=list)

    current_year: str = ""
    current_phase: str = ""

    # E0 outputs.
    historical_years: list[str] = field(default_factory=list)
    lfl_years: list[str] = field(default_factory=list)
    active_sector_pack: str | None = None

    validation_issues: list[ValidationIssue] = field(default_factory=list)
    approximation_log: list[Any] = field(default_factory=list)


def _year_index(year: str) -> int | None:
    """Return the integer offset of a ``Y<n>`` label, or ``None``."""
    match = _YEAR_RE.match(year)
    return int(match.group(1)) if match else None


def get_prev_year(year: str) -> str:
    """Return the previous year label.

    ``Y1`` → ``Y0``, ``Y2`` → ``Y1``, ``Y3`` → ``Y2``,
    ``Y0`` → ``Y-1``, ``Y-1`` → ``Y-2``. Unparseable input returns ``""``.
    """
    idx = _year_index(year)
    if idx is None:
        return ""
    return f"Y{idx - 1}"


def resolve_historical(voice_id: str, year: str, state: ModelState) -> float:
    """Read a historical voice actual; return 0.0 when missing."""
    return state.historical_data.get(voice_id, {}).get(year, 0.0)


def resolve_voice_value(voice_id: str, year: str, state: ModelState) -> float:
    """Return the effective value of ``voice_id`` for ``year``.

    Historical years (``Y-3``..``Y0``) read from ``historical_data``;
    overrides do not apply. Projection years (``Y1``..``Y3``) compose
    ``base_values`` with the sum of active override deltas. Unknown
    year labels fall through to the projection branch and return 0.0
    when the voice has no base value either.
    """
    idx = _year_index(year)
    if idx is not None and idx <= 0:
        return resolve_historical(voice_id, year, state)
    base = state.base_values.get(voice_id, {}).get(year, 0.0)
    delta = sum(
        ov.delta_amount
        for ov in state.overrides
        if ov.voice_id == voice_id and ov.year == year and ov.is_active
    )
    return base + delta


__all__ = [
    "ModelState",
    "Override",
    "ValidationIssue",
    "get_prev_year",
    "resolve_historical",
    "resolve_voice_value",
]

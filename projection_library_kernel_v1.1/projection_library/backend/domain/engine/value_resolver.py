"""ModelState + resolve_voice_value: single source of truth for voice values.

Implements the override-as-overlay pattern described in ARCHITECTURE.md
section "Override layer pattern". The engine writes pure ``base_value``
into ``state.base_values``; overrides live separately and are composed
on read via ``resolve_voice_value``. Every call site that reads a voice
value (formulas, derived rules, validation, CF identity, output) must
go through this function — otherwise the overlay is bypassed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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


def resolve_voice_value(voice_id: str, year: str, state: ModelState) -> float:
    """Return effective value = base_value + sum(active override deltas).

    Falls back to 0.0 when the voice has no base_value for that year
    (skipped voice, not yet computed, or referenced before configuration).
    """
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
    "resolve_voice_value",
]

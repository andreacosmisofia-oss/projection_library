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
class ModelState:
    project: Any = None
    registries: Any = None

    historical_data: dict[str, dict[str, float]] = field(default_factory=dict)
    drivers: dict[str, dict[str, float]] = field(default_factory=dict)
    assumptions: dict[str, dict[str, dict[str, float]]] = field(default_factory=dict)
    method_configs: dict[str, Any] = field(default_factory=dict)

    base_values: dict[str, dict[str, float]] = field(default_factory=dict)
    overrides: list[Override] = field(default_factory=list)

    current_year: str = ""
    current_phase: str = ""

    validation_issues: list[Any] = field(default_factory=list)
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


__all__ = ["ModelState", "Override", "resolve_voice_value"]

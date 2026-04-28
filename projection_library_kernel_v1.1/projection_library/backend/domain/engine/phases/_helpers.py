"""Cross-phase helpers for the engine year loop.

The helpers live here rather than in individual phase modules so that
phases that share logic (E1's method dispatch, E2/E3/E4's roll-forwards)
import from a single place.
"""

from __future__ import annotations

from typing import Any

from backend.domain.engine import formulas
from backend.domain.engine.value_resolver import (
    ModelState,
    get_prev_year,
    resolve_voice_value,
)


def roll_forward(
    voice_id: str,
    year: str,
    state: ModelState,
    additions_voice: str,
    disposals_voice: str,
) -> float:
    """Single-flow roll-forward: ``open + additions - abs(disposals)``.

    ``open`` is read from ``voice_id`` itself at ``prev_year`` (the
    rolling-balance pattern: this year's close becomes next year's
    open without a separate "open" voice). ``additions_voice`` and
    ``disposals_voice`` are read at ``year`` from ``base_values`` (or
    ``historical_data`` if the year is historical) via the standard
    ``resolve_voice_value`` dispatch.

    Disposals are taken in absolute value so the helper is robust to
    the sign convention chosen by the caller (some registries store
    disposals as negative numbers, others as positive).
    """
    prev = get_prev_year(year)
    open_value = resolve_voice_value(voice_id, prev, state)
    additions = resolve_voice_value(additions_voice, year, state)
    disposals = resolve_voice_value(disposals_voice, year, state)
    return open_value + additions - abs(disposals)


def dispatch_method(
    voice_id: str, year: str, state: ModelState
) -> float | None:
    """Resolve method (config or default) and evaluate ``formula_python``.

    Returns ``None`` when the voice has no configured method and no
    registry default, or when the resolved method has no
    ``formula_python`` (treated as "skip silently"). Lookups try
    ``method_registry.methods`` first, then ``derived_rules`` so
    aggregate voices that point at e.g. ``subtotal_aggregation`` flow
    through the same path.
    """
    if state.registries is None:
        return None
    voices = getattr(state.registries, "voices", None) or {}
    methods = getattr(state.registries, "methods", None) or {}
    derived_rules = getattr(state.registries, "derived_rules", None) or {}

    method_id = _resolve_method_id(voice_id, state, voices)
    if not method_id:
        return None

    formula = _resolve_formula_python(method_id, methods, derived_rules)
    if not formula:
        return None

    return formulas.evaluate(formula, voice_id, year, state)


def _resolve_method_id(
    voice_id: str,
    state: ModelState,
    voices_registry: dict[str, dict[str, Any]],
) -> str | None:
    cfg = state.method_configs.get(voice_id)
    if cfg is not None:
        method_id = getattr(cfg, "method_id", None)
        if method_id:
            return method_id
    voice_meta = voices_registry.get(voice_id) or {}
    return voice_meta.get("default_method")


def _resolve_formula_python(
    method_id: str,
    methods: dict[str, dict[str, Any]],
    derived_rules: dict[str, dict[str, Any]],
) -> str | None:
    spec = methods.get(method_id) or derived_rules.get(method_id)
    if spec is None:
        return None
    return spec.get("formula_python")


__all__ = ["dispatch_method", "roll_forward"]

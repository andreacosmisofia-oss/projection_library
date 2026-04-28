"""E1 — P&L driver core.

Implements the base phase pattern from flows/07_engine_execution.md §"Phase
pattern" for the ~50 P&L driver voices that carry ``calc_phase_proxy=E1``
or ``calc_phase_final=E1`` in the voice registry.

Per-voice loop:
1. Resolve the active method id — user override from
   ``state.method_configs`` first, falling back to
   ``voice.default_method`` from the registry. Voices without either
   are skipped (not in scope, or disabled by the user).
2. Look up ``formula_python``. The default_method may point to either
   ``method_registry.methods`` (extrapolation, ratio, driver-based) or
   ``method_registry.derived_rules`` (e.g. ``subtotal_aggregation`` for
   gross_total / opex.total / pl.rev.net proxy). The registry loader
   already validates the cross-reference so the dispatch is safe.
3. Evaluate the formula in ``formulas.evaluate``'s sandboxed namespace.
   Failures degrade to 0.0 with a logged warning rather than crashing
   the year loop (Flow 07 §"Edge cases").
4. Store the result in ``state.base_values[voice_id][year]`` so
   subsequent voices in the same phase that read this voice via
   ``resolve_voice_value`` see the updated value (intra-phase ordering
   relies on the registry's YAML order — pl.rev.net is materialised
   before any cogs voice that references it).

Sign convention is applied by the formula itself (e.g. ``-abs(...)``
patterns in cogs methods), so this phase does not post-process the
returned value. Voice-level sign hints in the registry remain advisory
for now and will be enforced in a later milestone.

Derived rules with ``fase_final=E1`` would run in the per-phase derived
hook below; the current registry has none, so the hook is a no-op
placeholder kept for forward compatibility.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.domain.engine import formulas
from backend.domain.engine.value_resolver import ModelState

logger = logging.getLogger(__name__)


_PHASE_ID = "E1"


def phase_e1(state: ModelState) -> ModelState:
    year = state.current_year
    logger.info("phase E1 year=%s", year)

    if state.registries is None:
        # No registry → nothing to dispatch on. Tests that exercise the
        # year-loop framework without real metadata land here.
        return state

    voices = getattr(state.registries, "voices", None) or {}
    methods = getattr(state.registries, "methods", None) or {}
    derived_rules = getattr(state.registries, "derived_rules", None) or {}

    voice_ids = [
        vid
        for vid, meta in voices.items()
        if _is_e1_voice(meta)
    ]

    for voice_id in voice_ids:
        method_id = _resolve_method_id(voice_id, state, voices)
        if method_id is None:
            continue

        formula = _resolve_formula_python(method_id, methods, derived_rules)
        if formula is None:
            logger.warning(
                "E1: no formula_python for method %r (voice %r)",
                method_id,
                voice_id,
            )
            continue

        value = formulas.evaluate(formula, voice_id, year, state)
        state.base_values.setdefault(voice_id, {})[year] = value

    return state


def _is_e1_voice(voice_meta: dict[str, Any]) -> bool:
    return (
        voice_meta.get("calc_phase_final") == _PHASE_ID
        or voice_meta.get("calc_phase_proxy") == _PHASE_ID
    )


def _resolve_method_id(
    voice_id: str,
    state: ModelState,
    voices_registry: dict[str, dict[str, Any]],
) -> str | None:
    """User override > registry default. Returns None when neither is set."""
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
    """Look up formula_python in methods first, then derived_rules."""
    spec = methods.get(method_id) or derived_rules.get(method_id)
    if spec is None:
        return None
    return spec.get("formula_python")


__all__ = ["phase_e1"]

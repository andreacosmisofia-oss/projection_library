"""E1 — P&L driver core.

Implements the base phase pattern from flows/07_engine_execution.md §"Phase
pattern" for the ~50 P&L driver voices that carry ``calc_phase_proxy=E1``
or ``calc_phase_final=E1`` in the voice registry.

For each voice in scope the shared ``dispatch_method`` helper resolves
the active method (user override > registry default), looks up the
``formula_python`` in ``methods`` then ``derived_rules`` (so aggregates
with ``default_method=subtotal_aggregation`` go through the same
sandbox), evaluates it, and returns the float. The result is stored
in ``state.base_values[voice_id][year]`` so subsequent voices in the
same phase that read this voice via ``resolve_voice_value`` see the
updated value (intra-phase ordering relies on the registry's YAML
order — pl.rev.net is materialised before any cogs voice that
references it).

Voices without a configured or default method are skipped silently;
the same applies when a method has no ``formula_python``. Sign
convention is applied by the formula itself.

Derived rules with ``fase_final=E1`` would run in the per-phase derived
hook below; the current registry has none, so the hook is a no-op
placeholder kept for forward compatibility.
"""

from __future__ import annotations

import logging

from backend.domain.engine.phases._helpers import dispatch_method
from backend.domain.engine.value_resolver import ModelState

logger = logging.getLogger(__name__)


_PHASE_ID = "E1"


def phase_e1(state: ModelState) -> ModelState:
    year = state.current_year
    logger.info("phase E1 year=%s", year)

    if state.registries is None:
        return state

    voices = getattr(state.registries, "voices", None) or {}
    voice_ids = [vid for vid, meta in voices.items() if _is_e1_voice(meta)]

    for voice_id in voice_ids:
        value = dispatch_method(voice_id, year, state)
        if value is None:
            continue
        state.base_values.setdefault(voice_id, {})[year] = value

    return state


def _is_e1_voice(voice_meta: dict) -> bool:
    return (
        voice_meta.get("calc_phase_final") == _PHASE_ID
        or voice_meta.get("calc_phase_proxy") == _PHASE_ID
    )


__all__ = ["phase_e1"]

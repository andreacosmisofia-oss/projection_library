"""E3.1 — IFRS 15 adjustments (stub).

3 voci: pl.rev.adjustments.deferred_movement,
pl.rev.adjustments.contract_asset_movement, pl.rev.adjustments_total.
See flows/07_engine_execution.md §E3.1. Logic lands in M9.5.
"""

from __future__ import annotations

import logging

from backend.domain.engine.value_resolver import ModelState

logger = logging.getLogger(__name__)


def phase_e3_1(state: ModelState) -> ModelState:
    logger.info("phase E3.1 year=%s", state.current_year)
    return state


__all__ = ["phase_e3_1"]

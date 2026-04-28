"""E1 — P&L driver core (stub).

~50 voci P&L (rev/cogs/opex/provisions/financial.fx_gain_loss/equity_method).
See flows/07_engine_execution.md §E1. Logic lands in M9.2.
"""

from __future__ import annotations

import logging

from backend.domain.engine.value_resolver import ModelState

logger = logging.getLogger(__name__)


def phase_e1(state: ModelState) -> ModelState:
    logger.info("phase E1 stub year=%s", state.current_year)
    return state


__all__ = ["phase_e1"]

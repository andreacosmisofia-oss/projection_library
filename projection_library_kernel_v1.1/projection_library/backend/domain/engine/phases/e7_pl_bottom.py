"""E7 — P&L bottom + tax current + retained earnings (stub).

~13 voci pl.ebit/ebt/tax/net_income + pl.ebitda_adjusted/ebit_adjusted +
bs.equity.retained_earnings.close + bs.tax.nol_carryforward.close.
See flows/07_engine_execution.md §E7. Logic lands in M9.9.
"""

from __future__ import annotations

import logging

from backend.domain.engine.value_resolver import ModelState

logger = logging.getLogger(__name__)


def phase_e7(state: ModelState) -> ModelState:
    logger.info("phase E7 stub year=%s", state.current_year)
    return state


__all__ = ["phase_e7"]

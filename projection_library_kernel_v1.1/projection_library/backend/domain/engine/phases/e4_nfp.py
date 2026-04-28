"""E4 — NFP + financial expenses (stub).

~15 voci bs.nfp.borrowings.* + bs.nfp.lease_liability.* + pl.financial.interest_*.
See flows/07_engine_execution.md §E4. Logic lands in M9.6.
"""

from __future__ import annotations

import logging

from backend.domain.engine.value_resolver import ModelState

logger = logging.getLogger(__name__)


def phase_e4(state: ModelState) -> ModelState:
    logger.info("phase E4 year=%s", state.current_year)
    return state


__all__ = ["phase_e4"]

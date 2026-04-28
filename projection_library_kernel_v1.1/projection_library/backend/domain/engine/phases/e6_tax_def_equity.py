"""E6 — Tax differita + Equity driver (stub).

~13 voci bs.tax.dta_*/dtl_* + bs.equity.capital.* + bs.equity.oci_* + bs.equity.nci.close.
See flows/07_engine_execution.md §E6. Logic lands in M9.8.
"""

from __future__ import annotations

import logging

from backend.domain.engine.value_resolver import ModelState

logger = logging.getLogger(__name__)


def phase_e6(state: ModelState) -> ModelState:
    logger.info("phase E6 year=%s", state.current_year)
    return state


__all__ = ["phase_e6"]

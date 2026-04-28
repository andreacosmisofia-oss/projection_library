"""E2 — Fixed assets + D&A + impairment + IP fv (stub).

~39 voci bs.fa.* + pl.da.* + pl.impairment.* + pl.other.fair_value_*.
See flows/07_engine_execution.md §E2. Logic lands in M9.3.
"""

from __future__ import annotations

import logging

from backend.domain.engine.value_resolver import ModelState

logger = logging.getLogger(__name__)


def phase_e2(state: ModelState) -> ModelState:
    logger.info("phase E2 stub year=%s", state.current_year)
    return state


__all__ = ["phase_e2"]

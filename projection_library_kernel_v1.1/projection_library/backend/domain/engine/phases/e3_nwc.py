"""E3 — NWC + ricalcolo COGS esatto (stub).

~25 voci bs.nwc.* + pl.cogs.inventory_writeoff/wip_capitalization/total.final.
See flows/07_engine_execution.md §E3. Logic lands in M9.4.
"""

from __future__ import annotations

import logging

from backend.domain.engine.value_resolver import ModelState

logger = logging.getLogger(__name__)


def phase_e3(state: ModelState) -> ModelState:
    logger.info("phase E3 year=%s", state.current_year)
    return state


__all__ = ["phase_e3"]

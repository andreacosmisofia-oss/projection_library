"""E8 — CF + cash close + balance check (stub).

~38 voci cf.* + bs.nfp.cash + bs.nfp.net_debt + bs.total_assets +
bs.total_liabilities_equity + bs.balance_check.
See flows/07_engine_execution.md §E8. Logic lands in M9.11.
"""

from __future__ import annotations

import logging

from backend.domain.engine.value_resolver import ModelState

logger = logging.getLogger(__name__)


def phase_e8(state: ModelState) -> ModelState:
    logger.info("phase E8 stub year=%s", state.current_year)
    return state


__all__ = ["phase_e8"]

"""E5 — Provisions + Employee benefits (stub).

~14 voci bs.provisions.* + bs.employee_benefits.*.
See flows/07_engine_execution.md §E5. Logic lands in M9.7.
"""

from __future__ import annotations

import logging

from backend.domain.engine.value_resolver import ModelState

logger = logging.getLogger(__name__)


def phase_e5(state: ModelState) -> ModelState:
    logger.info("phase E5 stub year=%s", state.current_year)
    return state


__all__ = ["phase_e5"]

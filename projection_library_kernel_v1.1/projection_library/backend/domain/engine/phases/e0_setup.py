"""E0 — Setup (stub).

Pre-loop setup: KPI storici, sector pack apply, validazioni hard-blocking
DI_001-014. See flows/07_engine_execution.md §E0. Logic lands in M9.1.
"""

from __future__ import annotations

import logging

from backend.domain.engine.value_resolver import ModelState

logger = logging.getLogger(__name__)


def phase_e0_setup(state: ModelState) -> ModelState:
    logger.info("phase E0 stub year=%s", state.current_year)
    return state


__all__ = ["phase_e0_setup"]

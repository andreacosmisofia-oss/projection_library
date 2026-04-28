"""E0 — Setup (pre-loop, una sola volta).

Three responsibilities (Flow 07 §E0):

1. Hard-blocking validation pre-run. Y0 actuals must exist for the
   critical voice groups (revenue, cash, equity) and the project must
   carry at least one method configuration. Failures are appended to
   ``state.validation_issues`` with severity ``"block"``; the executor
   inspects them right after E0 and raises ``ProjectNotReady`` if any
   are present, so subsequent year-loop phases never see a half-set
   model.

2. Apply ``sector_pack``. Look up ``project.sector_pack`` in
   ``registries.sector_packs``, log the ``method_overrides_examples``
   carried by the pack (the machine-readable normalisation of those
   overrides is deferred), and stash the pack id in
   ``state.active_sector_pack`` so downstream phases can reference it.

3. Mark historical years. Walk ``state.historical_data`` and collect
   every year that has at least one non-null voice value into
   ``state.historical_years`` (chronologically ordered).
   ``state.lfl_years`` is already populated by ``build_initial_state``
   from ``MappedValues.years_lfl`` (i.e. ``raw_voices.lfl_flag``);
   this step is a no-op for that field but is part of E0's contract.
"""

from __future__ import annotations

import logging
from typing import Iterable

from backend.domain.engine.value_resolver import ModelState, ValidationIssue

logger = logging.getLogger(__name__)


# Y0 critical voice prefixes — at least one voice id starting with
# ``prefix`` must carry a non-null Y0 value, otherwise the run blocks.
# Mirrors the spirit of M5 DI_002 but operates on already-resolved
# voice values in ``state.historical_data`` rather than ``MappedValues``.
_CRITICAL_VOICE_PREFIXES: tuple[tuple[str, str], ...] = (
    ("revenue", "pl.rev"),
    ("cash", "bs.nfp.cash"),
    ("equity", "bs.equity"),
)

_YEAR_ORDER: tuple[str, ...] = ("Y-3", "Y-2", "Y-1", "Y0")


def phase_e0_setup(state: ModelState) -> ModelState:
    logger.info("phase E0 year=%s", state.current_year)

    _validate_pre_run(state)
    _apply_sector_pack(state)
    _mark_historical_years(state)

    return state


def _validate_pre_run(state: ModelState) -> None:
    for group_name, prefix in _CRITICAL_VOICE_PREFIXES:
        if not _any_voice_with_prefix_has_y0(state.historical_data, prefix):
            state.validation_issues.append(
                ValidationIssue(
                    rule_id="E0_001_y0_critical_voices",
                    severity="block",
                    message=(
                        f"Y0 actual missing for critical voice group "
                        f"'{group_name}' (no voice with prefix '{prefix}' "
                        f"carries a Y0 value)"
                    ),
                    year="Y0",
                    context={"group": group_name, "prefix": prefix},
                )
            )

    if not state.method_configs:
        state.validation_issues.append(
            ValidationIssue(
                rule_id="E0_002_method_configs_present",
                severity="block",
                message=(
                    "No method configurations defined for the project; "
                    "configure at least one voice via M6 before running"
                ),
            )
        )


def _any_voice_with_prefix_has_y0(
    historical_data: dict[str, dict[str, float]], prefix: str
) -> bool:
    for voice_id, by_year in historical_data.items():
        if not voice_id.startswith(prefix):
            continue
        if by_year.get("Y0") is not None:
            return True
    return False


def _apply_sector_pack(state: ModelState) -> None:
    sector_pack_id = (
        getattr(state.project, "sector_pack", None) if state.project else None
    )
    if not sector_pack_id:
        logger.info("E0 sector_pack: project has no sector_pack set, skipping")
        return

    sector_packs = (
        getattr(state.registries, "sector_packs", None)
        if state.registries is not None
        else None
    )
    if not isinstance(sector_packs, dict):
        logger.info(
            "E0 sector_pack: registries unavailable, skipping pack '%s'",
            sector_pack_id,
        )
        return

    pack = sector_packs.get(sector_pack_id)
    if pack is None:
        logger.warning(
            "E0 sector_pack: %r not found in registries.sector_packs",
            sector_pack_id,
        )
        return

    state.active_sector_pack = sector_pack_id
    overrides = pack.get("method_overrides_examples") or []
    logger.info(
        "E0 sector_pack: applied %s with %d method_overrides_examples",
        sector_pack_id,
        len(overrides),
    )
    for override_str in overrides:
        logger.info("  override_example: %s", override_str)


def _mark_historical_years(state: ModelState) -> None:
    years: set[str] = set()
    for by_year in state.historical_data.values():
        for year, value in by_year.items():
            if value is not None:
                years.add(year)
    state.historical_years = _sort_historical_years(years)


def _sort_historical_years(years: Iterable[str]) -> list[str]:
    seen = list(dict.fromkeys(years))
    known = [y for y in _YEAR_ORDER if y in seen]
    extras = sorted(y for y in seen if y not in _YEAR_ORDER)
    return known + extras


__all__ = ["phase_e0_setup"]

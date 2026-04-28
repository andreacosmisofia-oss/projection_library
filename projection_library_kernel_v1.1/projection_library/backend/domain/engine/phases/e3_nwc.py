"""E3 — NWC + ricalcolo COGS esatto.

~22 voci ``bs.nwc.*`` (escluse ``cit_*`` calcolate in E7.5) +
``pl.cogs.inventory_writeoff`` + ``pl.cogs.wip_capitalization`` +
ricalcolo finale di ``pl.cogs.total`` / ``pl.gross_profit`` / ``pl.ebitda``
(che in E1 sono stati materializzati come proxy).

Three responsibility groups, processed in two ordered passes so the
COGS final values can read NWC balances written earlier in the same
phase:

1. **Days-driven NWC** (AR / Inventory / AP). The simplified formula
   used here bypasses the registry's ``days_target`` method (which
   uses generic assumption keys ``days`` / ``denominator_voice`` /
   ``sign``) in favour of explicit DSO / DIO / DPO assumptions:

   * ``bs.nwc.ar.trade_gross   = dso × resolve(pl.rev.net, year)   / 365``
   * ``bs.nwc.inventory.total  = dio × abs(pl.cogs.total[year])    / 365``
   * ``bs.nwc.ap.trade         = -dpo × abs(pl.cogs.total[year])   / 365``

   Days come from
   ``state.assumptions[voice]['{dso|dio|dpo}_days'][year]``.
   When the assumption is missing the helper falls back to the days
   *implied* by the Y0 actual (``balance_y0 × 365 / flow_y0``), so the
   projection holds the historical ratio constant across the horizon.

2. **Inventory writeoff & WIP capitalisation**:

   * writeoff = ``-pct × (inventory.total[prev] + inventory.total[year]) / 2``
   * wip_cap = ``-(inventory.wip[year] - inventory.wip[prev])``

3. **Final replacement of E1 proxies**:

   * ``pl.cogs.total = pl.cogs.total(E1 proxy) + writeoff + wip_cap``
   * ``pl.gross_profit = pl.rev.net + pl.cogs.total`` (final)
   * ``pl.ebitda = pl.gross_profit + pl.opex.total + pl.provisions.total``

   ``pl.rev.net`` is still its E1 proxy at this point; the IFRS 15
   adjustment lands in E3.1 and re-touches gross_profit / ebitda.

NWC voices that don't match the days pattern (other_current_assets,
accruals, ...) fall through to ``dispatch_method`` exactly like E1.
"""

from __future__ import annotations

import logging

from backend.domain.engine.phases._helpers import dispatch_method
from backend.domain.engine.value_resolver import (
    ModelState,
    get_prev_year,
    resolve_voice_value,
)

logger = logging.getLogger(__name__)


_PHASE_ID = "E3"


# voice_id -> (assumption key, denominator voice, sign, abs_denom?)
_DAYS_DRIVEN: dict[str, tuple[str, str, int, bool]] = {
    "bs.nwc.ar.trade_gross": ("dso_days", "pl.rev.net", 1, False),
    "bs.nwc.inventory.total": ("dio_days", "pl.cogs.total", 1, True),
    "bs.nwc.ap.trade": ("dpo_days", "pl.cogs.total", -1, True),
}

_WRITEOFF_VOICE = "pl.cogs.inventory_writeoff"
_WIP_CAP_VOICE = "pl.cogs.wip_capitalization"
_INVENTORY_TOTAL = "bs.nwc.inventory.total"
_INVENTORY_WIP = "bs.nwc.inventory.wip"


def phase_e3(state: ModelState) -> ModelState:
    year = state.current_year
    logger.info("phase E3 year=%s", year)

    if state.registries is None:
        return state

    voices = getattr(state.registries, "voices", None) or {}
    e3_voice_ids = [
        vid
        for vid, meta in voices.items()
        if meta.get("calc_phase_final") == _PHASE_ID
    ]

    # Pass 1 — NWC balances. The COGS adjustments pass below reads
    # bs.nwc.inventory.total / bs.nwc.inventory.wip via
    # resolve_voice_value, so those must already be in base_values.
    for voice_id in e3_voice_ids:
        if not voice_id.startswith("bs.nwc."):
            continue
        value = _compute_nwc_voice(voice_id, year, state)
        if value is None:
            continue
        state.base_values.setdefault(voice_id, {})[year] = value

    # Pass 2 — inventory writeoff / WIP cap, then final COGS / GP / EBITDA.
    # Registry order already places these in dependency order:
    # writeoff → wip_cap → pl.cogs.total → pl.gross_profit → pl.ebitda.
    for voice_id in e3_voice_ids:
        if voice_id.startswith("bs.nwc."):
            continue
        value = _compute_pl_voice(voice_id, year, state)
        if value is None:
            continue
        state.base_values.setdefault(voice_id, {})[year] = value

    return state


def _compute_nwc_voice(
    voice_id: str, year: str, state: ModelState
) -> float | None:
    spec = _DAYS_DRIVEN.get(voice_id)
    if spec is not None:
        days_key, denominator, sign, abs_denom = spec
        return _days_driven(
            voice_id,
            days_key,
            denominator,
            year,
            state,
            sign=sign,
            abs_denom=abs_denom,
        )
    return dispatch_method(voice_id, year, state)


def _compute_pl_voice(
    voice_id: str, year: str, state: ModelState
) -> float | None:
    if voice_id == _WRITEOFF_VOICE:
        return _inventory_writeoff(year, state)
    if voice_id == _WIP_CAP_VOICE:
        return _wip_capitalization(year, state)
    if voice_id == "pl.cogs.total":
        return _cogs_total_final(year, state)
    if voice_id == "pl.gross_profit":
        return _gross_profit_final(year, state)
    if voice_id == "pl.ebitda":
        return _ebitda_final(year, state)
    return dispatch_method(voice_id, year, state)


def _days_driven(
    voice_id: str,
    days_key: str,
    denominator: str,
    year: str,
    state: ModelState,
    *,
    sign: int,
    abs_denom: bool,
) -> float | None:
    days = (
        state.assumptions.get(voice_id, {})
        .get(days_key, {})
        .get(year)
    )
    if days is None:
        days = _implied_days_from_history(
            voice_id, denominator, state, abs_denom=abs_denom
        )
    if days is None:
        return None

    flow = resolve_voice_value(denominator, year, state)
    if abs_denom:
        flow = abs(flow)
    return sign * days * flow / 365.0


def _implied_days_from_history(
    voice_id: str,
    denominator: str,
    state: ModelState,
    *,
    abs_denom: bool,
) -> float | None:
    """Compute days from the Y0 actuals: ``|balance| × 365 / |flow|``.

    Returns ``None`` when either side is missing or the flow is zero.
    """
    bal_y0 = state.historical_data.get(voice_id, {}).get("Y0")
    flow_y0 = state.historical_data.get(denominator, {}).get("Y0")
    if bal_y0 is None or flow_y0 is None:
        return None
    if abs_denom:
        flow_y0 = abs(flow_y0)
    if flow_y0 == 0:
        return None
    return abs(bal_y0) * 365.0 / flow_y0


def _inventory_writeoff(year: str, state: ModelState) -> float:
    pct = (
        state.assumptions.get(_WRITEOFF_VOICE, {})
        .get("rate", {})
        .get(year, 0.0)
    )
    if pct == 0:
        return 0.0
    prev = get_prev_year(year)
    inv_prev = resolve_voice_value(_INVENTORY_TOTAL, prev, state)
    inv_curr = resolve_voice_value(_INVENTORY_TOTAL, year, state)
    return -pct * (inv_prev + inv_curr) / 2.0


def _wip_capitalization(year: str, state: ModelState) -> float:
    prev = get_prev_year(year)
    wip_curr = resolve_voice_value(_INVENTORY_WIP, year, state)
    wip_prev = resolve_voice_value(_INVENTORY_WIP, prev, state)
    return -(wip_curr - wip_prev)


def _cogs_total_final(year: str, state: ModelState) -> float:
    """E3 final = E1 proxy + writeoff + wip_cap.

    The proxy is read directly from ``base_values`` (not via
    ``resolve_voice_value``) because we want the engine output, not
    the override-overlay view: overrides on pl.cogs.total are
    composed when downstream phases re-read it.
    """
    proxy = state.base_values.get("pl.cogs.total", {}).get(year, 0.0)
    writeoff = resolve_voice_value(_WRITEOFF_VOICE, year, state)
    wip_cap = resolve_voice_value(_WIP_CAP_VOICE, year, state)
    return proxy + writeoff + wip_cap


def _gross_profit_final(year: str, state: ModelState) -> float:
    rev_net = resolve_voice_value("pl.rev.net", year, state)
    cogs_total = resolve_voice_value("pl.cogs.total", year, state)
    return rev_net + cogs_total


def _ebitda_final(year: str, state: ModelState) -> float:
    gross_profit = resolve_voice_value("pl.gross_profit", year, state)
    opex_total = resolve_voice_value("pl.opex.total", year, state)
    provisions_total = resolve_voice_value("pl.provisions.total", year, state)
    return gross_profit + opex_total + provisions_total


__all__ = ["phase_e3"]

"""E3.1 — IFRS 15 adjustments.

Three voices, plus a re-aggregation of pl.rev.net / pl.gross_profit /
pl.ebitda to absorb the adjustment into the final P&L (Flow 07 §E3.1).

The IFRS 15 movement is the management approximation of the SP-side
contract balances flowing through revenue:

* ``pl.rev.adjustments.deferred_movement       = -(Δ contract_liabilities)``
* ``pl.rev.adjustments.contract_asset_movement = +(Δ contract_assets)``
* ``pl.rev.adjustments_total = deferred_movement + contract_asset_movement``

Then ``pl.rev.net`` (the E1 proxy already in ``base_values``) is
updated to its final value: ``pl.rev.net + adjustments_total``.
``pl.gross_profit`` and ``pl.ebitda`` are re-aggregated with the new
revenue and the final ``pl.cogs.total`` / ``pl.opex.total`` /
``pl.provisions.total`` already produced by E1/E3.

When neither contract balance is present in ``base_values`` (typical
for projects without IFRS 15 detail in the management accounts), the
phase is a silent no-op: ``pl.rev.net`` stays at its E1 proxy and no
adjustment voices are written. Following the spec literally, the
guard checks ``base_values`` only — a contract balance that exists in
``historical_data`` but is not being projected forward is treated as
missing rather than as a balance falling to zero.
"""

from __future__ import annotations

import logging

from backend.domain.engine.value_resolver import (
    ModelState,
    get_prev_year,
    resolve_voice_value,
)

logger = logging.getLogger(__name__)


_CONTRACT_LIAB = "bs.nwc.contract_liabilities"
_CONTRACT_ASSET = "bs.nwc.contract_assets"

_DEFERRED_MOVEMENT = "pl.rev.adjustments.deferred_movement"
_CONTRACT_ASSET_MOVEMENT = "pl.rev.adjustments.contract_asset_movement"
_ADJUSTMENTS_TOTAL = "pl.rev.adjustments_total"


def phase_e3_1(state: ModelState) -> ModelState:
    year = state.current_year
    logger.info("phase E3.1 year=%s", year)

    if not _has_ifrs15_data(state):
        return state

    prev = get_prev_year(year)

    delta_liab = resolve_voice_value(
        _CONTRACT_LIAB, year, state
    ) - resolve_voice_value(_CONTRACT_LIAB, prev, state)
    deferred_movement = -delta_liab

    delta_asset = resolve_voice_value(
        _CONTRACT_ASSET, year, state
    ) - resolve_voice_value(_CONTRACT_ASSET, prev, state)
    contract_asset_movement = delta_asset

    adjustments_total = deferred_movement + contract_asset_movement

    state.base_values.setdefault(_DEFERRED_MOVEMENT, {})[year] = deferred_movement
    state.base_values.setdefault(_CONTRACT_ASSET_MOVEMENT, {})[
        year
    ] = contract_asset_movement
    state.base_values.setdefault(_ADJUSTMENTS_TOTAL, {})[year] = adjustments_total

    # Update pl.rev.net (final = E1 proxy + adjustments_total). We read
    # the proxy directly from base_values rather than resolve_voice_value
    # so we don't compose with any active override on pl.rev.net while
    # we're still inside the engine output stage.
    rev_net_proxy = state.base_values.get("pl.rev.net", {}).get(year, 0.0)
    rev_net_final = rev_net_proxy + adjustments_total
    state.base_values.setdefault("pl.rev.net", {})[year] = rev_net_final

    # Re-aggregate gross_profit / ebitda. pl.cogs.total / pl.opex.total /
    # pl.provisions.total already carry their final values from E1+E3.
    cogs_total = resolve_voice_value("pl.cogs.total", year, state)
    gross_profit = rev_net_final + cogs_total
    state.base_values.setdefault("pl.gross_profit", {})[year] = gross_profit

    opex_total = resolve_voice_value("pl.opex.total", year, state)
    provisions_total = resolve_voice_value("pl.provisions.total", year, state)
    ebitda = gross_profit + opex_total + provisions_total
    state.base_values.setdefault("pl.ebitda", {})[year] = ebitda

    return state


def _has_ifrs15_data(state: ModelState) -> bool:
    return (
        _CONTRACT_LIAB in state.base_values
        or _CONTRACT_ASSET in state.base_values
    )


__all__ = ["phase_e3_1"]

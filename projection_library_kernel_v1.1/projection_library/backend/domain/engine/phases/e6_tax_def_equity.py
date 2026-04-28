"""E6 — Tax differita + Equity (driver).

~13 voci — DTA / DTL roll-forward, share capital movements,
OCI cumulative close, NCI roll-forward, dividend seed for E7. See
flows/07_engine_execution.md §E6.

Sequence:

1. Registry-driven dispatch_method runs first so any voice with a
   default method (capital.organic_increases, oci_movement
   placeholders, …) gets its baseline written. The explicit logic
   below then overlays the roll-forwards on top.

2. DTA / DTL — pilot v1.1 simplified drift:
       dta_close = dta_open × (1 + drift)
       dtl_close = dtl_open × (1 + drift)
   The drift comes from
   ``state.assumptions['bs.tax.{dta|dtl}_close']['drift'][year]``;
   when missing the default is 0 (flat). The P&L deferred tax line
   is the algebraic delta:
       pl.tax.deferred = -(dta_close - dta_open) + (dtl_close - dtl_open)
   pl.tax.deferred is officially an E7 voice — E6 seeds it; E7 may
   refine.

3. Share capital roll-forward:
       share_capital.close = share_capital.open
                             + capital_injections - buyback
   Both flows come from assumptions on the close voice. The buyback
   amount is also surfaced as ``bs.equity.buyback`` (negative flow,
   convention used by the E7 retained_earnings identity rule).

4. OCI cumulative:
       oci_cumulative.close = oci_open + actuarial + fv_hedging + fx
   ``actuarial`` is read via resolve_voice_value from
   ``bs.equity.oci_actuarial`` — seeded by E5. ``fv_hedging`` and
   ``fx`` come from assumptions, default 0.

5. NCI:
       nci.close = nci_open × (1 + growth)
   growth from assumptions, default 0.

6. Dividend seed for E7:
       bs.equity.dividends = -payout × max(0, net_income[prev_year])
   The prev_year resolve dispatches into historical_data when prev is
   Y0, and into base_values for Y2 / Y3 (E7 of the previous year-loop
   iteration has already written pl.net_income).
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


_PHASE_ID = "E6"

_DTA_VOICE = "bs.tax.dta_close"
_DTL_VOICE = "bs.tax.dtl_close"
_PL_TAX_DEFERRED = "pl.tax.deferred"

_SHARE_CAPITAL = "bs.equity.share_capital.close"
_CAPITAL_INJECTIONS = "bs.equity.capital_injections"
_BUYBACK = "bs.equity.buyback"

_OCI_CLOSE = "bs.equity.oci_cumulative.close"
_OCI_ACTUARIAL = "bs.equity.oci_actuarial"

_NCI_CLOSE = "bs.equity.nci.close"

_DIVIDENDS = "bs.equity.dividends"
_NET_INCOME = "pl.net_income"


def phase_e6(state: ModelState) -> ModelState:
    year = state.current_year
    logger.info("phase E6 year=%s", year)

    # Pass 1: registry dispatch (gives default values to driver voices).
    if state.registries is not None:
        voices = getattr(state.registries, "voices", None) or {}
        voice_ids = [
            vid
            for vid, meta in voices.items()
            if meta.get("calc_phase_final") == _PHASE_ID
        ]
        for vid in voice_ids:
            value = dispatch_method(vid, year, state)
            if value is None:
                continue
            state.base_values.setdefault(vid, {})[year] = value

    # Pass 2-6: explicit roll-forwards.
    _process_dta_dtl(year, state)
    _process_share_capital(year, state)
    _process_oci(year, state)
    _process_nci(year, state)
    _process_dividends(year, state)

    return state


# ---------------------------------------------------------------------------
# DTA / DTL
# ---------------------------------------------------------------------------


def _process_dta_dtl(year: str, state: ModelState) -> None:
    prev = get_prev_year(year)

    dta_drift = (
        state.assumptions.get(_DTA_VOICE, {}).get("drift", {}).get(year, 0.0)
    )
    dta_open = resolve_voice_value(_DTA_VOICE, prev, state)
    dta_close = dta_open * (1 + dta_drift)

    dtl_drift = (
        state.assumptions.get(_DTL_VOICE, {}).get("drift", {}).get(year, 0.0)
    )
    dtl_open = resolve_voice_value(_DTL_VOICE, prev, state)
    dtl_close = dtl_open * (1 + dtl_drift)

    state.base_values.setdefault(_DTA_VOICE, {})[year] = dta_close
    state.base_values.setdefault(_DTL_VOICE, {})[year] = dtl_close

    deferred = -(dta_close - dta_open) + (dtl_close - dtl_open)
    state.base_values.setdefault(_PL_TAX_DEFERRED, {})[year] = deferred


# ---------------------------------------------------------------------------
# Share capital
# ---------------------------------------------------------------------------


def _process_share_capital(year: str, state: ModelState) -> None:
    prev = get_prev_year(year)
    cfg = state.assumptions.get(_SHARE_CAPITAL, {})
    capital_injections = float(
        cfg.get("capital_injections", {}).get(year, 0.0)
    )
    buyback = float(cfg.get("buyback", {}).get(year, 0.0))

    open_val = resolve_voice_value(_SHARE_CAPITAL, prev, state)
    close = open_val + capital_injections - buyback

    state.base_values.setdefault(_SHARE_CAPITAL, {})[year] = close
    state.base_values.setdefault(_CAPITAL_INJECTIONS, {})[year] = capital_injections
    # Buyback as a negative outflow voice (E7 retained_earnings identity
    # adds dividends + buyback to the bridge so the flow must be signed).
    state.base_values.setdefault(_BUYBACK, {})[year] = -abs(buyback)


# ---------------------------------------------------------------------------
# OCI cumulative
# ---------------------------------------------------------------------------


def _process_oci(year: str, state: ModelState) -> None:
    prev = get_prev_year(year)
    cfg = state.assumptions.get(_OCI_CLOSE, {})

    oci_open = resolve_voice_value(_OCI_CLOSE, prev, state)
    actuarial = resolve_voice_value(_OCI_ACTUARIAL, year, state)
    fv_hedging = float(cfg.get("fv_hedging", {}).get(year, 0.0))
    fx = float(cfg.get("fx", {}).get(year, 0.0))

    state.base_values.setdefault(_OCI_CLOSE, {})[year] = (
        oci_open + actuarial + fv_hedging + fx
    )


# ---------------------------------------------------------------------------
# NCI
# ---------------------------------------------------------------------------


def _process_nci(year: str, state: ModelState) -> None:
    prev = get_prev_year(year)
    growth = (
        state.assumptions.get(_NCI_CLOSE, {})
        .get("growth", {})
        .get(year, 0.0)
    )
    nci_open = resolve_voice_value(_NCI_CLOSE, prev, state)
    state.base_values.setdefault(_NCI_CLOSE, {})[year] = nci_open * (1 + growth)


# ---------------------------------------------------------------------------
# Dividends seed
# ---------------------------------------------------------------------------


def _process_dividends(year: str, state: ModelState) -> None:
    prev = get_prev_year(year)
    payout = (
        state.assumptions.get(_DIVIDENDS, {}).get("payout", {}).get(year, 0.0)
    )
    net_income_prev = resolve_voice_value(_NET_INCOME, prev, state)
    state.base_values.setdefault(_DIVIDENDS, {})[year] = (
        -payout * max(0.0, net_income_prev)
    )


__all__ = ["phase_e6"]

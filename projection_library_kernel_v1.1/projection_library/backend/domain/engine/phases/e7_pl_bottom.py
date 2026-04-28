"""E7 — P&L bottom + tax current + retained earnings.

~13 voci: ``pl.ebit``, ``pl.ebt``, ``pl.tax.current``, ``pl.tax.total``,
``pl.net_income``, ``pl.ebitda_adjusted``, ``pl.ebit_adjusted``,
``bs.equity.retained_earnings.close``, ``bs.tax.nol_carryforward.close``,
plus the helper aggregates ``pl.da.total`` and ``pl.impairment.total``
materialised here from the family leaves written in E2.
See flows/07_engine_execution.md §E7.

Sequence:

1. Registry-driven ``dispatch_method`` provides baselines for every E7
   voice. The explicit logic below overlays the bridge.

2. ``pl.ebit = ebitda + da.total + impairment.total``. ``pl.da.total``
   sums ``pl.da.{ppe,intangibles,rou}`` (D&A is stored as a negative
   cost, so the sum-add bridge keeps the standard ebit identity).
   ``pl.impairment.total`` sums the family leaves; missing voices
   default to 0.

3. ``pl.ebt = ebit + financial.total_net + equity_method_result +
   non_operating_total + fair_value_gain_loss_IP``. Missing voices
   resolve to 0.

4. Current tax with optional NOL bridge:

       no NOL: tax.current = -etr × max(0, ebt)

       NOL > 0 and ebt > 0:
           nol_used  = min(nol_open, ebt × 0.8)
           taxable   = max(0, ebt - nol_used)
           tax       = -etr × taxable
           nol_close = nol_open - nol_used

   ``etr`` reads from
   ``state.assumptions['pl.tax.current']['etr'][year]``, falls back to
   ``state.project.etr_default``, and finally to 0 when neither is set.

5. ``pl.tax.total = tax.current + tax.deferred`` (deferred from E6).
   ``pl.net_income = ebt + tax.total``.

6. Adjusted metrics — pilot v1.1 placeholder:
   ``pl.ebitda_adjusted = pl.ebitda``, ``pl.ebit_adjusted = pl.ebit``.
   The non_recurring flag plumbing lands later.

7. Retained earnings identity:
   ``re.close = re_open + net_income + dividends + buyback``.
   ``dividends`` and ``buyback`` are the signed flows seeded by E6.
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


_PHASE_ID = "E7"

_DA_FAMILIES = ("pl.da.ppe", "pl.da.intangibles", "pl.da.rou")
_IMPAIRMENT_FAMILIES = (
    "pl.impairment.ppe",
    "pl.impairment.intangibles",
    "pl.impairment.goodwill",
)

_NOL_VOICE = "bs.tax.nol_carryforward.close"
_NOL_USAGE_CAP = 0.8

_DEFAULT_ETR = 0.0


def phase_e7(state: ModelState) -> ModelState:
    year = state.current_year
    logger.info("phase E7 year=%s", year)

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

    _compute_ebit(year, state)
    _compute_ebt(year, state)
    _compute_tax_current_and_nol(year, state)
    _compute_tax_total_and_net_income(year, state)
    _compute_adjusted_metrics(year, state)
    _compute_retained_earnings(year, state)

    return state


# ---------------------------------------------------------------------------
# pl.ebit
# ---------------------------------------------------------------------------


def _compute_ebit(year: str, state: ModelState) -> None:
    ebitda = resolve_voice_value("pl.ebitda", year, state)

    da_total = sum(
        state.base_values.get(f, {}).get(year, 0.0) for f in _DA_FAMILIES
    )
    impairment_total = sum(
        state.base_values.get(f, {}).get(year, 0.0)
        for f in _IMPAIRMENT_FAMILIES
    )

    state.base_values.setdefault("pl.da.total", {})[year] = da_total
    state.base_values.setdefault("pl.impairment.total", {})[year] = impairment_total
    state.base_values.setdefault("pl.ebit", {})[year] = (
        ebitda + da_total + impairment_total
    )


# ---------------------------------------------------------------------------
# pl.ebt
# ---------------------------------------------------------------------------


def _compute_ebt(year: str, state: ModelState) -> None:
    ebit = resolve_voice_value("pl.ebit", year, state)
    financial_total = resolve_voice_value("pl.financial.total_net", year, state)
    equity_method = resolve_voice_value("pl.equity_method_result", year, state)
    non_operating = resolve_voice_value(
        "pl.other.non_operating_recurring", year, state
    ) + resolve_voice_value(
        "pl.other.non_operating_extraordinary", year, state
    )
    fv_ip = resolve_voice_value(
        "pl.other.fair_value_gain_loss_investment_property", year, state
    )

    state.base_values.setdefault("pl.ebt", {})[year] = (
        ebit + financial_total + equity_method + non_operating + fv_ip
    )


# ---------------------------------------------------------------------------
# pl.tax.current + NOL bridge
# ---------------------------------------------------------------------------


def _compute_tax_current_and_nol(year: str, state: ModelState) -> None:
    prev = get_prev_year(year)
    ebt = resolve_voice_value("pl.ebt", year, state)
    etr = _resolve_etr(year, state)
    nol_open = resolve_voice_value(_NOL_VOICE, prev, state)

    if nol_open > 0 and ebt > 0:
        nol_used = min(nol_open, ebt * _NOL_USAGE_CAP)
        taxable = max(0.0, ebt - nol_used)
        tax_current = -etr * taxable
        nol_close = nol_open - nol_used
    else:
        tax_current = -etr * max(0.0, ebt)
        nol_close = nol_open

    state.base_values.setdefault("pl.tax.current", {})[year] = tax_current
    state.base_values.setdefault(_NOL_VOICE, {})[year] = nol_close


def _resolve_etr(year: str, state: ModelState) -> float:
    direct = (
        state.assumptions.get("pl.tax.current", {})
        .get("etr", {})
        .get(year)
    )
    if direct is not None:
        return float(direct)
    if state.project is not None:
        project_default = getattr(state.project, "etr_default", None)
        if project_default is not None:
            return float(project_default)
    return _DEFAULT_ETR


# ---------------------------------------------------------------------------
# pl.tax.total + pl.net_income
# ---------------------------------------------------------------------------


def _compute_tax_total_and_net_income(year: str, state: ModelState) -> None:
    tax_current = resolve_voice_value("pl.tax.current", year, state)
    tax_deferred = resolve_voice_value("pl.tax.deferred", year, state)
    tax_total = tax_current + tax_deferred
    state.base_values.setdefault("pl.tax.total", {})[year] = tax_total

    ebt = resolve_voice_value("pl.ebt", year, state)
    state.base_values.setdefault("pl.net_income", {})[year] = ebt + tax_total


# ---------------------------------------------------------------------------
# Adjusted metrics (pilot placeholder)
# ---------------------------------------------------------------------------


def _compute_adjusted_metrics(year: str, state: ModelState) -> None:
    # The non_recurring flag plumbing isn't wired yet; placeholder copies
    # the headline values so downstream consumers always find the voices.
    state.base_values.setdefault("pl.ebitda_adjusted", {})[year] = (
        resolve_voice_value("pl.ebitda", year, state)
    )
    state.base_values.setdefault("pl.ebit_adjusted", {})[year] = (
        resolve_voice_value("pl.ebit", year, state)
    )


# ---------------------------------------------------------------------------
# Retained earnings identity
# ---------------------------------------------------------------------------


def _compute_retained_earnings(year: str, state: ModelState) -> None:
    prev = get_prev_year(year)
    re_open = resolve_voice_value(
        "bs.equity.retained_earnings.close", prev, state
    )
    net_income = resolve_voice_value("pl.net_income", year, state)
    dividends = resolve_voice_value("bs.equity.dividends", year, state)
    buyback = resolve_voice_value("bs.equity.buyback", year, state)
    state.base_values.setdefault("bs.equity.retained_earnings.close", {})[year] = (
        re_open + net_income + dividends + buyback
    )


__all__ = ["phase_e7"]

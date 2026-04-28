"""E7.5 — CIT NWC + NWC operating definitivo.

5 voci registry-side: ``bs.nwc.other_current_assets.cit_receivable``,
``bs.nwc.other_current_assets`` (subtotal), the symmetric pair on the
liab side, and ``bs.nwc.operating`` (final). See
flows/07_engine_execution.md §E7.5.

Sequence:

1. CIT payable / receivable from the year-on-year change in current
   tax. Following the user spec:
       cit_amount = -(|tax_current[year]| - |tax_current[prev_year]|)

   ``abs()`` wraps so the helper is robust to either sign convention
   for ``pl.tax.current`` (E7 stores it as a negative cost). The
   amount is then split:
       bs.nwc.other_current_liab.cit_payable     = min(0, cit_amount)
       bs.nwc.other_current_assets.cit_receivable = max(0, cit_amount)

2. Aggregate ``bs.nwc.other_current_assets`` (sum of vat_receivable +
   cit_receivable + other) and ``bs.nwc.other_current_liab`` (sum of
   vat_payable + cit_payable + other). These overwrite any subtotal
   left in place by E3 / dispatch_method.

3. ``bs.nwc.operating`` final — algebraic sum of every operating NWC
   component. Replaces the E3 proxy.
"""

from __future__ import annotations

import logging

from backend.domain.engine.value_resolver import (
    ModelState,
    get_prev_year,
    resolve_voice_value,
)

logger = logging.getLogger(__name__)


_TAX_CURRENT = "pl.tax.current"

_OCA_LEAVES = (
    "bs.nwc.other_current_assets.vat_receivable",
    "bs.nwc.other_current_assets.cit_receivable",
    "bs.nwc.other_current_assets.other",
)
_OCL_LEAVES = (
    "bs.nwc.other_current_liab.vat_payable",
    "bs.nwc.other_current_liab.cit_payable",
    "bs.nwc.other_current_liab.other",
)

# Components of operating NWC. ar.net is intentionally excluded — its
# component leaves (trade_gross + allowance) are summed individually
# so we don't double-count.
_NWC_OPERATING_COMPONENTS = (
    "bs.nwc.ar.trade_gross",
    "bs.nwc.ar.allowance",
    "bs.nwc.inventory.total",
    "bs.nwc.other_current_assets",
    "bs.nwc.other_current_liab",
    "bs.nwc.ap.trade",
    "bs.nwc.accrued_expenses",
    "bs.nwc.prepayments",
    "bs.nwc.contract_assets",
    "bs.nwc.contract_liabilities",
)


def phase_e7_5(state: ModelState) -> ModelState:
    year = state.current_year
    logger.info("phase E7.5 year=%s", year)

    _process_cit(year, state)
    _aggregate_other_current_assets(year, state)
    _aggregate_other_current_liab(year, state)
    _aggregate_nwc_operating_final(year, state)

    return state


# ---------------------------------------------------------------------------
# CIT
# ---------------------------------------------------------------------------


def _process_cit(year: str, state: ModelState) -> None:
    prev = get_prev_year(year)
    tax_year_magnitude = abs(resolve_voice_value(_TAX_CURRENT, year, state))
    tax_prev_magnitude = abs(resolve_voice_value(_TAX_CURRENT, prev, state))

    cit_amount = -(tax_year_magnitude - tax_prev_magnitude)

    state.base_values.setdefault(
        "bs.nwc.other_current_liab.cit_payable", {}
    )[year] = min(0.0, cit_amount)
    state.base_values.setdefault(
        "bs.nwc.other_current_assets.cit_receivable", {}
    )[year] = max(0.0, cit_amount)


# ---------------------------------------------------------------------------
# Subtotal aggregations
# ---------------------------------------------------------------------------


def _aggregate_other_current_assets(year: str, state: ModelState) -> None:
    total = sum(
        state.base_values.get(leaf, {}).get(year, 0.0) for leaf in _OCA_LEAVES
    )
    state.base_values.setdefault("bs.nwc.other_current_assets", {})[year] = total


def _aggregate_other_current_liab(year: str, state: ModelState) -> None:
    total = sum(
        state.base_values.get(leaf, {}).get(year, 0.0) for leaf in _OCL_LEAVES
    )
    state.base_values.setdefault("bs.nwc.other_current_liab", {})[year] = total


# ---------------------------------------------------------------------------
# NWC operating final
# ---------------------------------------------------------------------------


def _aggregate_nwc_operating_final(year: str, state: ModelState) -> None:
    total = sum(
        resolve_voice_value(c, year, state) for c in _NWC_OPERATING_COMPONENTS
    )
    state.base_values.setdefault("bs.nwc.operating", {})[year] = total


__all__ = ["phase_e7_5"]

"""E4 — NFP + financial expenses.

~19 voci ``bs.nfp.borrowings.*`` + ``bs.nfp.lease_liability.*`` +
``pl.financial.{interest_expense,lease_interest,total_net}``. The
proxy of ``pl.financial.interest_income`` lives here too
(``calc_phase_proxy=E4``); its final value is recomputed in E8 once
the closing cash is known. See flows/07_engine_execution.md §E4.

Two ordered passes so the P&L lines can read closing balances written
in the same phase.

Pass 1 — BS NFP
  * Term-loan amortisation: linear repayment driven by static
    parameters on ``driver.bs.nfp.borrowings.term_loan_repayments``
    (``initial_principal`` / ``term_years``). Falls back to the
    registry method when the driver is missing.
  * Lease close roll-forward:
        lease_open + new_contracts − payments_principal
    Sub-circolarità con interest_accrued: l'interest accrued non
    viene aggiunto al close (the registry stores principal-only
    payments, interest stays in P&L).
  * Other BS NFP voices (drawdowns, rcf_movement, bonds_movement,
    aggregates, …) flow through dispatch_method.

Pass 2 — financial P&L
  * ``pl.financial.interest_expense = -rate × |bal_avg|`` where
    ``bal_avg = (total_close[prev] + total_close[year]) / 2``.
    Default rate 5%.
  * ``pl.financial.interest_income = rate_income × |cash[prev_year]|``
    — the prev-year proxy is intentional to break the
    sub-circolarità with cash close (E8 recomputes the final).
    Default rate 1%.
  * ``pl.financial.lease_interest = -rate × |lease_open|``.
    Default rate 3%.
  * ``pl.financial.total_net`` aggregates the three components plus
    ``pl.financial.fx_gain_loss`` (already computed in E1).

Sign convention: balances are read with their stored sign and then
``abs()``-wrapped before applying the rate, so the helpers don't
depend on whether the registry stores liabilities as negative or
positive — interest_expense / lease_interest always come out
negative (cost), interest_income positive.
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


_PHASE_ID = "E4"

_TERM_LOAN_REPAY_VOICE = "bs.nfp.borrowings.term_loan_repayments"
_BORROWINGS_TOTAL_CLOSE = "bs.nfp.borrowings.total_close"
_LEASE_CLOSE = "bs.nfp.lease_liability.close"
_LEASE_NEW = "bs.nfp.lease_liability.new_contracts"
_LEASE_PAYMENTS = "bs.nfp.lease_liability.payments_principal"

_INTEREST_EXPENSE = "pl.financial.interest_expense"
_INTEREST_INCOME = "pl.financial.interest_income"
_LEASE_INTEREST = "pl.financial.lease_interest"
_FX_GAIN_LOSS = "pl.financial.fx_gain_loss"
_FINANCIAL_TOTAL = "pl.financial.total_net"

_CASH = "bs.nfp.cash"

_DEFAULT_INTEREST_RATE_EXPENSE = 0.05
_DEFAULT_INTEREST_RATE_INCOME = 0.01
_DEFAULT_LEASE_RATE = 0.03


def phase_e4(state: ModelState) -> ModelState:
    year = state.current_year
    logger.info("phase E4 year=%s", year)

    if state.registries is None:
        return state

    voices = getattr(state.registries, "voices", None) or {}
    voice_ids = [
        vid
        for vid, meta in voices.items()
        if meta.get("calc_phase_final") == _PHASE_ID
        or meta.get("calc_phase_proxy") == _PHASE_ID
    ]

    # Pass 1 — BS NFP balances (provides total_close / lease_close used by Pass 2).
    for vid in voice_ids:
        if not vid.startswith("bs.nfp."):
            continue
        value = _compute_bs_voice(vid, year, state)
        if value is None:
            continue
        state.base_values.setdefault(vid, {})[year] = value

    # Pass 2 — P&L financial lines, computed deterministically so that
    # total_net always sees its three components written in this phase.
    state.base_values.setdefault(_INTEREST_EXPENSE, {})[year] = _interest_expense(
        year, state
    )
    state.base_values.setdefault(_INTEREST_INCOME, {})[year] = _interest_income(
        year, state
    )
    state.base_values.setdefault(_LEASE_INTEREST, {})[year] = _lease_interest(
        year, state
    )
    state.base_values.setdefault(_FINANCIAL_TOTAL, {})[year] = _financial_total_net(
        year, state
    )

    return state


def _compute_bs_voice(
    voice_id: str, year: str, state: ModelState
) -> float | None:
    if voice_id == _TERM_LOAN_REPAY_VOICE:
        value = _term_loan_repayment(voice_id, year, state)
        if value is not None:
            return value
        # Driver missing → let dispatch_method honour the registry method
        return dispatch_method(voice_id, year, state)

    if voice_id == _LEASE_CLOSE:
        return _lease_rollforward(year, state)

    return dispatch_method(voice_id, year, state)


def _term_loan_repayment(
    voice_id: str, year: str, state: ModelState
) -> float | None:
    """Linear amortisation: ``-principal / term_years`` (constant per year)."""
    driver_id = f"driver.{voice_id}"
    driver = state.drivers.get(driver_id, {})
    params = driver.get("static_parameters") or {}
    principal = params.get("initial_principal")
    term_years = params.get("term_years")
    if principal is None or term_years is None or term_years <= 0:
        return None
    return -principal / term_years


def _lease_rollforward(year: str, state: ModelState) -> float:
    prev = get_prev_year(year)
    lease_open = resolve_voice_value(_LEASE_CLOSE, prev, state)
    new_contracts = resolve_voice_value(_LEASE_NEW, year, state)
    payments_principal = resolve_voice_value(_LEASE_PAYMENTS, year, state)
    return lease_open + new_contracts - payments_principal


def _interest_expense(year: str, state: ModelState) -> float:
    rate = (
        state.assumptions.get(_INTEREST_EXPENSE, {})
        .get("rate", {})
        .get(year, _DEFAULT_INTEREST_RATE_EXPENSE)
    )
    prev = get_prev_year(year)
    bal_open = resolve_voice_value(_BORROWINGS_TOTAL_CLOSE, prev, state)
    bal_close = resolve_voice_value(_BORROWINGS_TOTAL_CLOSE, year, state)
    bal_avg = (bal_open + bal_close) / 2
    return -rate * abs(bal_avg)


def _interest_income(year: str, state: ModelState) -> float:
    """E4 proxy: rate × prev-year cash (final lands in E8)."""
    rate = (
        state.assumptions.get(_INTEREST_INCOME, {})
        .get("rate", {})
        .get(year, _DEFAULT_INTEREST_RATE_INCOME)
    )
    prev = get_prev_year(year)
    cash_prev = resolve_voice_value(_CASH, prev, state)
    return rate * abs(cash_prev)


def _lease_interest(year: str, state: ModelState) -> float:
    rate = (
        state.assumptions.get(_LEASE_INTEREST, {})
        .get("rate", {})
        .get(year, _DEFAULT_LEASE_RATE)
    )
    prev = get_prev_year(year)
    lease_open = resolve_voice_value(_LEASE_CLOSE, prev, state)
    return -rate * abs(lease_open)


def _financial_total_net(year: str, state: ModelState) -> float:
    return (
        resolve_voice_value(_INTEREST_EXPENSE, year, state)
        + resolve_voice_value(_INTEREST_INCOME, year, state)
        + resolve_voice_value(_LEASE_INTEREST, year, state)
        + resolve_voice_value(_FX_GAIN_LOSS, year, state)
    )


__all__ = ["phase_e4"]

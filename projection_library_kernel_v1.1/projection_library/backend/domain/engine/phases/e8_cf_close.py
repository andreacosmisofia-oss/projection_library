"""E8 — CF + cash close + balance check.

The longest phase by voice count (~38 voci): cash flow operating /
investing / financing legs, the cash identity, and the closing
balance-sheet integrity check. See flows/07_engine_execution.md §E8.

CF legs read every input through ``resolve_voice_value`` so any
override applied later naturally propagates: cash close itself is
computed via the identity ``cash[t] = cash[t-1] + net_change_cash``,
which means an override on a CF component flows through to cash
without re-running the engine.

Validation:

* ``AI_001`` (balance check) — registered as ``info`` when within
  ``max(1.0, 0.0001 × total_assets)`` tolerance, ``error`` otherwise.
* ``SC_009`` (cash non-negative) — ``error`` when projected cash goes
  below zero.

``AI_002`` (cash identity) is structurally enforced by computing
``bs.nfp.cash`` from the CF identity itself; we still emit an info
ValidationIssue so the validator audit trail records it.
"""

from __future__ import annotations

import logging

from backend.domain.engine.value_resolver import (
    ModelState,
    ValidationIssue,
    get_prev_year,
    resolve_voice_value,
)

logger = logging.getLogger(__name__)


def phase_e8(state: ModelState) -> ModelState:
    year = state.current_year
    logger.info("phase E8 year=%s", year)

    _cf_operating(year, state)
    _cf_investing(year, state)
    _cf_financing(year, state)
    _cash_close(year, state)
    _balance_check(year, state)

    return state


# ---------------------------------------------------------------------------
# CF Operating
# ---------------------------------------------------------------------------


def _cf_operating(year: str, state: ModelState) -> None:
    prev = get_prev_year(year)

    net_income = resolve_voice_value("pl.net_income", year, state)
    da_total = resolve_voice_value("pl.da.total", year, state)
    impairment_total = resolve_voice_value("pl.impairment.total", year, state)
    provisions_total = resolve_voice_value("pl.provisions.total", year, state)
    tax_deferred = resolve_voice_value("pl.tax.deferred", year, state)
    financial_total = resolve_voice_value("pl.financial.total_net", year, state)
    equity_method = resolve_voice_value("pl.equity_method_result", year, state)
    fv_ip = resolve_voice_value(
        "pl.other.fair_value_gain_loss_investment_property", year, state
    )

    nwc_year = resolve_voice_value("bs.nwc.operating", year, state)
    nwc_prev = resolve_voice_value("bs.nwc.operating", prev, state)
    nwc_change = nwc_year - nwc_prev

    cit_year = resolve_voice_value(
        "bs.nwc.other_current_liab.cit_payable", year, state
    )
    cit_prev = resolve_voice_value(
        "bs.nwc.other_current_liab.cit_payable", prev, state
    )
    tax_paid = abs(cit_year - cit_prev)

    eb_paid = abs(
        resolve_voice_value(
            "bs.employee_benefits.payments_to_employees", year, state
        )
    )

    da_addback = abs(da_total)
    impairment_addback = abs(impairment_total)
    provisions_addback = abs(provisions_total)

    cf_op = (
        net_income
        + da_addback
        + impairment_addback
        + provisions_addback
        + tax_deferred
        - financial_total
        - equity_method
        - fv_ip
        - nwc_change
        - tax_paid
        - eb_paid
    )

    bv = state.base_values
    bv.setdefault("cf.operating.net_income", {})[year] = net_income
    bv.setdefault("cf.operating.da_addback", {})[year] = da_addback
    bv.setdefault("cf.operating.impairment_addback", {})[year] = impairment_addback
    bv.setdefault("cf.operating.provisions_addback", {})[year] = provisions_addback
    bv.setdefault("cf.operating.tax_deferred_addback", {})[year] = tax_deferred
    bv.setdefault("cf.operating.financial_addback", {})[year] = -financial_total
    bv.setdefault("cf.operating.equity_method_addback", {})[year] = -equity_method
    bv.setdefault("cf.operating.fv_addback", {})[year] = -fv_ip
    bv.setdefault("cf.operating.nwc_change", {})[year] = -nwc_change
    bv.setdefault("cf.operating.tax_paid", {})[year] = -tax_paid
    bv.setdefault("cf.operating.employee_benefits_paid", {})[year] = -eb_paid
    bv.setdefault("cf.operating.total", {})[year] = cf_op


# ---------------------------------------------------------------------------
# CF Investing
# ---------------------------------------------------------------------------


def _cf_investing(year: str, state: ModelState) -> None:
    prev = get_prev_year(year)

    capex_ppe = abs(
        resolve_voice_value("bs.fa.tangible.maintenance_capex", year, state)
    ) + abs(
        resolve_voice_value("bs.fa.tangible.expansion_capex", year, state)
    )
    capex_intangibles = abs(
        resolve_voice_value("bs.fa.intangible.software_capex", year, state)
    )

    disposals_ppe = abs(
        resolve_voice_value("bs.fa.tangible.disposals_gross", year, state)
    )
    disposals_intangibles = abs(
        resolve_voice_value("bs.fa.intangible.disposals_gross", year, state)
    )

    ip_year = resolve_voice_value(
        "bs.fa.investment_property.gross_close", year, state
    )
    ip_prev = resolve_voice_value(
        "bs.fa.investment_property.gross_close", prev, state
    )
    ip_change = -(ip_year - ip_prev)

    fin_assets_year = resolve_voice_value(
        "bs.fa.financial.balance_close", year, state
    )
    fin_assets_prev = resolve_voice_value(
        "bs.fa.financial.balance_close", prev, state
    )
    financial_assets_movement = -(fin_assets_year - fin_assets_prev)

    cf_inv = (
        -capex_ppe
        - capex_intangibles
        + disposals_ppe
        + disposals_intangibles
        + ip_change
        + financial_assets_movement
    )

    bv = state.base_values
    bv.setdefault("cf.investing.capex_ppe", {})[year] = -capex_ppe
    bv.setdefault("cf.investing.capex_intangibles", {})[year] = -capex_intangibles
    bv.setdefault("cf.investing.disposals_ppe", {})[year] = disposals_ppe
    bv.setdefault("cf.investing.disposals_intangibles", {})[year] = (
        disposals_intangibles
    )
    bv.setdefault("cf.investing.investment_property_change", {})[year] = ip_change
    bv.setdefault("cf.investing.financial_assets_movement", {})[year] = (
        financial_assets_movement
    )
    bv.setdefault("cf.investing.total", {})[year] = cf_inv


# ---------------------------------------------------------------------------
# CF Financing
# ---------------------------------------------------------------------------


def _cf_financing(year: str, state: ModelState) -> None:
    drawdowns = resolve_voice_value(
        "bs.nfp.borrowings.term_loan_drawdowns", year, state
    )
    repayments = resolve_voice_value(
        "bs.nfp.borrowings.term_loan_repayments", year, state
    )
    capital_injections = resolve_voice_value(
        "bs.equity.capital_injections", year, state
    )
    buyback = resolve_voice_value("bs.equity.buyback", year, state)
    dividends = resolve_voice_value("bs.equity.dividends", year, state)
    lease_payments = resolve_voice_value(
        "bs.nfp.lease_liability.payments_principal", year, state
    )

    cf_fin = (
        drawdowns
        - abs(repayments)
        + capital_injections
        - abs(buyback)
        - abs(dividends)
        - abs(lease_payments)
    )

    bv = state.base_values
    bv.setdefault("cf.financing.borrowings_drawdowns", {})[year] = drawdowns
    bv.setdefault("cf.financing.borrowings_repayments", {})[year] = -abs(repayments)
    bv.setdefault("cf.financing.lease_payments_principal", {})[year] = -abs(
        lease_payments
    )
    bv.setdefault("cf.financing.dividends", {})[year] = -abs(dividends)
    bv.setdefault("cf.financing.capital_changes", {})[year] = (
        capital_injections - abs(buyback)
    )
    bv.setdefault("cf.financing.total", {})[year] = cf_fin


# ---------------------------------------------------------------------------
# Cash close (CF identity)
# ---------------------------------------------------------------------------


def _cash_close(year: str, state: ModelState) -> None:
    prev = get_prev_year(year)
    cf_op = resolve_voice_value("cf.operating.total", year, state)
    cf_inv = resolve_voice_value("cf.investing.total", year, state)
    cf_fin = resolve_voice_value("cf.financing.total", year, state)

    net_change = cf_op + cf_inv + cf_fin
    state.base_values.setdefault("cf.net_change_cash", {})[year] = net_change

    cash_prev = resolve_voice_value("bs.nfp.cash", prev, state)
    cash_close = cash_prev + net_change
    state.base_values.setdefault("bs.nfp.cash", {})[year] = cash_close
    state.base_values.setdefault("cf.cash_close", {})[year] = cash_close

    state.validation_issues.append(
        ValidationIssue(
            rule_id="AI_002_cash_identity",
            severity="info",
            message=f"Cash identity: cash[{year}] = cash[{prev}] + net_change",
            year=year,
            context={
                "cash_prev": cash_prev,
                "net_change": net_change,
                "cash_close": cash_close,
            },
        )
    )

    if cash_close < 0:
        state.validation_issues.append(
            ValidationIssue(
                rule_id="SC_009_cash_non_negative",
                severity="error",
                message=f"Cash projected negative at {year}: {cash_close:.2f}",
                year=year,
                voice_id="bs.nfp.cash",
                context={"cash_close": cash_close},
            )
        )


# ---------------------------------------------------------------------------
# Balance check
# ---------------------------------------------------------------------------


def _balance_check(year: str, state: ModelState) -> None:
    fa_total_net = (
        resolve_voice_value("bs.fa.tangible.net_close", year, state)
        + resolve_voice_value("bs.fa.intangible.net_close", year, state)
        + resolve_voice_value("bs.fa.rou.net_close", year, state)
        + resolve_voice_value(
            "bs.fa.investment_property.gross_close", year, state
        )
    )

    total_assets = (
        fa_total_net
        + resolve_voice_value("bs.nwc.operating", year, state)
        + resolve_voice_value("bs.nwc.other_current_assets", year, state)
        + resolve_voice_value("bs.tax.dta_close", year, state)
        + resolve_voice_value("bs.nfp.cash", year, state)
        + resolve_voice_value("bs.fa.financial.balance_close", year, state)
    )

    total_liab_equity = (
        resolve_voice_value("bs.nfp.borrowings.total_close", year, state)
        + resolve_voice_value("bs.nfp.lease_liability.close", year, state)
        + resolve_voice_value("bs.provisions.total_close", year, state)
        + resolve_voice_value("bs.employee_benefits.balance_close", year, state)
        + resolve_voice_value("bs.tax.dtl_close", year, state)
        + resolve_voice_value("bs.nwc.other_current_liab", year, state)
        + resolve_voice_value("bs.equity.share_capital.close", year, state)
        + resolve_voice_value(
            "bs.equity.retained_earnings.close", year, state
        )
        + resolve_voice_value("bs.equity.oci_cumulative.close", year, state)
        + resolve_voice_value("bs.equity.nci.close", year, state)
    )

    balance_check = total_assets - total_liab_equity

    state.base_values.setdefault("bs.total_assets", {})[year] = total_assets
    state.base_values.setdefault("bs.total_liabilities_equity", {})[year] = (
        total_liab_equity
    )
    state.base_values.setdefault("bs.balance_check", {})[year] = balance_check

    tolerance = max(1.0, abs(total_assets) * 0.0001)
    severity = "error" if abs(balance_check) > tolerance else "info"
    message = (
        f"Balance check off by {balance_check:.4f} > tolerance {tolerance:.4f}"
        if severity == "error"
        else f"Balance check OK: {balance_check:.6f} (tolerance {tolerance:.4f})"
    )
    state.validation_issues.append(
        ValidationIssue(
            rule_id="AI_001_balance_check",
            severity=severity,
            message=message,
            year=year,
            context={
                "balance_check": balance_check,
                "tolerance": tolerance,
                "total_assets": total_assets,
                "total_liab_equity": total_liab_equity,
            },
        )
    )


__all__ = ["phase_e8"]

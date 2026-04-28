"""Unit tests for phase_e8 (M9.11 CF + cash close + balance check)."""

from __future__ import annotations

from backend.domain.engine.phases.e8_cf_close import phase_e8
from backend.domain.engine.value_resolver import ModelState


def test_e8_cf_operating_basic():
    """cf_op = NI + addbacks + tax_deferred - financial - eq_method - fv
              - nwc_change - tax_paid - eb_paid."""
    state = ModelState(
        base_values={
            "pl.net_income": {"Y1": 100.0},
            "pl.da.total": {"Y1": -50.0},          # addback +50
            "pl.impairment.total": {"Y1": -20.0},  # addback +20
            "pl.provisions.total": {"Y1": -10.0},  # addback +10
            "pl.tax.deferred": {"Y1": -5.0},       # added as-is (already neg)
            "pl.financial.total_net": {"Y1": -8.0},  # subtracted → +8
            "pl.equity_method_result": {"Y1": 3.0},  # subtracted → -3
            # All other inputs (fv_ip, nwc_change, tax_paid, eb_paid) = 0
        },
        current_year="Y1",
    )

    state = phase_e8(state)

    # 100 + 50 + 20 + 10 + (-5) - (-8) - 3 = 180
    assert state.base_values["cf.operating.total"]["Y1"] == 180.0
    # Component voices written
    assert state.base_values["cf.operating.da_addback"]["Y1"] == 50.0
    assert state.base_values["cf.operating.provisions_addback"]["Y1"] == 10.0


def test_e8_cf_investing_capex():
    """cf_inv = -capex_ppe - capex_intangibles + disposals + ip_change
              + financial_assets_movement (all sign-controlled)."""
    state = ModelState(
        base_values={
            "bs.fa.tangible.maintenance_capex": {"Y1": 100.0},
            "bs.fa.tangible.expansion_capex": {"Y1": 50.0},
            "bs.fa.intangible.software_capex": {"Y1": 30.0},
            "bs.fa.tangible.disposals_gross": {"Y1": -10.0},  # registry sign
            # IP balance constant → no movement
            "bs.fa.investment_property.gross_close": {"Y1": 500.0},
            "bs.fa.financial.balance_close": {"Y1": 200.0},
        },
        historical_data={
            "bs.fa.investment_property.gross_close": {"Y0": 500.0},
            "bs.fa.financial.balance_close": {"Y0": 200.0},
        },
        current_year="Y1",
    )

    state = phase_e8(state)

    # capex_ppe = 100 + 50 = 150 ; capex_intangibles = 30 ; disposals = 10
    # IP_change = 0 ; fin_assets_movement = 0
    # cf_inv = -150 - 30 + 10 + 0 + 0 + 0 = -170
    assert state.base_values["cf.investing.total"]["Y1"] == -170.0
    assert state.base_values["cf.investing.capex_ppe"]["Y1"] == -150.0


def test_e8_cf_financing_debt():
    """cf_fin = drawdowns - |repayments| + capital_inj - |buyback|
              - |dividends| - |lease_payments|."""
    state = ModelState(
        base_values={
            "bs.nfp.borrowings.term_loan_drawdowns": {"Y1": 200.0},
            "bs.nfp.borrowings.term_loan_repayments": {"Y1": -100.0},
            "bs.equity.capital_injections": {"Y1": 50.0},
            "bs.equity.buyback": {"Y1": -20.0},
            "bs.equity.dividends": {"Y1": -30.0},
            "bs.nfp.lease_liability.payments_principal": {"Y1": 25.0},
        },
        current_year="Y1",
    )

    state = phase_e8(state)

    # 200 - 100 + 50 - 20 - 30 - 25 = 75
    assert state.base_values["cf.financing.total"]["Y1"] == 75.0


def test_e8_cash_close_identity():
    """cash[t] = cash[t-1] + cf_op + cf_inv + cf_fin."""
    state = ModelState(
        historical_data={"bs.nfp.cash": {"Y0": 100.0}},
        base_values={
            # CF inputs that produce a deterministic net change
            "pl.net_income": {"Y1": 50.0},  # cf_op = 50 (no other inputs)
            "bs.fa.tangible.maintenance_capex": {"Y1": 30.0},  # cf_inv = -30
            "bs.nfp.borrowings.term_loan_drawdowns": {"Y1": 10.0},  # cf_fin = 10
        },
        current_year="Y1",
    )

    state = phase_e8(state)

    # cf_op = 50, cf_inv = -30, cf_fin = 10 → net = 30
    assert state.base_values["cf.net_change_cash"]["Y1"] == 30.0
    # cash_close = 100 + 30 = 130
    assert state.base_values["bs.nfp.cash"]["Y1"] == 130.0
    assert state.base_values["cf.cash_close"]["Y1"] == 130.0
    # AI_002 info issue logged
    assert any(
        i.rule_id == "AI_002_cash_identity" and i.severity == "info"
        for i in state.validation_issues
    )


def test_e8_balance_check_within_tolerance():
    """A balanced setup produces an info-level AI_001 issue (no error)."""
    state = ModelState(
        historical_data={"bs.nfp.cash": {"Y0": 100.0}},
        base_values={
            # Construct a balanced BS:
            # Assets: cash (will be 100), retained_earnings on the equity side.
            # No CF activity → cash stays 100.
            "bs.equity.retained_earnings.close": {"Y1": 100.0},
            # Note: CF inputs all default to 0 → cf_op = cf_inv = cf_fin = 0
            # → cash[Y1] = 100. total_assets = 100. total_liab_equity = 100.
        },
        current_year="Y1",
    )

    state = phase_e8(state)

    assert state.base_values["bs.total_assets"]["Y1"] == 100.0
    assert state.base_values["bs.total_liabilities_equity"]["Y1"] == 100.0
    assert state.base_values["bs.balance_check"]["Y1"] == 0.0

    ai_001_issues = [
        i for i in state.validation_issues if i.rule_id == "AI_001_balance_check"
    ]
    assert len(ai_001_issues) == 1
    assert ai_001_issues[0].severity == "info"


def test_e8_balance_check_adds_error_when_off():
    """A material imbalance produces a severity=error AI_001 issue."""
    state = ModelState(
        historical_data={"bs.nfp.cash": {"Y0": 1000.0}},
        base_values={
            # Cash 1000 vs equity 0 → balance_check = +1000 (well above tolerance)
            "bs.equity.retained_earnings.close": {"Y1": 0.0},
        },
        current_year="Y1",
    )

    state = phase_e8(state)

    assert abs(state.base_values["bs.balance_check"]["Y1"] - 1000.0) < 1e-9

    ai_001 = next(
        i for i in state.validation_issues if i.rule_id == "AI_001_balance_check"
    )
    assert ai_001.severity == "error"
    assert "off by" in ai_001.message


def test_e8_cash_non_negative_validation():
    """Negative projected cash adds an SC_009 error."""
    state = ModelState(
        historical_data={"bs.nfp.cash": {"Y0": 50.0}},
        base_values={
            # Heavy capex drains cash below zero
            "bs.fa.tangible.maintenance_capex": {"Y1": 200.0},
        },
        current_year="Y1",
    )

    state = phase_e8(state)

    # cash_close = 50 + 0 + (-200) + 0 = -150
    assert state.base_values["bs.nfp.cash"]["Y1"] == -150.0
    sc_009 = [
        i for i in state.validation_issues if i.rule_id == "SC_009_cash_non_negative"
    ]
    assert len(sc_009) == 1
    assert sc_009[0].severity == "error"

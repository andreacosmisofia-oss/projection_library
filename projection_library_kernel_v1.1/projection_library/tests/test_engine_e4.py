"""Unit tests for phase_e4 (M9.6 NFP + financial expenses)."""

from __future__ import annotations

from types import SimpleNamespace

from backend.domain.engine.phases.e4_nfp import phase_e4
from backend.domain.engine.value_resolver import ModelState


def _registries(voices: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        voices=voices or {},
        methods={},
        derived_rules={},
    )


def _e4_voice(default_method: str | None = None) -> dict:
    return {
        "calc_phase_final": "E4",
        "calc_phase_proxy": None,
        "default_method": default_method,
    }


def test_e4_term_loan_amortization_linear():
    """repayment = -principal / term_years, written as a negative flow."""
    state = ModelState(
        registries=_registries(
            voices={"bs.nfp.borrowings.term_loan_repayments": _e4_voice()}
        ),
        drivers={
            "driver.bs.nfp.borrowings.term_loan_repayments": {
                "static_parameters": {
                    "initial_principal": 1000.0,
                    "term_years": 10,
                },
            },
        },
        current_year="Y1",
    )

    state = phase_e4(state)

    assert (
        state.base_values["bs.nfp.borrowings.term_loan_repayments"]["Y1"]
        == -100.0
    )


def test_e4_interest_expense_on_avg_balance():
    """interest_expense = -rate × |bal_avg|, negative cost."""
    state = ModelState(
        registries=_registries(),
        # total_close from prev (historical Y0) and current Y1
        historical_data={"bs.nfp.borrowings.total_close": {"Y0": -1000.0}},
        base_values={"bs.nfp.borrowings.total_close": {"Y1": -800.0}},
        assumptions={"pl.financial.interest_expense": {"rate": {"Y1": 0.06}}},
        current_year="Y1",
    )

    state = phase_e4(state)

    # bal_avg = (-1000 + -800) / 2 = -900 ; abs(bal_avg) = 900
    # interest_expense = -0.06 × 900 = -54
    assert state.base_values["pl.financial.interest_expense"]["Y1"] == -54.0


def test_e4_interest_expense_uses_default_rate_when_assumption_missing():
    """Default rate is 5% when no assumption is set for the voice."""
    state = ModelState(
        registries=_registries(),
        historical_data={"bs.nfp.borrowings.total_close": {"Y0": 1000.0}},
        base_values={"bs.nfp.borrowings.total_close": {"Y1": 1000.0}},
        current_year="Y1",
    )

    state = phase_e4(state)

    # 5% × 1000 = 50 → interest_expense = -50
    assert state.base_values["pl.financial.interest_expense"]["Y1"] == -50.0


def test_e4_interest_income_uses_prev_cash():
    """interest_income = rate × |cash[prev]| — sub-circolarità con cash close
    risolta usando il proxy del prev year, non il close del year corrente."""
    state = ModelState(
        registries=_registries(),
        # Cash[Y0] = 5000 historical ; cash[Y1] = whatever (must NOT be used)
        historical_data={"bs.nfp.cash": {"Y0": 5000.0}},
        base_values={"bs.nfp.cash": {"Y1": 9999.0}},
        assumptions={"pl.financial.interest_income": {"rate": {"Y1": 0.02}}},
        current_year="Y1",
    )

    state = phase_e4(state)

    # 0.02 × 5000 = 100 (not 0.02 × 9999)
    assert state.base_values["pl.financial.interest_income"]["Y1"] == 100.0


def test_e4_lease_rollforward():
    """lease_close = lease_open + new_contracts - payments_principal."""
    state = ModelState(
        registries=_registries(
            voices={"bs.nfp.lease_liability.close": _e4_voice()}
        ),
        historical_data={"bs.nfp.lease_liability.close": {"Y0": -500.0}},
        base_values={
            # Flows produced earlier in Pass 1 (or pre-seeded)
            "bs.nfp.lease_liability.new_contracts": {"Y1": -50.0},
            "bs.nfp.lease_liability.payments_principal": {"Y1": 30.0},
        },
        assumptions={"pl.financial.lease_interest": {"rate": {"Y1": 0.04}}},
        current_year="Y1",
    )

    state = phase_e4(state)

    # lease_close = -500 + (-50) - 30 = -580
    assert state.base_values["bs.nfp.lease_liability.close"]["Y1"] == -580.0
    # lease_interest = -0.04 × |-500| = -20 (uses lease_open, not close)
    assert state.base_values["pl.financial.lease_interest"]["Y1"] == -20.0


def test_e4_financial_total_net():
    """total_net = interest_expense + interest_income + lease_interest + fx_gain_loss."""
    state = ModelState(
        registries=_registries(),
        historical_data={
            "bs.nfp.borrowings.total_close": {"Y0": -1000.0},
            "bs.nfp.lease_liability.close": {"Y0": -500.0},
            "bs.nfp.cash": {"Y0": 200.0},
        },
        base_values={
            "bs.nfp.borrowings.total_close": {"Y1": -1000.0},
            # fx_gain_loss already produced by E1
            "pl.financial.fx_gain_loss": {"Y1": 5.0},
        },
        assumptions={
            "pl.financial.interest_expense": {"rate": {"Y1": 0.05}},
            "pl.financial.interest_income": {"rate": {"Y1": 0.01}},
            "pl.financial.lease_interest": {"rate": {"Y1": 0.04}},
        },
        current_year="Y1",
    )

    state = phase_e4(state)

    # interest_expense = -0.05 × 1000 = -50
    # interest_income  = +0.01 × 200  = +2
    # lease_interest   = -0.04 × 500  = -20
    # fx_gain_loss     = +5
    # total_net = -50 + 2 - 20 + 5 = -63
    assert state.base_values["pl.financial.interest_expense"]["Y1"] == -50.0
    assert state.base_values["pl.financial.interest_income"]["Y1"] == 2.0
    assert state.base_values["pl.financial.lease_interest"]["Y1"] == -20.0
    assert state.base_values["pl.financial.total_net"]["Y1"] == -63.0

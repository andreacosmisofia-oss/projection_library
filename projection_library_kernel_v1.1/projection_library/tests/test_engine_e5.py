"""Unit tests for phase_e5 (M9.7 provisions + employee benefits)."""

from __future__ import annotations

from backend.domain.engine.phases.e5_provisions_eb import phase_e5
from backend.domain.engine.value_resolver import ModelState


def test_e5_provision_rollforward():
    """balance_close = balance_open + accrual - usage - releases."""
    state = ModelState(
        # No registries → skips Pass 1 dispatch_method, runs only the
        # explicit provisions/EB logic. That's enough for this test.
        historical_data={
            "bs.provisions.warranty.balance_close": {"Y0": 50.0},
        },
        assumptions={
            "bs.provisions.warranty": {
                "accrual": {"Y1": 10.0},
                "usage": {"Y1": 5.0},
                "releases": {"Y1": 2.0},
            },
        },
        current_year="Y1",
    )

    state = phase_e5(state)

    # 50 + 10 - 5 - 2 = 53
    assert state.base_values["bs.provisions.warranty.balance_close"]["Y1"] == 53.0
    # P&L line carries the accrual as a cost
    assert state.base_values["pl.provisions.warranty"]["Y1"] == -10.0


def test_e5_provision_accrual_pct_revenue():
    """Fallback to pct_revenue × |pl.rev.net| when no direct accrual."""
    state = ModelState(
        base_values={"pl.rev.net": {"Y1": 1000.0}},
        assumptions={
            "bs.provisions.warranty": {
                "pct_revenue": {"Y1": 0.01},  # 1% of revenue
            },
        },
        current_year="Y1",
    )

    state = phase_e5(state)

    # accrual = 0.01 × 1000 = 10
    assert state.base_values["pl.provisions.warranty"]["Y1"] == -10.0
    # balance_close = 0 (no historical) + 10 - 0 - 0 = 10
    assert state.base_values["bs.provisions.warranty.balance_close"]["Y1"] == 10.0


def test_e5_provisions_total_sum():
    """pl.provisions.total = sum of pl.provisions.{family}."""
    state = ModelState(
        assumptions={
            "bs.provisions.warranty": {"accrual": {"Y1": 10.0}},
            "bs.provisions.restructuring": {"accrual": {"Y1": 20.0}},
            "bs.provisions.legal_other": {"accrual": {"Y1": 5.0}},
            # 'other' family has no accrual → contributes 0
        },
        current_year="Y1",
    )

    state = phase_e5(state)

    assert state.base_values["pl.provisions.warranty"]["Y1"] == -10.0
    assert state.base_values["pl.provisions.restructuring"]["Y1"] == -20.0
    assert state.base_values["pl.provisions.legal_other"]["Y1"] == -5.0
    assert state.base_values["pl.provisions.other"]["Y1"] == 0.0
    assert state.base_values["pl.provisions.total"]["Y1"] == -35.0
    # bs.provisions.total_close = 10 + 20 + 5 + 0 = 35 (sum of family closes)
    assert state.base_values["bs.provisions.total_close"]["Y1"] == 35.0


def test_e5_eb_service_cost():
    """service_cost = pct_labour × |pl.opex.labour.total|."""
    state = ModelState(
        base_values={"pl.opex.labour.total": {"Y1": -800.0}},  # cost stored neg
        assumptions={
            "bs.employee_benefits.balance_close": {
                "pct_labour": {"Y1": 0.05},
            },
        },
        current_year="Y1",
    )

    state = phase_e5(state)

    # 0.05 × 800 = 40
    assert state.base_values["bs.employee_benefits.service_cost"]["Y1"] == 40.0


def test_e5_eb_rollforward():
    """balance_close = open + service_cost + interest_cost - payments + actuarial."""
    state = ModelState(
        historical_data={"bs.employee_benefits.balance_close": {"Y0": 1000.0}},
        base_values={"pl.opex.labour.total": {"Y1": -800.0}},
        assumptions={
            "bs.employee_benefits.balance_close": {
                "pct_labour": {"Y1": 0.05},
                "rate": {"Y1": 0.03},
                "pct_turnover": {"Y1": 0.04},
                "actuarial": {"Y1": -10.0},
            },
        },
        current_year="Y1",
    )

    state = phase_e5(state)

    # service_cost  = 0.05 × 800   = 40
    # interest_cost = 0.03 × 1000  = 30
    # payments      = 0.04 × 1000  = 40
    # actuarial     = -10
    # balance_close = 1000 + 40 + 30 - 40 + (-10) = 1020
    assert state.base_values["bs.employee_benefits.service_cost"]["Y1"] == 40.0
    assert state.base_values["bs.employee_benefits.interest_cost"]["Y1"] == 30.0
    assert state.base_values["bs.employee_benefits.payments_to_employees"]["Y1"] == -40.0
    assert state.base_values["bs.employee_benefits.actuarial_changes"]["Y1"] == -10.0
    assert state.base_values["bs.employee_benefits.balance_close"]["Y1"] == 1020.0
    # OCI seed for E6
    assert state.base_values["bs.equity.oci_actuarial"]["Y1"] == -10.0


def test_e5_ebitda_updated_with_provisions():
    """pl.ebitda must be recomputed with the new pl.provisions.total."""
    state = ModelState(
        base_values={
            # gross_profit / opex come into E5 unchanged from E3
            "pl.gross_profit": {"Y1": 400.0},
            "pl.opex.total": {"Y1": -150.0},
            # E3 had pl.provisions.total = -10 → ebitda = 240
            "pl.provisions.total": {"Y1": -10.0},
            "pl.ebitda": {"Y1": 240.0},
        },
        assumptions={
            "bs.provisions.warranty": {"accrual": {"Y1": 50.0}},
            "bs.provisions.restructuring": {"accrual": {"Y1": 30.0}},
        },
        current_year="Y1",
    )

    state = phase_e5(state)

    # New provisions total = -50 + -30 = -80
    assert state.base_values["pl.provisions.total"]["Y1"] == -80.0
    # ebitda = gross_profit + opex + provisions = 400 - 150 - 80 = 170
    assert state.base_values["pl.ebitda"]["Y1"] == 170.0

"""Unit tests for phase_e6 (M9.8 deferred tax + equity drivers)."""

from __future__ import annotations

from backend.domain.engine.phases.e6_tax_def_equity import phase_e6
from backend.domain.engine.value_resolver import ModelState


def test_e6_dta_drift():
    """dta_close = dta_open × (1 + drift)."""
    state = ModelState(
        historical_data={"bs.tax.dta_close": {"Y0": 100.0}},
        assumptions={"bs.tax.dta_close": {"drift": {"Y1": 0.05}}},
        current_year="Y1",
    )

    state = phase_e6(state)

    assert state.base_values["bs.tax.dta_close"]["Y1"] == 105.0


def test_e6_dtl_flat_default():
    """Without a drift assumption, dtl_close stays equal to dtl_open."""
    state = ModelState(
        historical_data={"bs.tax.dtl_close": {"Y0": 200.0}},
        current_year="Y1",
    )

    state = phase_e6(state)

    assert state.base_values["bs.tax.dtl_close"]["Y1"] == 200.0


def test_e6_deferred_tax_pl_computed():
    """pl.tax.deferred = -(Δ dta) + (Δ dtl)."""
    state = ModelState(
        historical_data={
            "bs.tax.dta_close": {"Y0": 100.0},
            "bs.tax.dtl_close": {"Y0": 200.0},
        },
        assumptions={
            "bs.tax.dta_close": {"drift": {"Y1": 0.10}},  # close = 110, Δ = +10
            "bs.tax.dtl_close": {"drift": {"Y1": 0.05}},  # close = 210, Δ = +10
        },
        current_year="Y1",
    )

    state = phase_e6(state)

    # -(+10) + (+10) = 0 — DTA growth offsets DTL growth (within float ε)
    assert abs(state.base_values["pl.tax.deferred"]["Y1"]) < 1e-9

    # Asymmetric case: only DTA grows
    state2 = ModelState(
        historical_data={
            "bs.tax.dta_close": {"Y0": 100.0},
            "bs.tax.dtl_close": {"Y0": 200.0},
        },
        assumptions={
            "bs.tax.dta_close": {"drift": {"Y1": 0.10}},  # Δ = +10
        },
        current_year="Y1",
    )
    state2 = phase_e6(state2)
    # -(+10) + 0 = -10 — DTA increase reduces deferred tax expense
    assert abs(state2.base_values["pl.tax.deferred"]["Y1"] - (-10.0)) < 1e-9


def test_e6_share_capital_rollforward():
    """share_capital.close = open + capital_injections - buyback."""
    state = ModelState(
        historical_data={"bs.equity.share_capital.close": {"Y0": 1000.0}},
        assumptions={
            "bs.equity.share_capital.close": {
                "capital_injections": {"Y1": 100.0},
                "buyback": {"Y1": 30.0},
            },
        },
        current_year="Y1",
    )

    state = phase_e6(state)

    # 1000 + 100 - 30 = 1070
    assert state.base_values["bs.equity.share_capital.close"]["Y1"] == 1070.0
    assert state.base_values["bs.equity.capital_injections"]["Y1"] == 100.0
    # buyback surfaced as a negative outflow for the E7 retained-earnings identity
    assert state.base_values["bs.equity.buyback"]["Y1"] == -30.0


def test_e6_oci_with_actuarial_from_e5():
    """OCI close pulls actuarial from bs.equity.oci_actuarial seeded by E5."""
    state = ModelState(
        historical_data={"bs.equity.oci_cumulative.close": {"Y0": 50.0}},
        base_values={
            # Seeded by E5 in production
            "bs.equity.oci_actuarial": {"Y1": -10.0},
        },
        assumptions={
            "bs.equity.oci_cumulative.close": {
                "fv_hedging": {"Y1": 5.0},
                "fx": {"Y1": -2.0},
            },
        },
        current_year="Y1",
    )

    state = phase_e6(state)

    # 50 + (-10) + 5 + (-2) = 43
    assert state.base_values["bs.equity.oci_cumulative.close"]["Y1"] == 43.0


def test_e6_nci_growth():
    """nci.close = nci_open × (1 + growth); default growth=0."""
    state = ModelState(
        historical_data={"bs.equity.nci.close": {"Y0": 100.0}},
        assumptions={"bs.equity.nci.close": {"growth": {"Y1": 0.20}}},
        current_year="Y1",
    )

    state = phase_e6(state)

    assert state.base_values["bs.equity.nci.close"]["Y1"] == 120.0


def test_e6_dividends_from_prev_net_income():
    """dividends = -payout × max(0, net_income[prev_year])."""
    state = ModelState(
        # Y0 historical net_income (prev_year for Y1)
        historical_data={"pl.net_income": {"Y0": 200.0}},
        assumptions={"bs.equity.dividends": {"payout": {"Y1": 0.30}}},
        current_year="Y1",
    )

    state = phase_e6(state)

    # -0.30 × 200 = -60
    assert state.base_values["bs.equity.dividends"]["Y1"] == -60.0


def test_e6_dividends_clamped_when_prev_loss():
    """A previous-year loss results in zero dividends (max(0, ...))."""
    state = ModelState(
        historical_data={"pl.net_income": {"Y0": -50.0}},
        assumptions={"bs.equity.dividends": {"payout": {"Y1": 0.30}}},
        current_year="Y1",
    )

    state = phase_e6(state)

    assert state.base_values["bs.equity.dividends"]["Y1"] == 0.0

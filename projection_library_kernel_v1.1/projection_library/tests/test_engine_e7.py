"""Unit tests for phase_e7 (M9.9 P&L bottom + tax current + retained earnings)."""

from __future__ import annotations

from backend.domain.engine.phases.e7_pl_bottom import phase_e7
from backend.domain.engine.value_resolver import ModelState


def test_e7_ebit_from_ebitda_da():
    """ebit = ebitda + sum(pl.da.*) + sum(pl.impairment.*)."""
    state = ModelState(
        base_values={
            "pl.ebitda": {"Y1": 500.0},
            # D&A stored as negative cost
            "pl.da.ppe": {"Y1": -50.0},
            "pl.da.intangibles": {"Y1": -10.0},
            "pl.da.rou": {"Y1": -5.0},
            # Impairment partially populated
            "pl.impairment.ppe": {"Y1": -20.0},
            # impairment.intangibles & goodwill missing → default 0
        },
        current_year="Y1",
    )

    state = phase_e7(state)

    assert state.base_values["pl.da.total"]["Y1"] == -65.0
    assert state.base_values["pl.impairment.total"]["Y1"] == -20.0
    # ebit = 500 + (-65) + (-20) = 415
    assert state.base_values["pl.ebit"]["Y1"] == 415.0


def test_e7_ebt_includes_financial():
    """ebt = ebit + financial.total_net + equity_method + non_op + fv_IP."""
    state = ModelState(
        base_values={
            "pl.ebitda": {"Y1": 500.0},
            "pl.financial.total_net": {"Y1": -30.0},
            "pl.equity_method_result": {"Y1": 5.0},
            "pl.other.non_operating_recurring": {"Y1": 2.0},
            "pl.other.non_operating_extraordinary": {"Y1": -1.0},
            "pl.other.fair_value_gain_loss_investment_property": {"Y1": 3.0},
        },
        current_year="Y1",
    )

    state = phase_e7(state)

    # ebit = 500 (no D&A / impairment) → 500
    assert state.base_values["pl.ebit"]["Y1"] == 500.0
    # ebt = 500 + (-30) + 5 + (2 + -1) + 3 = 479
    assert state.base_values["pl.ebt"]["Y1"] == 479.0


def test_e7_tax_etr_simple():
    """No NOL: tax.current = -etr × max(0, ebt)."""
    state = ModelState(
        base_values={"pl.ebitda": {"Y1": 1000.0}},
        assumptions={"pl.tax.current": {"etr": {"Y1": 0.24}}},
        current_year="Y1",
    )

    state = phase_e7(state)

    # ebit = 1000, ebt = 1000 (no financial / non_op)
    assert state.base_values["pl.ebt"]["Y1"] == 1000.0
    # tax.current = -0.24 × 1000 = -240
    assert state.base_values["pl.tax.current"]["Y1"] == -240.0
    # nol_close stays at 0 (no balance) → resolve returns 0 (no historical, no base)
    assert state.base_values["bs.tax.nol_carryforward.close"]["Y1"] == 0.0


def test_e7_tax_etr_negative_ebt_clamped():
    """Negative ebt → tax.current = 0 (loss not refunded in simplified mode)."""
    state = ModelState(
        base_values={
            "pl.ebitda": {"Y1": -100.0},  # loss
        },
        assumptions={"pl.tax.current": {"etr": {"Y1": 0.24}}},
        current_year="Y1",
    )

    state = phase_e7(state)

    assert state.base_values["pl.tax.current"]["Y1"] == 0.0


def test_e7_tax_nol_reduces_taxable():
    """nol_open=200, ebt=100, ebt×0.8=80 → nol_used=80, taxable=20.

    With etr=0.25: tax.current = -0.25 × 20 = -5
    nol_close = 200 - 80 = 120
    """
    state = ModelState(
        historical_data={"bs.tax.nol_carryforward.close": {"Y0": 200.0}},
        base_values={"pl.ebitda": {"Y1": 100.0}},
        assumptions={"pl.tax.current": {"etr": {"Y1": 0.25}}},
        current_year="Y1",
    )

    state = phase_e7(state)

    assert state.base_values["pl.tax.current"]["Y1"] == -5.0
    assert state.base_values["bs.tax.nol_carryforward.close"]["Y1"] == 120.0


def test_e7_tax_nol_smaller_than_cap():
    """When nol_open is smaller than 80% × ebt, the whole NOL is consumed."""
    state = ModelState(
        historical_data={"bs.tax.nol_carryforward.close": {"Y0": 50.0}},
        base_values={"pl.ebitda": {"Y1": 100.0}},
        assumptions={"pl.tax.current": {"etr": {"Y1": 0.25}}},
        current_year="Y1",
    )

    state = phase_e7(state)

    # nol_used = min(50, 80) = 50 ; taxable = 100 - 50 = 50 ; tax = -0.25 × 50 = -12.5
    assert state.base_values["pl.tax.current"]["Y1"] == -12.5
    assert state.base_values["bs.tax.nol_carryforward.close"]["Y1"] == 0.0


def test_e7_net_income_computed():
    """tax.total = tax.current + tax.deferred (E6); net_income = ebt + tax.total."""
    state = ModelState(
        base_values={
            "pl.ebitda": {"Y1": 1000.0},
            "pl.tax.deferred": {"Y1": -10.0},  # seeded by E6
        },
        assumptions={"pl.tax.current": {"etr": {"Y1": 0.24}}},
        current_year="Y1",
    )

    state = phase_e7(state)

    # ebt = 1000, tax.current = -240, tax.deferred = -10
    assert state.base_values["pl.tax.current"]["Y1"] == -240.0
    assert state.base_values["pl.tax.total"]["Y1"] == -250.0
    # net_income = 1000 + (-250) = 750
    assert state.base_values["pl.net_income"]["Y1"] == 750.0
    # adjusted metrics placeholder = headline values
    assert state.base_values["pl.ebitda_adjusted"]["Y1"] == 1000.0
    assert state.base_values["pl.ebit_adjusted"]["Y1"] == 1000.0


def test_e7_retained_earnings_rollforward():
    """re.close = re_open + net_income + dividends + buyback."""
    state = ModelState(
        historical_data={"bs.equity.retained_earnings.close": {"Y0": 2000.0}},
        base_values={
            "pl.ebitda": {"Y1": 1000.0},
            "pl.tax.deferred": {"Y1": -10.0},
            # Seeded by E6
            "bs.equity.dividends": {"Y1": -100.0},
            "bs.equity.buyback": {"Y1": -50.0},
        },
        assumptions={"pl.tax.current": {"etr": {"Y1": 0.24}}},
        current_year="Y1",
    )

    state = phase_e7(state)

    # net_income = 750 (same arithmetic as the previous test)
    assert state.base_values["pl.net_income"]["Y1"] == 750.0
    # re.close = 2000 + 750 + (-100) + (-50) = 2600
    assert state.base_values["bs.equity.retained_earnings.close"]["Y1"] == 2600.0

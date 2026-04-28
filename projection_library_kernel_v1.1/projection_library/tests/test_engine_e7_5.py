"""Unit tests for phase_e7_5 (M9.10 CIT NWC + NWC operating final)."""

from __future__ import annotations

from backend.domain.engine.phases.e7_5_cit_nwc import phase_e7_5
from backend.domain.engine.value_resolver import ModelState


def test_e7_5_cit_payable_when_tax_increases():
    """Tax magnitude grows ⇒ cit_amount negative ⇒ payable booked."""
    state = ModelState(
        # E7's convention stores tax.current as a negative cost; |tax| grows
        # from 100 (Y0) to 150 (Y1), so the company owes 50 more.
        historical_data={"pl.tax.current": {"Y0": -100.0}},
        base_values={"pl.tax.current": {"Y1": -150.0}},
        current_year="Y1",
    )

    state = phase_e7_5(state)

    # cit_amount = -(150 - 100) = -50 → payable
    assert state.base_values["bs.nwc.other_current_liab.cit_payable"]["Y1"] == -50.0
    assert (
        state.base_values["bs.nwc.other_current_assets.cit_receivable"]["Y1"]
        == 0.0
    )


def test_e7_5_cit_receivable_when_tax_decreases():
    """Tax magnitude shrinks ⇒ cit_amount positive ⇒ receivable booked."""
    state = ModelState(
        historical_data={"pl.tax.current": {"Y0": -150.0}},
        base_values={"pl.tax.current": {"Y1": -100.0}},
        current_year="Y1",
    )

    state = phase_e7_5(state)

    # cit_amount = -(100 - 150) = +50 → receivable
    assert (
        state.base_values["bs.nwc.other_current_assets.cit_receivable"]["Y1"]
        == 50.0
    )
    assert state.base_values["bs.nwc.other_current_liab.cit_payable"]["Y1"] == 0.0


def test_e7_5_other_current_subtotals():
    """OCA and OCL subtotals sum the leaf voices, including the CIT split."""
    state = ModelState(
        historical_data={"pl.tax.current": {"Y0": -100.0}},
        base_values={
            "pl.tax.current": {"Y1": -150.0},  # CIT payable = -50
            # Other leaves seeded by previous phases / dispatch
            "bs.nwc.other_current_assets.vat_receivable": {"Y1": 30.0},
            "bs.nwc.other_current_assets.other": {"Y1": 5.0},
            "bs.nwc.other_current_liab.vat_payable": {"Y1": -20.0},
            "bs.nwc.other_current_liab.other": {"Y1": -3.0},
        },
        current_year="Y1",
    )

    state = phase_e7_5(state)

    # OCA = vat (30) + cit_receivable (0) + other (5) = 35
    assert state.base_values["bs.nwc.other_current_assets"]["Y1"] == 35.0
    # OCL = vat (-20) + cit_payable (-50) + other (-3) = -73
    assert state.base_values["bs.nwc.other_current_liab"]["Y1"] == -73.0


def test_e7_5_nwc_operating_final_sums_components():
    """bs.nwc.operating sums every operating NWC component algebraically."""
    state = ModelState(
        base_values={
            "bs.nwc.ar.trade_gross": {"Y1": 600.0},
            "bs.nwc.ar.allowance": {"Y1": -10.0},
            "bs.nwc.inventory.total": {"Y1": 450.0},
            "bs.nwc.other_current_assets.vat_receivable": {"Y1": 30.0},
            "bs.nwc.other_current_liab.vat_payable": {"Y1": -20.0},
            "bs.nwc.ap.trade": {"Y1": -300.0},
            "bs.nwc.accrued_expenses": {"Y1": -40.0},
            "bs.nwc.prepayments": {"Y1": 15.0},
            "bs.nwc.contract_assets": {"Y1": 25.0},
            "bs.nwc.contract_liabilities": {"Y1": -50.0},
        },
        current_year="Y1",
    )

    state = phase_e7_5(state)

    # CIT inputs zero (tax.current resolves to 0 in both years), so OCA / OCL
    # match their seeded vat lines.
    # Sum: 600 - 10 + 450 + 30 - 20 - 300 - 40 + 15 + 25 - 50 = 700
    assert state.base_values["bs.nwc.operating"]["Y1"] == 700.0


def test_e7_5_nwc_replaces_e3_proxy():
    """Whatever E3 left in bs.nwc.operating must be overwritten by the final."""
    state = ModelState(
        base_values={
            # E3 proxy (e.g., a placeholder value)
            "bs.nwc.operating": {"Y1": 999.0},
            # New components — these dictate the final value
            "bs.nwc.ar.trade_gross": {"Y1": 100.0},
            "bs.nwc.ap.trade": {"Y1": -50.0},
            "bs.nwc.inventory.total": {"Y1": 200.0},
        },
        current_year="Y1",
    )

    state = phase_e7_5(state)

    # 100 - 50 + 200 = 250 (other components default to 0)
    assert state.base_values["bs.nwc.operating"]["Y1"] == 250.0
    # And the proxy 999 is gone
    assert state.base_values["bs.nwc.operating"]["Y1"] != 999.0

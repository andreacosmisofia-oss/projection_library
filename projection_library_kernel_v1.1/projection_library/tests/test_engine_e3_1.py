"""Unit tests for phase_e3_1 (M9.5 IFRS 15 adjustments)."""

from __future__ import annotations

from backend.domain.engine.phases.e3_1_ifrs15 import phase_e3_1
from backend.domain.engine.value_resolver import ModelState


def test_e3_1_no_ifrs15_voices_passthrough():
    """Without contract_liab/contract_assets in base_values, pl.rev.net
    keeps its E1 proxy and no adjustment voices are written."""
    state = ModelState(
        base_values={"pl.rev.net": {"Y1": 1000.0}},
        # An historical-only contract balance must NOT trigger the
        # adjustment (the spec checks base_values only).
        historical_data={
            "bs.nwc.contract_liabilities": {"Y0": 50.0},
        },
        current_year="Y1",
    )

    state = phase_e3_1(state)

    assert state.base_values["pl.rev.net"]["Y1"] == 1000.0
    for voice in (
        "pl.rev.adjustments.deferred_movement",
        "pl.rev.adjustments.contract_asset_movement",
        "pl.rev.adjustments_total",
    ):
        assert voice not in state.base_values


def test_e3_1_deferred_revenue_increase_reduces_revenue():
    """Δ contract_liabilities = +50 ⇒ deferred_movement = -50; rev.net -50."""
    state = ModelState(
        base_values={
            "pl.rev.net": {"Y1": 1000.0},
            "bs.nwc.contract_liabilities": {"Y1": 150.0},
        },
        historical_data={
            "bs.nwc.contract_liabilities": {"Y0": 100.0},
        },
        current_year="Y1",
    )

    state = phase_e3_1(state)

    assert state.base_values["pl.rev.adjustments.deferred_movement"]["Y1"] == -50.0
    assert (
        state.base_values["pl.rev.adjustments.contract_asset_movement"]["Y1"]
        == 0.0
    )
    assert state.base_values["pl.rev.adjustments_total"]["Y1"] == -50.0
    assert state.base_values["pl.rev.net"]["Y1"] == 950.0


def test_e3_1_contract_asset_increase_boosts_revenue():
    """Δ contract_assets = +60 ⇒ contract_asset_movement = +60; rev.net +60."""
    state = ModelState(
        base_values={
            "pl.rev.net": {"Y1": 1000.0},
            "bs.nwc.contract_assets": {"Y1": 80.0},
        },
        historical_data={
            "bs.nwc.contract_assets": {"Y0": 20.0},
        },
        current_year="Y1",
    )

    state = phase_e3_1(state)

    assert (
        state.base_values["pl.rev.adjustments.contract_asset_movement"]["Y1"]
        == 60.0
    )
    assert state.base_values["pl.rev.adjustments.deferred_movement"]["Y1"] == 0.0
    assert state.base_values["pl.rev.adjustments_total"]["Y1"] == 60.0
    assert state.base_values["pl.rev.net"]["Y1"] == 1060.0


def test_e3_1_updates_gross_profit_and_ebitda():
    """After IFRS 15 adjustment, gross_profit and ebitda must be
    re-aggregated with the updated pl.rev.net."""
    state = ModelState(
        base_values={
            # E1 + E3 final state coming into E3.1
            "pl.rev.net": {"Y1": 1000.0},
            "pl.cogs.total": {"Y1": -600.0},
            "pl.opex.total": {"Y1": -150.0},
            "pl.provisions.total": {"Y1": -20.0},
            # Stale E3 aggregates that E3.1 must overwrite
            "pl.gross_profit": {"Y1": 400.0},
            "pl.ebitda": {"Y1": 230.0},
            # Trigger the IFRS 15 path
            "bs.nwc.contract_liabilities": {"Y1": 150.0},
            "bs.nwc.contract_assets": {"Y1": 30.0},
        },
        historical_data={
            "bs.nwc.contract_liabilities": {"Y0": 100.0},
            "bs.nwc.contract_assets": {"Y0": 20.0},
        },
        current_year="Y1",
    )

    state = phase_e3_1(state)

    # deferred_movement = -50, contract_asset_movement = +10 → total = -40
    assert state.base_values["pl.rev.adjustments_total"]["Y1"] == -40.0
    # rev.net final = 1000 + (-40) = 960
    assert state.base_values["pl.rev.net"]["Y1"] == 960.0
    # gross_profit = 960 + (-600) = 360
    assert state.base_values["pl.gross_profit"]["Y1"] == 360.0
    # ebitda = 360 + (-150) + (-20) = 190
    assert state.base_values["pl.ebitda"]["Y1"] == 190.0

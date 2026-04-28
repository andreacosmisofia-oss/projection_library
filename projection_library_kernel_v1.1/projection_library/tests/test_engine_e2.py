"""Unit tests for phase_e2 (M9.3 fixed assets + D&A + impairment + IP fv)."""

from __future__ import annotations

from types import SimpleNamespace

from backend.domain.engine.phases.e2_fa_da import phase_e2
from backend.domain.engine.value_resolver import ModelState


def _registries(voices: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        voices=voices or {},
        methods={},
        derived_rules={},
    )


def _e2_voice(default_method: str | None = None) -> dict:
    return {
        "calc_phase_final": "E2",
        "calc_phase_proxy": None,
        "default_method": default_method,
    }


def test_e2_tangible_gross_rollforward():
    """gross_close = open(prev_year) + maintenance_capex - abs(disposals_gross)."""
    state = ModelState(
        registries=_registries(
            voices={"bs.fa.tangible.gross_close": _e2_voice()}
        ),
        historical_data={"bs.fa.tangible.gross_close": {"Y0": 1000.0}},
        # Inflows / outflows pre-populated as if their own driver methods
        # had already run. In production these voices have nature=driver
        # and are computed by dispatch_method earlier in the same phase
        # (registry YAML order puts capex/disposals before gross_close).
        base_values={
            "bs.fa.tangible.maintenance_capex": {"Y1": 200.0},
            "bs.fa.tangible.disposals_gross": {"Y1": -50.0},
        },
        current_year="Y1",
    )

    state = phase_e2(state)

    assert state.base_values["bs.fa.tangible.gross_close"]["Y1"] == 1150.0


def test_e2_da_mid_year_convention():
    """D&A = -max(0, gross_avg - non_depreciable) / useful_life.

    With Y0 close = 1000, Y1 close = 1100, useful_life = 20 (PPE default),
    non_depreciable_pct = 0:
        gross_avg = 1050
        D&A = -1050 / 20 = -52.5
    """
    state = ModelState(
        registries=_registries(voices={"pl.da.ppe": _e2_voice()}),
        historical_data={"bs.fa.tangible.gross_close": {"Y0": 1000.0}},
        base_values={"bs.fa.tangible.gross_close": {"Y1": 1100.0}},
        current_year="Y1",
    )

    state = phase_e2(state)

    assert state.base_values["pl.da.ppe"]["Y1"] == -52.5


def test_e2_da_mid_year_with_non_depreciable():
    """non_depreciable_pct shrinks the depreciable base."""
    state = ModelState(
        registries=_registries(voices={"pl.da.ppe": _e2_voice()}),
        historical_data={"bs.fa.tangible.gross_close": {"Y0": 1000.0}},
        base_values={"bs.fa.tangible.gross_close": {"Y1": 1000.0}},
        # 10% of the gross average is land (non depreciable) → depreciable
        # base = 900, useful_life = 10 → D&A = -90
        assumptions={
            "pl.da.ppe": {
                "useful_life": {"Y1": 10},
                "non_depreciable_pct": {"Y1": 0.10},
            }
        },
        current_year="Y1",
    )

    state = phase_e2(state)

    assert state.base_values["pl.da.ppe"]["Y1"] == -90.0


def test_e2_da_rou_requires_assumption():
    """ROU depreciation has no static default useful_life — without the
    assumption the helper safely returns 0."""
    state = ModelState(
        registries=_registries(voices={"pl.da.rou": _e2_voice()}),
        historical_data={"bs.fa.rou.gross_close": {"Y0": 600.0}},
        base_values={"bs.fa.rou.gross_close": {"Y1": 600.0}},
        current_year="Y1",
    )
    state = phase_e2(state)
    assert state.base_values["pl.da.rou"]["Y1"] == 0.0

    # With an explicit assumption (5-year lease), D&A = -600 / 5 = -120
    state2 = ModelState(
        registries=_registries(voices={"pl.da.rou": _e2_voice()}),
        historical_data={"bs.fa.rou.gross_close": {"Y0": 600.0}},
        base_values={"bs.fa.rou.gross_close": {"Y1": 600.0}},
        assumptions={"pl.da.rou": {"useful_life": {"Y1": 5}}},
        current_year="Y1",
    )
    state2 = phase_e2(state2)
    assert state2.base_values["pl.da.rou"]["Y1"] == -120.0


def test_e2_intangible_rollforward():
    """gross_close = open + software_capex - abs(disposals_gross)."""
    state = ModelState(
        registries=_registries(
            voices={"bs.fa.intangible.gross_close": _e2_voice()}
        ),
        historical_data={"bs.fa.intangible.gross_close": {"Y0": 500.0}},
        base_values={
            "bs.fa.intangible.software_capex": {"Y1": 80.0},
            "bs.fa.intangible.disposals_gross": {"Y1": -20.0},
        },
        current_year="Y1",
    )

    state = phase_e2(state)

    assert state.base_values["bs.fa.intangible.gross_close"]["Y1"] == 560.0


def test_e2_ip_fair_value_movement():
    """IP gross_close = fv_open + revaluation; the P&L line mirrors it."""
    state = ModelState(
        registries=_registries(
            voices={
                "bs.fa.investment_property.gross_close": _e2_voice(),
                "pl.other.fair_value_gain_loss_investment_property": _e2_voice(),
            }
        ),
        historical_data={
            "bs.fa.investment_property.gross_close": {"Y0": 5000.0},
        },
        assumptions={
            "bs.fa.investment_property.gross_close": {
                "fv_revaluation": {"Y1": 200.0},
            },
        },
        current_year="Y1",
    )

    state = phase_e2(state)

    assert (
        state.base_values["bs.fa.investment_property.gross_close"]["Y1"]
        == 5200.0
    )
    assert (
        state.base_values[
            "pl.other.fair_value_gain_loss_investment_property"
        ]["Y1"]
        == 200.0
    )


def test_e2_skips_non_e2_voices():
    """phase_e2 must not touch voices tagged for other phases."""
    state = ModelState(
        registries=_registries(
            voices={
                "pl.rev.net": {
                    "calc_phase_final": "E1",
                    "calc_phase_proxy": None,
                    "default_method": "flat",
                },
                "bs.nfp.cash": {
                    "calc_phase_final": "E8",
                    "calc_phase_proxy": None,
                    "default_method": None,
                },
                "bs.fa.investment_property.gross_close": _e2_voice(),
            }
        ),
        historical_data={
            "pl.rev.net": {"Y0": 1000.0},
            "bs.nfp.cash": {"Y0": 200.0},
            "bs.fa.investment_property.gross_close": {"Y0": 5000.0},
        },
        current_year="Y1",
    )

    state = phase_e2(state)

    # Only the E2 voice should have been written
    assert "pl.rev.net" not in state.base_values
    assert "bs.nfp.cash" not in state.base_values
    assert "bs.fa.investment_property.gross_close" in state.base_values

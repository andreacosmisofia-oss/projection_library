"""Unit tests for phase_e3 (M9.4 NWC + COGS final + EBITDA final)."""

from __future__ import annotations

from types import SimpleNamespace

from backend.domain.engine.phases.e3_nwc import phase_e3
from backend.domain.engine.value_resolver import ModelState


def _registries(voices: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        voices=voices or {},
        methods={},
        derived_rules={},
    )


def _e3_voice() -> dict:
    return {
        "calc_phase_final": "E3",
        "calc_phase_proxy": None,
        "default_method": None,
    }


def test_e3_ar_dso_driven():
    """AR.trade_gross = dso × pl.rev.net[year] / 365."""
    state = ModelState(
        registries=_registries(
            voices={"bs.nwc.ar.trade_gross": _e3_voice()}
        ),
        # E1 has already materialised pl.rev.net for Y1
        base_values={"pl.rev.net": {"Y1": 3650.0}},
        assumptions={"bs.nwc.ar.trade_gross": {"dso_days": {"Y1": 60}}},
        current_year="Y1",
    )

    state = phase_e3(state)

    # 60 × 3650 / 365 = 600
    assert state.base_values["bs.nwc.ar.trade_gross"]["Y1"] == 600.0


def test_e3_ap_dpo_driven():
    """AP.trade = -dpo × abs(pl.cogs.total[year]) / 365 (negative balance)."""
    state = ModelState(
        registries=_registries(voices={"bs.nwc.ap.trade": _e3_voice()}),
        base_values={"pl.cogs.total": {"Y1": -1825.0}},  # E1 proxy, signed neg
        assumptions={"bs.nwc.ap.trade": {"dpo_days": {"Y1": 90}}},
        current_year="Y1",
    )

    state = phase_e3(state)

    # -90 × |-1825| / 365 = -450
    assert state.base_values["bs.nwc.ap.trade"]["Y1"] == -450.0


def test_e3_inventory_dio_driven():
    """Inventory.total = dio × abs(pl.cogs.total[year]) / 365."""
    state = ModelState(
        registries=_registries(
            voices={"bs.nwc.inventory.total": _e3_voice()}
        ),
        base_values={"pl.cogs.total": {"Y1": -3650.0}},
        assumptions={"bs.nwc.inventory.total": {"dio_days": {"Y1": 45}}},
        current_year="Y1",
    )

    state = phase_e3(state)

    # 45 × |-3650| / 365 = 450
    assert state.base_values["bs.nwc.inventory.total"]["Y1"] == 450.0


def test_e3_fallback_dso_from_historical():
    """When no DSO assumption is set, use the days implied by Y0 actuals."""
    state = ModelState(
        registries=_registries(
            voices={"bs.nwc.ar.trade_gross": _e3_voice()}
        ),
        # Y0 actuals: balance 200, revenue 2000 → implied DSO = 200×365/2000 = 36.5
        historical_data={
            "bs.nwc.ar.trade_gross": {"Y0": 200.0},
            "pl.rev.net": {"Y0": 2000.0},
        },
        base_values={"pl.rev.net": {"Y1": 4000.0}},  # revenue doubles in Y1
        # NB: assumptions intentionally empty for this voice
        current_year="Y1",
    )

    state = phase_e3(state)

    # implied_dso × 4000 / 365 = 36.5 × 4000 / 365 = 400
    assert state.base_values["bs.nwc.ar.trade_gross"]["Y1"] == 400.0


def test_e3_cogs_final_replaces_proxy():
    """pl.cogs.total final = E1 proxy + writeoff + wip_cap."""
    voices = {
        # Inventory.total + inventory.wip computed in NWC pass
        "bs.nwc.inventory.total": _e3_voice(),
        "bs.nwc.inventory.wip": _e3_voice(),
        # Then writeoff/wip_cap, then pl.cogs.total
        "pl.cogs.inventory_writeoff": _e3_voice(),
        "pl.cogs.wip_capitalization": _e3_voice(),
        "pl.cogs.total": _e3_voice(),
    }
    state = ModelState(
        registries=_registries(voices=voices),
        # E1 proxy already in place
        base_values={
            "pl.cogs.total": {"Y1": -2000.0},  # E1 proxy
        },
        historical_data={
            "bs.nwc.inventory.total": {"Y0": 400.0},
            "bs.nwc.inventory.wip": {"Y0": 100.0},
            "pl.cogs.total": {"Y0": -3650.0},
        },
        assumptions={
            "bs.nwc.inventory.total": {"dio_days": {"Y1": 50}},
            # WIP: dispatch_method falls back; without a method we
            # leave wip at its prev-year (=Y0 historical) by skipping.
            # We seed Y1 directly via base_values for determinism.
            "pl.cogs.inventory_writeoff": {"rate": {"Y1": 0.05}},
        },
        current_year="Y1",
    )

    # Pre-seed inventory.wip Y1 so wip_cap has a well-defined delta
    state.base_values.setdefault("bs.nwc.inventory.wip", {})["Y1"] = 130.0
    # NB: the registry-driven leaf inventory voices would normally
    # carry their own days_target — we shortcut via base_values for
    # the test instead.

    state = phase_e3(state)

    # NWC pass: inventory.total Y1 = 50 × |-2000| × ??? wait - pl.cogs.total
    # is read from base_values which still has the E1 proxy at this point.
    # That's the intended behaviour: NWC reads the *current* pl.cogs.total
    # before the COGS-adjustment pass replaces it.
    # 50 × |-2000| / 365 = 273.97...
    inv_total_y1 = state.base_values["bs.nwc.inventory.total"]["Y1"]
    assert abs(inv_total_y1 - (50 * 2000 / 365)) < 1e-6

    # writeoff = -0.05 × (400 + inv_total_y1) / 2
    expected_writeoff = -0.05 * (400 + inv_total_y1) / 2
    assert (
        abs(state.base_values["pl.cogs.inventory_writeoff"]["Y1"] - expected_writeoff)
        < 1e-9
    )

    # wip_cap = -(130 - 100) = -30
    assert state.base_values["pl.cogs.wip_capitalization"]["Y1"] == -30.0

    # pl.cogs.total final = -2000 + writeoff + (-30)
    expected_cogs_final = -2000.0 + expected_writeoff + (-30.0)
    assert (
        abs(state.base_values["pl.cogs.total"]["Y1"] - expected_cogs_final)
        < 1e-9
    )


def test_e3_ebitda_final_computed():
    """ebitda final = gross_profit + opex.total + provisions.total."""
    voices = {
        "pl.cogs.inventory_writeoff": _e3_voice(),
        "pl.cogs.wip_capitalization": _e3_voice(),
        "pl.cogs.total": _e3_voice(),
        "pl.gross_profit": _e3_voice(),
        "pl.ebitda": _e3_voice(),
    }
    state = ModelState(
        registries=_registries(voices=voices),
        base_values={
            "pl.rev.net": {"Y1": 1000.0},
            "pl.cogs.total": {"Y1": -600.0},  # E1 proxy
            "pl.opex.total": {"Y1": -150.0},
            "pl.provisions.total": {"Y1": -20.0},
        },
        # No writeoff / wip_cap assumptions → both default to 0
        current_year="Y1",
    )

    state = phase_e3(state)

    # writeoff and wip_cap default to 0 → pl.cogs.total final stays at -600
    assert state.base_values["pl.cogs.total"]["Y1"] == -600.0
    # pl.gross_profit = 1000 + (-600) = 400
    assert state.base_values["pl.gross_profit"]["Y1"] == 400.0
    # pl.ebitda = 400 + (-150) + (-20) = 230
    assert state.base_values["pl.ebitda"]["Y1"] == 230.0


def test_e3_skips_non_e3_voices():
    """phase_e3 must leave voices in other phases untouched."""
    state = ModelState(
        registries=_registries(
            voices={
                "pl.rev.net": {
                    "calc_phase_final": "E3_1",
                    "calc_phase_proxy": "E1",
                    "default_method": "subtotal_aggregation",
                },
                "bs.fa.tangible.gross_close": {
                    "calc_phase_final": "E2",
                    "calc_phase_proxy": None,
                    "default_method": None,
                },
                "bs.nwc.ar.trade_gross": _e3_voice(),
            }
        ),
        base_values={"pl.rev.net": {"Y1": 1000.0}},
        assumptions={"bs.nwc.ar.trade_gross": {"dso_days": {"Y1": 30}}},
        current_year="Y1",
    )

    state = phase_e3(state)

    assert "pl.rev.net" not in state.base_values or state.base_values["pl.rev.net"] == {"Y1": 1000.0}
    assert "bs.fa.tangible.gross_close" not in state.base_values
    assert "bs.nwc.ar.trade_gross" in state.base_values

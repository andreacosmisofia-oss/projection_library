"""Unit tests for phase_e1 (M9.2 P&L driver core)."""

from __future__ import annotations

from types import SimpleNamespace

from backend.domain.engine.phases.e1_pl_driver import phase_e1
from backend.domain.engine.value_resolver import ModelState


def _registries(
    voices: dict | None = None,
    methods: dict | None = None,
    derived_rules: dict | None = None,
) -> SimpleNamespace:
    """Minimal registry stub: only the slots E1 reads."""
    return SimpleNamespace(
        voices=voices or {},
        methods=methods or {},
        derived_rules=derived_rules or {},
    )


def _voice(default_method: str | None, *, phase: str = "calc_phase_final") -> dict:
    meta = {"calc_phase_final": None, "calc_phase_proxy": None}
    meta[phase] = "E1"
    meta["default_method"] = default_method
    return meta


_GROWTH_FORMULA = (
    "resolve(voice, prev_year) * "
    "(1 + assumptions[voice]['growth_rate'][year])"
)
_FLAT_FORMULA = "resolve(voice, prev_year)"
_PCT_NET_REVENUE_FORMULA = (
    "assumptions[voice]['pct'][year] * resolve('pl.rev.net', year)"
)


def test_e1_revenue_historical_avg_growth():
    state = ModelState(
        registries=_registries(
            voices={"pl.rev.net": _voice("historical_avg_growth")},
            methods={
                "historical_avg_growth": {"formula_python": _GROWTH_FORMULA},
            },
        ),
        historical_data={"pl.rev.net": {"Y0": 1000.0}},
        assumptions={"pl.rev.net": {"growth_rate": {"Y1": 0.10}}},
        current_year="Y1",
    )

    state = phase_e1(state)

    assert state.base_values["pl.rev.net"]["Y1"] == 1100.0


def test_e1_revenue_flat():
    state = ModelState(
        registries=_registries(
            voices={"pl.rev.gross.subscription": _voice("flat")},
            methods={"flat": {"formula_python": _FLAT_FORMULA}},
        ),
        historical_data={"pl.rev.gross.subscription": {"Y0": 500.0}},
        current_year="Y1",
    )

    state = phase_e1(state)

    assert state.base_values["pl.rev.gross.subscription"]["Y1"] == 500.0


def test_e1_cogs_pct_net_revenue():
    """COGS that depends on pl.rev.net resolved earlier in the same phase."""
    voices = {
        # Insertion order matters: pl.rev.net is materialised before
        # the cogs voice that references it. The real registry has
        # the same ordering for pl.rev.* before pl.cogs.*.
        "pl.rev.net": _voice("flat"),
        "pl.cogs.materials.raw": _voice("pct_net_revenue"),
    }
    methods = {
        "flat": {"formula_python": _FLAT_FORMULA},
        "pct_net_revenue": {"formula_python": _PCT_NET_REVENUE_FORMULA},
    }
    state = ModelState(
        registries=_registries(voices=voices, methods=methods),
        historical_data={"pl.rev.net": {"Y0": 1000.0}},
        assumptions={
            "pl.cogs.materials.raw": {"pct": {"Y1": -0.4}},
        },
        current_year="Y1",
    )

    state = phase_e1(state)

    assert state.base_values["pl.rev.net"]["Y1"] == 1000.0
    assert state.base_values["pl.cogs.materials.raw"]["Y1"] == -400.0


def test_e1_skips_voice_without_method_config():
    """A voice without a method_config and without registry default_method
    is skipped silently — no entry in base_values."""
    voices = {
        "pl.opex.ga.travel": _voice(default_method=None),
    }
    methods = {"flat": {"formula_python": _FLAT_FORMULA}}
    state = ModelState(
        registries=_registries(voices=voices, methods=methods),
        historical_data={"pl.opex.ga.travel": {"Y0": 100.0}},
        current_year="Y1",
    )

    state = phase_e1(state)

    assert "pl.opex.ga.travel" not in state.base_values

    # And a non-E1 voice is also skipped (calc_phase_final doesn't match)
    state2 = ModelState(
        registries=_registries(
            voices={
                "bs.fa.tangible.net_close": {
                    "calc_phase_final": "E2",
                    "calc_phase_proxy": None,
                    "default_method": "flat",
                },
            },
            methods=methods,
        ),
        historical_data={"bs.fa.tangible.net_close": {"Y0": 5000.0}},
        current_year="Y1",
    )

    state2 = phase_e1(state2)

    assert "bs.fa.tangible.net_close" not in state2.base_values


def test_e1_prev_year_resolution_y2():
    """Y2 must read prev_year=Y1 from base_values (engine output of the
    previous year-loop iteration), not from historical_data."""
    state = ModelState(
        registries=_registries(
            voices={"pl.rev.gross.product_sales": _voice("historical_avg_growth")},
            methods={
                "historical_avg_growth": {"formula_python": _GROWTH_FORMULA},
            },
        ),
        historical_data={"pl.rev.gross.product_sales": {"Y0": 1000.0}},
        assumptions={
            "pl.rev.gross.product_sales": {
                "growth_rate": {"Y1": 0.10, "Y2": 0.20},
            }
        },
    )

    state.current_year = "Y1"
    state = phase_e1(state)
    assert state.base_values["pl.rev.gross.product_sales"]["Y1"] == 1100.0

    state.current_year = "Y2"
    state = phase_e1(state)
    # Y2 = base_values[Y1] * 1.20 = 1100 * 1.20 = 1320
    assert state.base_values["pl.rev.gross.product_sales"]["Y2"] == 1320.0


def test_e1_user_method_config_overrides_default():
    """When a method_config exists for a voice it wins over default_method."""
    voices = {"pl.rev.net": _voice("flat")}
    methods = {
        "flat": {"formula_python": _FLAT_FORMULA},
        "historical_avg_growth": {"formula_python": _GROWTH_FORMULA},
    }
    state = ModelState(
        registries=_registries(voices=voices, methods=methods),
        historical_data={"pl.rev.net": {"Y0": 1000.0}},
        assumptions={"pl.rev.net": {"growth_rate": {"Y1": 0.05}}},
        method_configs={
            "pl.rev.net": SimpleNamespace(method_id="historical_avg_growth"),
        },
        current_year="Y1",
    )

    state = phase_e1(state)

    # User-configured method (growth 5%) wins over registry default ("flat")
    assert state.base_values["pl.rev.net"]["Y1"] == 1050.0

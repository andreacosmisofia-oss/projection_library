"""Unit tests for ``backend.domain.assumptions.populator``."""

from __future__ import annotations

from backend.domain.assumptions.populator import (
    SOURCE_DEFAULT_KPI,
    SOURCE_FALLBACK,
    compute_assumption_defaults,
    compute_template_kpi_fallback,
    resolve_default_kpi,
)
from backend.domain.intake.mapping_resolver import MappedValues
from backend.infrastructure.registry.loader import Registries


def _empty_registries(**overrides) -> Registries:
    """Make a minimally-shaped :class:`Registries` for unit tests.

    Only the fields the populator touches need real data; the rest stay
    empty.
    """
    base = dict(
        voices={},
        methods={},
        methods_by_tech_code={},
        derived_rules={},
        derived_rules_by_tech_code={},
        kpis={},
        validation_rules={},
        validation_rules_by_phase={},
        sector_packs={},
        sector_custom_kpis=[],
        voice_dependencies={},
        override_policies=[],
        required_data=[],
    )
    base.update(overrides)
    return Registries(**base)


# ---------------------------------------------------------------------------
# resolve_default_kpi
# ---------------------------------------------------------------------------


def test_resolve_default_kpi_substitutes_voice():
    assert (
        resolve_default_kpi("kpi.growth.<voice>_yoy", "pl.rev.gross.product_sales")
        == "kpi.growth.pl.rev.gross.product_sales_yoy"
    )


def test_resolve_default_kpi_handles_null_markers():
    assert resolve_default_kpi(None, "x") is None
    assert resolve_default_kpi("—", "x") is None
    assert resolve_default_kpi("", "x") is None


def test_resolve_default_kpi_strips_parenthetical():
    out = resolve_default_kpi("kpi.saas.new_arr_rate (e altri)", "x")
    assert out == "kpi.saas.new_arr_rate"


def test_resolve_default_kpi_returns_none_on_unsupported_placeholder():
    # Other angle-brackets placeholders (e.g. <segment>) cannot be resolved
    # from a voice id alone — populator falls back to zero.
    assert resolve_default_kpi("kpi.foo.<segment>_bar", "voice.x") is None


# ---------------------------------------------------------------------------
# compute_template_kpi_fallback
# ---------------------------------------------------------------------------


def _mapped(values: dict[str, dict[str, float]], lfl_years: list[str]):
    years_present = sorted({y for v in values.values() for y in v.keys()})
    return MappedValues(
        project_id="p",
        values=values,
        years_present=years_present,
        years_lfl=lfl_years,
    )


def test_template_kpi_fallback_growth_yoy():
    mapped = _mapped(
        {"pl.rev.gross.x": {"Y-1": 100.0, "Y0": 110.0}},
        lfl_years=["Y-1", "Y0"],
    )
    out = compute_template_kpi_fallback(
        "kpi.growth.pl.rev.gross.x_yoy", "pl.rev.gross.x", mapped
    )
    assert out is not None
    value, calibration = out
    assert value == 0.10
    # 2 LFL years → 0.7 calibration.
    assert calibration == 0.7


def test_template_kpi_fallback_margin_pct_revenue():
    mapped = _mapped(
        {
            "pl.cogs.materials": {"Y0": -40.0},
            "pl.rev.net": {"Y0": 100.0},
        },
        lfl_years=["Y0"],
    )
    out = compute_template_kpi_fallback(
        "kpi.margin.pl.cogs.materials_pct_revenue",
        "pl.cogs.materials",
        mapped,
    )
    assert out is not None
    # abs(num) / den.
    assert out[0] == 0.40


def test_template_kpi_fallback_returns_none_when_inputs_missing():
    mapped = _mapped({"pl.rev.net": {"Y0": 100.0}}, lfl_years=["Y0"])
    assert (
        compute_template_kpi_fallback(
            "kpi.margin.unmapped.voice_pct_revenue",
            "unmapped.voice",
            mapped,
        )
        is None
    )


def test_template_kpi_fallback_unknown_template_returns_none():
    mapped = _mapped({"x": {"Y0": 1.0}}, lfl_years=["Y0"])
    assert (
        compute_template_kpi_fallback("kpi.exotic.thing", "x", mapped) is None
    )


# ---------------------------------------------------------------------------
# compute_assumption_defaults
# ---------------------------------------------------------------------------


def test_compute_defaults_uses_literal_kpi_when_present():
    # Method that references ``kpi.equity.payout_ratio`` (a literal KPI).
    methods = {
        "dividend_payout_ratio": {
            "method_id": "dividend_payout_ratio",
            "tech_code": "M_DIV_001",
            "family": "manual",
            "name_it": "x",
            "formula_python": (
                "-assumptions[voice]['payout'][year] * "
                "max(0, resolve('pl.net_income', prev_year))"
            ),
            "default_kpi_example": "kpi.equity.payout_ratio",
        }
    }
    reg = _empty_registries(
        voices={
            "bs.equity.dividends": {
                "voice_id": "bs.equity.dividends",
                "default_method": "dividend_payout_ratio",
            }
        },
        methods=methods,
    )

    kpi_index = {"kpi.equity.payout_ratio": (0.30, 0.85)}
    defaults = compute_assumption_defaults(
        [("bs.equity.dividends", "dividend_payout_ratio")],
        reg,
        kpi_index,
    )
    assert len(defaults) == 1
    d = defaults[0]
    assert d.assumption_name == "payout"
    assert d.value == 0.30
    assert d.calibration_score == 0.85
    assert d.source == SOURCE_DEFAULT_KPI
    assert d.default_kpi_id == "kpi.equity.payout_ratio"
    assert d.validation_range == (0.0, 1.0)


def test_compute_defaults_uses_template_fallback_for_growth():
    methods = {
        "historical_avg_growth": {
            "method_id": "historical_avg_growth",
            "tech_code": "M_EXT_002",
            "family": "extrapolation",
            "name_it": "x",
            "formula_python": (
                "resolve(voice, prev_year) * "
                "(1 + assumptions[voice]['growth_rate'][year])"
            ),
            "default_kpi_example": "kpi.growth.<voice>_yoy",
        }
    }
    reg = _empty_registries(
        voices={
            "pl.rev.gross.x": {
                "voice_id": "pl.rev.gross.x",
                "default_method": "historical_avg_growth",
            }
        },
        methods=methods,
    )

    mapped = _mapped(
        {"pl.rev.gross.x": {"Y-1": 100.0, "Y0": 110.0}},
        lfl_years=["Y-1", "Y0"],
    )
    defaults = compute_assumption_defaults(
        [("pl.rev.gross.x", "historical_avg_growth")],
        reg,
        kpi_index={},
        mapped_values=mapped,
    )
    assert len(defaults) == 1
    d = defaults[0]
    assert d.assumption_name == "growth_rate"
    assert d.value == 0.10
    assert d.source == SOURCE_DEFAULT_KPI
    # Template was the source even though we computed inline.
    assert d.default_kpi_id == "kpi.growth.pl.rev.gross.x_yoy"


def test_compute_defaults_falls_back_to_zero_when_no_inputs():
    methods = {
        "historical_avg_growth": {
            "method_id": "historical_avg_growth",
            "tech_code": "M_EXT_002",
            "family": "extrapolation",
            "name_it": "x",
            "formula_python": (
                "resolve(voice, prev_year) * "
                "(1 + assumptions[voice]['growth_rate'][year])"
            ),
            "default_kpi_example": "kpi.growth.<voice>_yoy",
        }
    }
    reg = _empty_registries(methods=methods)
    defaults = compute_assumption_defaults(
        [("pl.rev.gross.unmapped", "historical_avg_growth")],
        reg,
        kpi_index={},
        mapped_values=None,
    )
    assert len(defaults) == 1
    d = defaults[0]
    assert d.value == 0.0
    assert d.source == SOURCE_FALLBACK


def test_compute_defaults_skips_method_with_no_assumptions():
    # ``flat`` has no assumptions[voice][...] in its formula → no defaults.
    methods = {
        "flat": {
            "method_id": "flat",
            "tech_code": "M_EXT_001",
            "family": "extrapolation",
            "name_it": "x",
            "formula_python": "resolve(voice, prev_year)",
            "default_kpi_example": None,
        }
    }
    reg = _empty_registries(methods=methods)
    defaults = compute_assumption_defaults(
        [("any.voice", "flat")], reg, {}, mapped_values=None
    )
    assert defaults == []


def test_compute_defaults_marks_parameterized_assumption():
    methods = {
        "bom_input_cost": {
            "method_id": "bom_input_cost",
            "tech_code": "M_OPS_004",
            "family": "operational_driver",
            "name_it": "x",
            "formula_python": (
                "-drivers[f'driver.{voice}.volume'][year] * sum("
                "drivers[f'driver.{voice}.bom_{m}_qty'][year] * "
                "assumptions[voice][f'bom_{m}_price'][year] "
                "for m in assumptions[voice]['bom_materials'][year])"
            ),
            "default_kpi_example": None,
        }
    }
    reg = _empty_registries(methods=methods)
    defaults = compute_assumption_defaults(
        [("pl.cogs.materials", "bom_input_cost")],
        reg,
        kpi_index={},
        mapped_values=None,
    )
    by_name = {d.assumption_name: d for d in defaults}
    assert by_name["bom_{m}_price"].parameterized is True
    assert by_name["bom_{m}_price"].value == 0.0
    assert by_name["bom_{m}_price"].source == SOURCE_FALLBACK
    # The literal companion is still picked up.
    assert by_name["bom_materials"].parameterized is False

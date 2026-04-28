"""Unit tests for the M5 KPI calculator + expression parser."""

from __future__ import annotations

import math

import pytest

from backend.domain.intake.mapping_resolver import MappedValues
from backend.domain.kpi import compute_historical_kpis
from backend.domain.kpi.expression import VoiceRef, parse_voice_ref


# ---------- expression parser --------------------------------------------------


def test_parse_simple_t():
    ref = parse_voice_ref("pl.rev.net[t]")
    assert ref == VoiceRef("pl.rev.net", 0)


def test_parse_lagged():
    assert parse_voice_ref("pl.rev.net[t-1]") == VoiceRef("pl.rev.net", 1)
    assert parse_voice_ref("pl.rev.net[t-3]") == VoiceRef("pl.rev.net", 3)


def test_parse_template_returns_none():
    assert parse_voice_ref("<voice>[t-1]") is None


def test_parse_compound_returns_none():
    assert parse_voice_ref("DSO + DIO_total - DPO") is None
    assert parse_voice_ref("abs(borrowings) - cash") is None


def test_parse_none_returns_none():
    assert parse_voice_ref(None) is None


# ---------- calculator --------------------------------------------------------


def _values(voices: dict[str, dict[str, float]], lfl: list[str] | None = None) -> MappedValues:
    years = sorted({y for v in voices.values() for y in v}, key=lambda y: ("Y-3", "Y-2", "Y-1", "Y0").index(y))
    return MappedValues(
        project_id="p",
        values=voices,
        years_present=years,
        years_lfl=lfl if lfl is not None else years,
        unmapped_labels=[],
        label_to_voice={},
        raw_by_section={},
    )


def test_revenue_yoy_y0_value(loaded_registries):
    values = _values({"pl.rev.net": {"Y-1": 1000.0, "Y0": 1100.0}})
    snap = compute_historical_kpis(values, loaded_registries)
    revenue_yoy = next(
        k for k in snap.computed if k.kpi_id == "kpi.growth.revenue_yoy"
    )
    assert revenue_yoy.values_by_year["Y0"] == pytest.approx(0.10)
    # Y-1 has no prior → not present
    assert "Y-1" not in revenue_yoy.values_by_year
    assert revenue_yoy.default_for_projection == pytest.approx(0.10)
    assert revenue_yoy.calibration_score == 0.7  # 2 LFL years


def test_revenue_cagr_3y(loaded_registries):
    values = _values(
        {"pl.rev.net": {"Y-3": 1000.0, "Y-2": 1100.0, "Y-1": 1200.0, "Y0": 1331.0}}
    )
    snap = compute_historical_kpis(values, loaded_registries)
    cagr = next(
        k for k in snap.computed if k.kpi_id == "kpi.growth.revenue_cagr_3y"
    )
    expected = 1.331 ** (1 / 3) - 1
    assert cagr.values_by_year["Y0"] == pytest.approx(expected, rel=1e-4)
    assert cagr.default_for_projection == pytest.approx(expected, rel=1e-4)
    assert cagr.calibration_score == 1.0


def test_unsupported_formula_marked(loaded_registries):
    values = _values({"pl.rev.net": {"Y0": 100.0}})
    snap = compute_historical_kpis(values, loaded_registries)
    ccc = next(k for k in snap.computed if k.kpi_id == "kpi.nwc.ccc")
    assert ccc.not_computable_reason == "unsupported_formula"
    assert ccc.values_by_year == {}


def test_template_kpis_skipped(loaded_registries):
    values = _values({"pl.rev.net": {"Y0": 100.0}})
    snap = compute_historical_kpis(values, loaded_registries)
    template_kpis = [
        k for k in snap.computed if k.not_computable_reason == "template"
    ]
    assert len(template_kpis) == 4  # known templates in kpi_registry


def test_y0_only_calibration_score(loaded_registries):
    values = _values({"pl.rev.net": {"Y0": 100.0}, "pl.cogs.total": {"Y0": -40.0}})
    snap = compute_historical_kpis(values, loaded_registries)
    yoy = next(k for k in snap.computed if k.kpi_id == "kpi.growth.revenue_yoy")
    # Only Y0 → numerator-only present but denominator missing → not computed
    assert yoy.not_computable_reason == "missing_inputs"


def test_lfl_warning_when_excluded_year_in_avg(loaded_registries):
    # cogs_pct_revenue = abs(pl.cogs.total) / pl.rev.net — averaged Y-2/Y-1/Y0
    voices = {
        "pl.rev.net": {"Y-2": 1000.0, "Y-1": 1000.0, "Y0": 1000.0},
        "pl.cogs.total": {"Y-2": -400.0, "Y-1": -400.0, "Y0": -400.0},
    }
    values = _values(voices, lfl=["Y-2", "Y0"])  # Y-1 not LFL
    snap = compute_historical_kpis(values, loaded_registries)
    margin = next(
        k for k in snap.computed if k.kpi_id == "kpi.margin.cogs_pct_revenue"
    )
    assert margin.lfl_warning is True
    assert margin.default_for_projection == pytest.approx(0.4)


def test_counts_reflect_classification(loaded_registries):
    values = _values({"pl.rev.net": {"Y0": 100.0}})
    snap = compute_historical_kpis(values, loaded_registries)
    assert snap.counts["total"] == len(loaded_registries.kpis)
    assert snap.counts["computed"] + snap.counts["not_computable"] == snap.counts["total"]
    assert snap.counts["unsupported_formula"] >= 1
    assert snap.counts["template"] == 4

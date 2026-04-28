"""Unit tests for ``backend.domain.assumptions.extractor``."""

from __future__ import annotations

from backend.domain.assumptions.extractor import (
    extract_assumption_refs_from_formula,
    infer_validation_range,
)


def test_extract_simple_literal_name():
    formula = "resolve(voice, prev_year) * (1 + assumptions[voice]['growth_rate'][year])"
    refs = extract_assumption_refs_from_formula(formula)
    assert [r.name for r in refs] == ["growth_rate"]
    assert refs[0].parameterized is False
    assert refs[0].unresolved_placeholders == ()


def test_extract_multiple_distinct_names_dedup_preserves_order():
    formula = (
        "(assumptions[voice]['pct_start'][year] + "
        "(assumptions[voice]['pct_target'][year] - "
        "assumptions[voice]['pct_start'][year]) * "
        "assumptions[voice]['drift_progress'][year])"
    )
    refs = extract_assumption_refs_from_formula(formula)
    assert [r.name for r in refs] == ["pct_start", "pct_target", "drift_progress"]


def test_extract_parameterized_name_surfaces_placeholder():
    formula = (
        "-drivers[f'driver.{voice}.volume'][year] * sum("
        "drivers[f'driver.{voice}.bom_{m}_qty'][year] * "
        "assumptions[voice][f'bom_{m}_price'][year] "
        "for m in assumptions[voice]['bom_materials'][year])"
    )
    refs = extract_assumption_refs_from_formula(formula)
    by_name = {r.name: r for r in refs}
    # Parametric assumption surfaces with the survivor placeholder.
    assert "bom_{m}_price" in by_name
    assert by_name["bom_{m}_price"].parameterized is True
    assert by_name["bom_{m}_price"].unresolved_placeholders == ("m",)
    # Plain name extracted alongside.
    assert "bom_materials" in by_name
    assert by_name["bom_materials"].parameterized is False


def test_extract_handles_double_quotes():
    formula = 'assumptions[voice]["dso"][year]'
    refs = extract_assumption_refs_from_formula(formula)
    assert [r.name for r in refs] == ["dso"]


def test_extract_returns_empty_for_none_or_empty_formula():
    assert extract_assumption_refs_from_formula(None) == []
    assert extract_assumption_refs_from_formula("") == []
    assert extract_assumption_refs_from_formula("0.0") == []


def test_extract_ignores_drivers_lookup():
    formula = "drivers[f'driver.{voice}.volume'][year] * 1.0"
    assert extract_assumption_refs_from_formula(formula) == []


# ---------------------------------------------------------------------------
# infer_validation_range
# ---------------------------------------------------------------------------


def test_infer_range_growth_like():
    assert infer_validation_range("growth_rate") == (-0.50, 2.00)
    assert infer_validation_range("cagr") == (-0.50, 2.00)
    assert infer_validation_range("drift") == (-0.50, 2.00)
    assert infer_validation_range("volume_growth") == (-0.50, 2.00)


def test_infer_range_pct_like():
    assert infer_validation_range("pct") == (0.0, 1.0)
    assert infer_validation_range("payout") == (0.0, 1.0)
    assert infer_validation_range("ecl_rate") == (0.0, 1.0)
    assert infer_validation_range("retention_rate") == (0.0, 1.0)


def test_infer_range_days_like():
    assert infer_validation_range("days") == (0.0, 730.0)
    assert infer_validation_range("cycle_days") == (0.0, 730.0)
    assert infer_validation_range("dso") == (0.0, 730.0)


def test_infer_range_compound_suffix_match():
    # win_rate_qualified isn't in the exact-token set; suffix lookup
    # rescues it (suffix "qualified" doesn't, but "rate" -> via substring).
    assert infer_validation_range("win_rate_qualified") == (0.0, 1.0)
    # case_3_probability — substring "probability".
    assert infer_validation_range("case_3_probability") == (0.0, 1.0)


def test_infer_range_unknown_returns_none():
    assert infer_validation_range("amount") == (None, None)
    assert infer_validation_range("value") == (None, None)
    assert infer_validation_range("") == (None, None)

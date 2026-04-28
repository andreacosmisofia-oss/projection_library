"""Unit tests for ``backend.domain.drivers.extractor`` (M7).

The extractor is exercised against handwritten formula strings (so the
regex contract is pinned independent of registry churn) and against
the live registry (so we know it survives the actual data we ship).
"""

from __future__ import annotations

import pytest

from backend.domain.drivers import (
    DRIVER_TYPE_SCALAR_PER_YEAR,
    DRIVER_TYPE_STATIC_PARAMETERS,
    STATUS_COMPLETE,
    STATUS_MISSING,
    STATUS_PARTIAL,
    STATUS_SKIPPED,
    compute_driver_status,
    compute_required_drivers,
    extract_driver_refs_from_formula,
    infer_driver_type,
)


# ---------- regex-level extraction ------------------------------------


def test_extract_literal_driver_with_single_quotes():
    formula = "drivers['driver.headcount.total'][year] * 1.0"
    refs = extract_driver_refs_from_formula(formula, "any.voice")
    assert refs == [("driver.headcount.total", False, ())]


def test_extract_literal_driver_with_double_quotes():
    formula = 'drivers["driver.saas.new_arr"][year]'
    refs = extract_driver_refs_from_formula(formula, "bs.equity")
    assert refs == [("driver.saas.new_arr", False, ())]


def test_extract_voice_templated_driver_substitutes_voice_id():
    formula = "drivers[f'driver.{voice}.headcount'][year]"
    refs = extract_driver_refs_from_formula(formula, "pl.cogs.labour.direct")
    assert refs == [("driver.pl.cogs.labour.direct.headcount", False, ())]


def test_extract_nested_template_flagged_as_parameterized():
    formula = (
        "drivers[f'driver.{voice}.bom_{m}_qty'][year] * "
        "assumptions[voice][f'bom_{m}_price'][year]"
    )
    refs = extract_driver_refs_from_formula(formula, "pl.cogs.materials")
    assert len(refs) == 1
    resolved, parameterized, placeholders = refs[0]
    assert resolved == "driver.pl.cogs.materials.bom_{m}_qty"
    assert parameterized is True
    assert placeholders == ("m",)


def test_extract_resolve_driver_call():
    formula = (
        "resolve(f'driver.{voice}.backlog_open', year) * "
        "assumptions[voice]['conversion_rate'][year]"
    )
    refs = extract_driver_refs_from_formula(formula, "pl.rev.services")
    assert refs == [("driver.pl.rev.services.backlog_open", False, ())]


def test_extract_dedupes_repeated_lookups_in_order():
    formula = (
        "drivers[f'driver.{voice}.volume'][year] * 2 + "
        "drivers[f'driver.{voice}.volume'][prev_year]"
    )
    refs = extract_driver_refs_from_formula(formula, "pl.rev.gross")
    assert refs == [("driver.pl.rev.gross.volume", False, ())]


def test_extract_returns_empty_for_formula_without_drivers():
    formula = (
        "resolve(voice, prev_year) * "
        "(1 + assumptions[voice]['growth_rate'][year])"
    )
    refs = extract_driver_refs_from_formula(formula, "pl.opex.maintenance")
    assert refs == []


def test_extract_returns_empty_for_none_or_empty_formula():
    assert extract_driver_refs_from_formula(None, "x") == []
    assert extract_driver_refs_from_formula("", "x") == []


def test_extract_ignores_non_driver_resolve_calls():
    formula = "resolve('pl.rev.net', year) + drivers['driver.x.y'][year]"
    refs = extract_driver_refs_from_formula(formula, "pl.opex.commissions")
    assert refs == [("driver.x.y", False, ())]


def test_extract_handles_mixed_literal_and_templated_in_same_formula():
    formula = (
        "drivers['driver.headcount.total'][year] + "
        "drivers[f'driver.{voice}.bonus'][year]"
    )
    refs = extract_driver_refs_from_formula(formula, "pl.opex.personnel")
    assert refs == [
        ("driver.headcount.total", False, ()),
        ("driver.pl.opex.personnel.bonus", False, ()),
    ]


# ---------- type inference --------------------------------------------


@pytest.mark.parametrize(
    "driver_id,expected",
    [
        ("driver.pl.rev.gross.volume", DRIVER_TYPE_SCALAR_PER_YEAR),
        ("driver.pl.cogs.labour.direct.headcount", DRIVER_TYPE_SCALAR_PER_YEAR),
        ("driver.bs.nfp.term_loan.initial_principal", DRIVER_TYPE_STATIC_PARAMETERS),
        ("driver.bs.nfp.term_loan.term_years", DRIVER_TYPE_STATIC_PARAMETERS),
        ("driver.bs.nfp.term_loan.rate", DRIVER_TYPE_STATIC_PARAMETERS),
        ("driver.bs.nfp.term_loan.parameters", DRIVER_TYPE_STATIC_PARAMETERS),
    ],
)
def test_infer_driver_type_uses_suffix_heuristics(driver_id, expected):
    assert infer_driver_type(driver_id) == expected


# ---------- aggregation across method_configs --------------------------


def test_compute_required_drivers_aggregates_methods_per_driver(loaded_registries):
    configs = [
        ("pl.cogs.labour.direct", "headcount_unit_cost"),
        # A second voice using the same template-shaped method picks up
        # its own resolved id, so this is not a duplicate of the first.
        ("pl.opex.sm.personnel", "headcount_unit_cost"),
    ]
    reqs = compute_required_drivers(configs, loaded_registries)
    by_id = {r.driver_id: r for r in reqs}
    assert "driver.pl.cogs.labour.direct.headcount" in by_id
    assert "driver.pl.opex.sm.personnel.headcount" in by_id
    assert by_id["driver.pl.cogs.labour.direct.headcount"].required_by_methods == (
        "headcount_unit_cost",
    )


def test_compute_required_drivers_skips_methods_without_driver_refs(
    loaded_registries,
):
    # ``flat`` and ``historical_avg_growth`` have no drivers[...] in
    # their formulas — they should produce zero requirements.
    configs = [
        ("pl.opex.maintenance", "flat"),
        ("pl.rev.net", "historical_avg_growth"),
    ]
    reqs = compute_required_drivers(configs, loaded_registries)
    assert reqs == []


def test_compute_required_drivers_skips_unknown_method_silently(
    loaded_registries,
):
    configs = [("pl.cogs.labour.direct", "totally_made_up_method")]
    assert compute_required_drivers(configs, loaded_registries) == []


def test_compute_required_drivers_returns_sorted(loaded_registries):
    configs = [
        ("pl.cogs.labour.direct", "headcount_unit_cost"),
        ("bs.nfp.borrowings.term_loan_repayments", "term_loan_amortization_linear"),
    ]
    reqs = compute_required_drivers(configs, loaded_registries)
    ids = [r.driver_id for r in reqs]
    assert ids == sorted(ids)


def test_compute_required_drivers_flags_parameterized_for_bom(
    loaded_registries,
):
    configs = [("pl.cogs.materials", "bom_input_cost")]
    reqs = compute_required_drivers(configs, loaded_registries)
    # bom_input_cost has both ``drivers[f'driver.{voice}.volume']`` (clean)
    # and ``drivers[f'driver.{voice}.bom_{m}_qty']`` (parameterized).
    by_id = {r.driver_id: r for r in reqs}
    assert "driver.pl.cogs.materials.volume" in by_id
    assert by_id["driver.pl.cogs.materials.volume"].parameterized is False
    parameterized = [r for r in reqs if r.parameterized]
    assert len(parameterized) == 1
    assert "{m}" in parameterized[0].driver_id


def test_compute_required_drivers_collects_term_loan_static_parameters(
    loaded_registries,
):
    configs = [(
        "bs.nfp.borrowings.term_loan_repayments",
        "term_loan_amortization_linear",
    )]
    reqs = compute_required_drivers(configs, loaded_registries)
    ids = {r.driver_id for r in reqs}
    assert "driver.bs.nfp.borrowings.term_loan_repayments.initial_principal" in ids
    assert "driver.bs.nfp.borrowings.term_loan_repayments.term_years" in ids
    static = [
        r for r in reqs if r.driver_id.endswith(".initial_principal")
    ][0]
    assert static.type == DRIVER_TYPE_STATIC_PARAMETERS


# ---------- status computation ----------------------------------------


def test_status_skipped_overrides_data():
    # Even with all years present, ``skipped`` wins.
    status = compute_driver_status(
        driver_type=DRIVER_TYPE_SCALAR_PER_YEAR,
        skipped=True,
        present_years={"Y-1", "Y0"},
        required_years={"Y-1", "Y0"},
        has_static_parameters=False,
        has_time_series=False,
        has_aging_buckets=False,
    )
    assert status == STATUS_SKIPPED


def test_status_complete_when_required_years_present():
    status = compute_driver_status(
        driver_type=DRIVER_TYPE_SCALAR_PER_YEAR,
        skipped=False,
        present_years={"Y-1", "Y0"},
        required_years={"Y-1", "Y0"},
        has_static_parameters=False,
        has_time_series=False,
        has_aging_buckets=False,
    )
    assert status == STATUS_COMPLETE


def test_status_partial_when_some_years_missing():
    status = compute_driver_status(
        driver_type=DRIVER_TYPE_SCALAR_PER_YEAR,
        skipped=False,
        present_years={"Y0"},
        required_years={"Y-1", "Y0"},
        has_static_parameters=False,
        has_time_series=False,
        has_aging_buckets=False,
    )
    assert status == STATUS_PARTIAL


def test_status_missing_when_no_rows():
    status = compute_driver_status(
        driver_type=DRIVER_TYPE_SCALAR_PER_YEAR,
        skipped=False,
        present_years=set(),
        required_years={"Y-1", "Y0"},
        has_static_parameters=False,
        has_time_series=False,
        has_aging_buckets=False,
    )
    assert status == STATUS_MISSING


def test_status_static_parameters_complete_requires_payload():
    args = dict(
        skipped=False,
        present_years=set(),
        required_years={"Y-1", "Y0"},
        has_time_series=False,
        has_aging_buckets=False,
    )
    assert compute_driver_status(
        driver_type=DRIVER_TYPE_STATIC_PARAMETERS,
        has_static_parameters=True,
        **args,
    ) == STATUS_COMPLETE
    assert compute_driver_status(
        driver_type=DRIVER_TYPE_STATIC_PARAMETERS,
        has_static_parameters=False,
        **args,
    ) == STATUS_MISSING

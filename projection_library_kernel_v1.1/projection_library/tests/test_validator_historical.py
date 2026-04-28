"""Unit tests for the M5 historical validator."""

from __future__ import annotations

import pytest

from backend.domain.intake.mapping_resolver import MappedValues
from backend.domain.intake.validator_historical import run_historical_validation
from backend.infrastructure.db.models import Project


def _project(perimeter: str | None = "consolidated", currency: str = "EUR") -> Project:
    return Project(
        name="t",
        sector_pack="industrial",
        perimeter=perimeter,
        currency=currency,
    )


def _values(
    *,
    voices: dict[str, dict[str, float]] | None = None,
    raw_by_section: dict[str, list[tuple[str, str, float]]] | None = None,
    years_present: list[str] | None = None,
    years_lfl: list[str] | None = None,
) -> MappedValues:
    voices = voices or {}
    raw_by_section = raw_by_section or {}
    years_present = years_present or sorted(
        {y for v in voices.values() for y in v}
        | {row[1] for rows in raw_by_section.values() for row in rows}
    )
    years_lfl = years_lfl if years_lfl is not None else list(years_present)
    return MappedValues(
        project_id="p",
        values=voices,
        years_present=years_present,
        years_lfl=years_lfl,
        unmapped_labels=[],
        label_to_voice={},
        raw_by_section=raw_by_section,
    )


def test_di_002_blocks_when_no_y0(loaded_registries):
    values = _values(
        voices={"pl.rev.net": {"Y-1": 100.0}},
        years_present=["Y-1"],
    )
    report = run_historical_validation(values, loaded_registries, _project())
    rule_ids = {i.rule_id for i in report.issues if i.severity == "block"}
    assert "DI_002_y0_actual_complete" in rule_ids
    assert report.can_proceed is False


def test_di_002_blocks_when_critical_voice_missing(loaded_registries):
    # Y0 column exists but no critical voice mapped
    values = _values(
        voices={},
        raw_by_section={"P&L": [("Foo", "Y0", 100.0)]},
        years_present=["Y0"],
    )
    report = run_historical_validation(values, loaded_registries, _project())
    blocks = [i for i in report.issues if i.severity == "block"]
    rule_ids = {i.rule_id for i in blocks}
    assert "DI_002_y0_actual_complete" in rule_ids


def test_di_013_blocks_unbalanced_sp(loaded_registries):
    # Unbalanced: assets 1000, liab+equity sum to -800 (delta = 200)
    raw = {
        "SP_assets": [
            ("Cassa", "Y0", 1000.0),
        ],
        "SP_liabilities": [
            ("Debiti", "Y0", -300.0),
        ],
        "SP_equity": [
            ("Capitale", "Y0", -500.0),
        ],
    }
    values = _values(
        voices={
            "pl.rev.net": {"Y0": 100.0},
            "pl.cogs.total": {"Y0": -50.0},
            "bs.nfp.cash": {"Y0": 1000.0},
            "bs.equity.share_capital.close": {"Y0": -500.0},
            "bs.fa.tangible.gross_close": {"Y0": 200.0},
        },
        raw_by_section=raw,
    )
    report = run_historical_validation(values, loaded_registries, _project())
    di013 = [i for i in report.issues if i.rule_id == "DI_013_balance_check_historical"]
    assert di013, "Expected DI_013 to fire on unbalanced SP"
    assert all(i.severity == "block" for i in di013)


def test_di_013_passes_balanced_sp(loaded_registries):
    raw = {
        "SP_assets": [("Cassa", "Y0", 1000.0)],
        "SP_liabilities": [("Debiti", "Y0", -300.0)],
        "SP_equity": [("Capitale", "Y0", -700.0)],
    }
    values = _values(
        voices={
            "pl.rev.net": {"Y0": 100.0},
            "pl.cogs.total": {"Y0": -50.0},
            "bs.nfp.cash": {"Y0": 1000.0},
            "bs.equity.share_capital.close": {"Y0": -700.0},
            "bs.fa.tangible.gross_close": {"Y0": 200.0},
        },
        raw_by_section=raw,
    )
    report = run_historical_validation(values, loaded_registries, _project())
    rule_ids = {i.rule_id for i in report.issues}
    assert "DI_013_balance_check_historical" not in rule_ids


def test_sc_001_revenue_negative_is_error(loaded_registries):
    values = _values(
        voices={
            "pl.rev.net": {"Y0": -100.0},
            "pl.cogs.total": {"Y0": -50.0},
            "bs.nfp.cash": {"Y0": 200.0},
            "bs.equity.share_capital.close": {"Y0": -200.0},
            "bs.fa.tangible.gross_close": {"Y0": 200.0},
        },
    )
    report = run_historical_validation(values, loaded_registries, _project())
    sc = [i for i in report.issues if i.rule_id == "SC_001_revenues_positive"]
    assert sc and sc[0].severity == "error"


def test_sc_002_positive_cost_is_error(loaded_registries):
    values = _values(
        voices={
            "pl.rev.net": {"Y0": 100.0},
            "pl.cogs.total": {"Y0": 50.0},
            "bs.nfp.cash": {"Y0": 200.0},
            "bs.equity.share_capital.close": {"Y0": -200.0},
            "bs.fa.tangible.gross_close": {"Y0": 200.0},
        },
    )
    report = run_historical_validation(values, loaded_registries, _project())
    sc = [i for i in report.issues if i.rule_id == "SC_002_costs_negative"]
    assert sc and sc[0].severity == "error"


def test_cf_006_currency_must_be_eur(loaded_registries):
    values = _values(
        voices={
            "pl.rev.net": {"Y0": 100.0},
            "pl.cogs.total": {"Y0": -50.0},
            "bs.nfp.cash": {"Y0": 200.0},
            "bs.equity.share_capital.close": {"Y0": -200.0},
            "bs.fa.tangible.gross_close": {"Y0": 200.0},
        },
    )
    project = _project(currency="USD")
    report = run_historical_validation(values, loaded_registries, project)
    rules = {i.rule_id for i in report.issues}
    assert "CF_006_currency_consistency" in rules


def test_cp_002_extreme_revenue_swing_is_warning(loaded_registries):
    values = _values(
        voices={
            "pl.rev.net": {"Y-1": 100.0, "Y0": 300.0},
            "pl.cogs.total": {"Y0": -50.0},
            "bs.nfp.cash": {"Y0": 200.0},
            "bs.equity.share_capital.close": {"Y0": -200.0},
            "bs.fa.tangible.gross_close": {"Y0": 200.0},
        },
        years_present=["Y-1", "Y0"],
    )
    report = run_historical_validation(values, loaded_registries, _project())
    cp = [i for i in report.issues if i.rule_id == "CP_002_revenue_trend_continuity"]
    assert cp and cp[0].severity == "warning"


def test_clean_dataset_can_proceed(loaded_registries):
    values = _values(
        voices={
            "pl.rev.net": {"Y-1": 1000.0, "Y0": 1100.0},
            "pl.cogs.total": {"Y-1": -500.0, "Y0": -550.0},
            "bs.nfp.cash": {"Y-1": 200.0, "Y0": 250.0},
            "bs.equity.share_capital.close": {"Y-1": -100.0, "Y0": -100.0},
            "bs.fa.tangible.gross_close": {"Y-1": 800.0, "Y0": 850.0},
        },
        raw_by_section={
            "SP_assets": [("PPE", "Y0", 850.0), ("Cassa", "Y0", 250.0)],
            "SP_liabilities": [("Debiti", "Y0", -300.0)],
            "SP_equity": [("Capitale", "Y0", -800.0)],
        },
        years_present=["Y-1", "Y0"],
    )
    report = run_historical_validation(values, loaded_registries, _project())
    assert report.can_proceed
    summary = report.summary()
    assert summary["block"] == 0

"""Unit tests for the M5 quality scorer."""

from __future__ import annotations

import pytest

from backend.domain.intake.mapping_resolver import MappedValues
from backend.domain.intake.validator_historical import (
    HistoricalValidationIssue,
    HistoricalValidationReport,
    run_historical_validation,
)
from backend.domain.quality import compute_quality_score
from backend.infrastructure.db.models import Project


def _project() -> Project:
    return Project(
        name="t",
        sector_pack="industrial",
        perimeter="consolidated",
        currency="EUR",
        tier_level=None,
    )


def _values(
    voices: dict[str, dict[str, float]] | None = None,
    *,
    years_present: list[str],
    years_lfl: list[str] | None = None,
) -> MappedValues:
    return MappedValues(
        project_id="p",
        values=voices or {},
        years_present=years_present,
        years_lfl=years_lfl if years_lfl is not None else list(years_present),
        unmapped_labels=[],
        label_to_voice={},
        raw_by_section={},
    )


def _empty_report() -> HistoricalValidationReport:
    return HistoricalValidationReport(issues=[])


def test_history_full_4_years_lfl(loaded_registries):
    values = _values(
        voices={"pl.rev.net": {"Y0": 1.0}},
        years_present=["Y-3", "Y-2", "Y-1", "Y0"],
    )
    result = compute_quality_score(values, _empty_report(), loaded_registries, None)
    assert result.score_history == 100.0


def test_history_only_y0(loaded_registries):
    values = _values(
        voices={"pl.rev.net": {"Y0": 1.0}}, years_present=["Y0"]
    )
    result = compute_quality_score(values, _empty_report(), loaded_registries, None)
    assert result.score_history == 40.0


def test_history_half_weight_for_not_lfl(loaded_registries):
    # 3 LFL + 1 not-LFL = 3.5 → interpolated 95
    values = _values(
        voices={"pl.rev.net": {"Y0": 1.0}},
        years_present=["Y-3", "Y-2", "Y-1", "Y0"],
        years_lfl=["Y-3", "Y-1", "Y0"],  # Y-2 is not LFL
    )
    result = compute_quality_score(values, _empty_report(), loaded_registries, None)
    assert result.score_history == pytest.approx(95.0)


def test_consistency_blocks_zero_out(loaded_registries):
    block_issue = HistoricalValidationIssue(
        rule_id="DI_013_balance_check_historical",
        severity="block",
        voice_id=None,
        year="Y0",
        message="block",
    )
    values = _values(
        voices={"pl.rev.net": {"Y0": 1.0}}, years_present=["Y0"]
    )
    result = compute_quality_score(
        values,
        HistoricalValidationReport(issues=[block_issue]),
        loaded_registries,
        None,
    )
    assert result.score_consistency == 0.0


def test_consistency_errors_and_warnings(loaded_registries):
    issues = [
        HistoricalValidationIssue("AI_005", "error", None, None, "x") for _ in range(2)
    ] + [
        HistoricalValidationIssue("RP_002", "warning", None, None, "x") for _ in range(5)
    ]
    values = _values(
        voices={"pl.rev.net": {"Y0": 1.0}}, years_present=["Y0"]
    )
    result = compute_quality_score(
        values,
        HistoricalValidationReport(issues=issues),
        loaded_registries,
        None,
    )
    # 100 - 2*8 - 5*2 = 74
    assert result.score_consistency == 74.0


def test_method_calibration_pending(loaded_registries):
    values = _values(
        voices={"pl.rev.net": {"Y0": 1.0}}, years_present=["Y0"]
    )
    result = compute_quality_score(values, _empty_report(), loaded_registries, None)
    assert result.score_method_calibration is None
    detail = result.components_detail["method_calibration"]
    assert detail["status"] == "pending_method_selection"
    weights_used = result.components_detail["weights_used"]
    assert weights_used["method_calibration"] == 0.0


def test_classification_history_and_consistency_at_full(loaded_registries):
    # 4y LFL + 0 issues + critical_set fully mapped → history=100,
    # consistency=100, completeness penalised by sparse non-critical
    # mapping. Until M1.6 ships the tier-aware required matrix, this
    # is the best we can do; classification lands in Acceptable/Solid.
    voices = {
        "pl.rev.net": {"Y0": 100.0},
        "pl.cogs.total": {"Y0": -50.0},
        "bs.nfp.cash": {"Y0": 200.0},
        "bs.equity.share_capital.close": {"Y0": -200.0},
        "bs.fa.tangible.gross_close": {"Y0": 200.0},
    }
    values = _values(voices=voices, years_present=["Y-3", "Y-2", "Y-1", "Y0"])
    result = compute_quality_score(values, _empty_report(), loaded_registries, None)
    assert result.score_history == 100.0
    assert result.score_consistency == 100.0
    detail = result.components_detail["completeness"]
    assert detail["critical_missing"] == []  # no critical group skipped
    assert result.classification in {"Acceptable", "Solid"}


def test_only_y0_no_critical_classifies_low(loaded_registries):
    values = _values(
        voices={},
        years_present=["Y0"],
    )
    result = compute_quality_score(values, _empty_report(), loaded_registries, None)
    # No critical voices mapped → completeness penalised heavily
    assert result.classification in {"Insufficient", "Directional"}


def test_total_renormalises_when_method_calibration_missing(loaded_registries):
    # Build values yielding history=40, completeness=40, consistency=100
    values = _values(
        voices={
            "pl.rev.net": {"Y0": 100.0},
            "pl.cogs.total": {"Y0": -50.0},
            "bs.nfp.cash": {"Y0": 200.0},
            "bs.equity.share_capital.close": {"Y0": -200.0},
            "bs.fa.tangible.gross_close": {"Y0": 200.0},
        },
        years_present=["Y0"],
    )
    result = compute_quality_score(values, _empty_report(), loaded_registries, None)
    # Manually compute weighted average over the 3 sub-scores
    h, c, k = result.score_history, result.score_completeness, result.score_consistency
    expected_total = (0.25 * h + 0.30 * c + 0.20 * k) / 0.75
    assert result.score_total == pytest.approx(round(expected_total, 2))

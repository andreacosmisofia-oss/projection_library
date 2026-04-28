"""Quality score (M5) — formula and sub-score logic from
``flows/10_quality_score.md``.

The 4 sub-scores:

1. ``score_history`` — count of historical years available, half-weight
   for not-LFL years.
2. ``score_completeness`` — share of "required" voices that have a
   confirmed mapping, with a penalty for missing critical voices.
3. ``score_consistency`` — derived from validation issue counts.
4. ``score_method_calibration`` — N/A in M5 (depends on M6 method
   selection); the score is left ``None`` and the total renormalises
   the remaining 3 weights to keep the badge meaningful.

Required voice baseline (M5 simplification): ``nature ∈ {driver,
driver_placeholder}`` filtered by ``statement ∈ {PL, BS}``. M1.6's
``required_data_matrix.yaml`` will provide a tier-aware list later;
the ``_build_required_voice_set`` seam is where the upgrade plugs in.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.domain.intake.mapping_resolver import MappedValues
from backend.domain.intake.validator_historical import (
    CRITICAL_VOICE_GROUPS,
    HistoricalValidationReport,
)
from backend.infrastructure.registry.loader import Registries


WEIGHTS = {
    "history": 0.25,
    "completeness": 0.30,
    "consistency": 0.20,
    "method_calibration": 0.25,
}


@dataclass(frozen=True)
class QualityScoreResult:
    score_total: float
    score_history: float
    score_completeness: float
    score_consistency: float
    score_method_calibration: float | None
    classification: str
    components_detail: dict


# ---------------------------------------------------------------------------
# Sub-score 1 — history
# ---------------------------------------------------------------------------


def _score_history(values: MappedValues) -> tuple[float, dict]:
    historical_years = ("Y-3", "Y-2", "Y-1", "Y0")
    actuals = [y for y in historical_years if y in values.years_present]
    lfl = set(values.years_lfl)
    weighted = sum(1.0 if y in lfl else 0.5 for y in actuals)

    if weighted >= 4.0:
        score = 100.0
    elif weighted >= 3.0:
        # Linear interpolation 90 → 100 between 3.0 and 4.0
        score = 90.0 + (weighted - 3.0) * 10.0
    elif weighted >= 2.0:
        score = 70.0 + (weighted - 2.0) * 20.0
    elif weighted >= 1.0:
        score = 40.0 + (weighted - 1.0) * 30.0
    elif weighted > 0:
        score = 40.0 * weighted
    else:
        score = 0.0

    return score, {
        "years_present": list(actuals),
        "years_lfl": [y for y in actuals if y in lfl],
        "weighted_count": weighted,
        "score": score,
    }


# ---------------------------------------------------------------------------
# Sub-score 2 — completeness
# ---------------------------------------------------------------------------


def _build_required_voice_set(registries: Registries, _tier_level: str | None) -> set[str]:
    """Pilot baseline of "required" voices.

    M5 stops at ``nature in {driver, driver_placeholder}`` filtered to
    PL / BS. ``_tier_level`` is ignored at the moment (the
    required-by-tier matrix lives in M1.6 and will replace this set).
    """
    required: set[str] = set()
    for voice_id, spec in registries.voices.items():
        if spec.get("statement") not in ("PL", "BS"):
            continue
        if spec.get("nature") in ("driver", "driver_placeholder"):
            required.add(voice_id)
    return required


def _critical_voices_present(values: MappedValues) -> list[str]:
    """Return the names of critical groups that have at least one mapped voice."""
    present: list[str] = []
    for group, candidates in CRITICAL_VOICE_GROUPS.items():
        if any(values.has(v) for v in candidates):
            present.append(group)
    return present


def _score_completeness(
    values: MappedValues, registries: Registries, tier_level: str | None
) -> tuple[float, dict]:
    required = _build_required_voice_set(registries, tier_level)
    if not required:
        return 0.0, {"required": 0, "score": 0.0}

    mapped_voices = set(values.values.keys())
    mapped_in_required = mapped_voices & required
    base = (len(mapped_in_required) / len(required)) * 100.0

    critical_present = set(_critical_voices_present(values))
    critical_missing = sorted(set(CRITICAL_VOICE_GROUPS) - critical_present)
    critical_penalty = len(critical_missing) * 10.0

    score = max(0.0, base - critical_penalty)
    return score, {
        "required": len(required),
        "mapped_in_required": len(mapped_in_required),
        "base": round(base, 2),
        "critical_groups_total": len(CRITICAL_VOICE_GROUPS),
        "critical_missing": critical_missing,
        "critical_penalty": critical_penalty,
        "score": score,
    }


# ---------------------------------------------------------------------------
# Sub-score 3 — consistency
# ---------------------------------------------------------------------------


def _score_consistency(report: HistoricalValidationReport) -> tuple[float, dict]:
    summary = report.summary()
    if summary["block"] > 0:
        score = 0.0
    else:
        score = max(
            0.0,
            100.0 - 8.0 * summary["error"] - 2.0 * summary["warning"],
        )
    return score, {
        "blocks": summary["block"],
        "errors": summary["error"],
        "warnings": summary["warning"],
        "info": summary["info"],
        "score": score,
    }


# ---------------------------------------------------------------------------
# Sub-score 4 — method calibration (deferred to M6)
# ---------------------------------------------------------------------------


def _score_method_calibration_pending() -> tuple[None, dict]:
    return None, {
        "status": "pending_method_selection",
        "note": (
            "method_calibration sub-score requires Milestone 6 method "
            "configs; total renormalises remaining weights."
        ),
        "score": None,
    }


# ---------------------------------------------------------------------------
# Classification + total
# ---------------------------------------------------------------------------


def _classify(total: float) -> str:
    if total >= 90:
        return "Full"
    if total >= 70:
        return "Solid"
    if total >= 50:
        return "Acceptable"
    if total >= 30:
        return "Directional"
    return "Insufficient"


def _weighted_total(
    history: float,
    completeness: float,
    consistency: float,
    method_calibration: float | None,
) -> float:
    """Weighted sum, renormalised when method_calibration is missing."""
    pieces = [
        (history, WEIGHTS["history"]),
        (completeness, WEIGHTS["completeness"]),
        (consistency, WEIGHTS["consistency"]),
    ]
    if method_calibration is not None:
        pieces.append((method_calibration, WEIGHTS["method_calibration"]))
    weight_sum = sum(w for _, w in pieces)
    if weight_sum == 0:
        return 0.0
    return sum(value * weight for value, weight in pieces) / weight_sum


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def compute_quality_score(
    values: MappedValues,
    validation_report: HistoricalValidationReport,
    registries: Registries,
    tier_level: str | None,
) -> QualityScoreResult:
    history, history_detail = _score_history(values)
    completeness, completeness_detail = _score_completeness(
        values, registries, tier_level
    )
    consistency, consistency_detail = _score_consistency(validation_report)
    method_calibration, mc_detail = _score_method_calibration_pending()

    total = _weighted_total(history, completeness, consistency, method_calibration)
    classification = _classify(total)

    return QualityScoreResult(
        score_total=round(total, 2),
        score_history=round(history, 2),
        score_completeness=round(completeness, 2),
        score_consistency=round(consistency, 2),
        score_method_calibration=method_calibration,
        classification=classification,
        components_detail={
            "history": history_detail,
            "completeness": completeness_detail,
            "consistency": consistency_detail,
            "method_calibration": mc_detail,
            "weights": dict(WEIGHTS),
            "weights_used": {
                "history": WEIGHTS["history"],
                "completeness": WEIGHTS["completeness"],
                "consistency": WEIGHTS["consistency"],
                "method_calibration": (
                    WEIGHTS["method_calibration"]
                    if method_calibration is not None
                    else 0.0
                ),
            },
        },
    )


__all__ = [
    "QualityScoreResult",
    "WEIGHTS",
    "compute_quality_score",
]

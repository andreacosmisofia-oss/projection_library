"""Compute historical KPIs from MappedValues (M5).

For every KPI in ``kpi_registry`` whose numerator (and, when present,
denominator) is a simple voice reference parseable by
:mod:`backend.domain.kpi.expression`, this module:

1. Computes a per-year value across the actual years available
   (Y-3..Y0).
2. Aggregates an explanatory ``default_for_projection`` according to
   ``default_aggregation`` (avg_3y / last_3y_cagr / y0_value),
   honouring LFL filtering on aggregations as documented in
   ``flows/03_validation_historical.md`` §4–5.
3. Stamps a ``calibration_score`` reflecting how many LFL years are
   available, plus an ``lfl_warning`` flag if the aggregation could not
   be computed on a fully LFL window.

KPIs whose formulas are too complex for the M5 parser are returned with
``not_computable_reason='unsupported_formula'`` and skipped from the
aggregation. This keeps the door open for M9 to plug in the real
evaluator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from backend.domain.intake.mapping_resolver import MappedValues
from backend.domain.kpi.expression import VoiceRef, parse_voice_ref
from backend.infrastructure.registry.loader import Registries


@dataclass(frozen=True)
class ComputedKPI:
    kpi_id: str
    values_by_year: dict[str, float]
    default_for_projection: float | None
    calibration_score: float
    lfl_warning: bool
    not_computable_reason: str | None
    used_aggregation: str | None


@dataclass(frozen=True)
class HistoricalKPISnapshot:
    project_id: str
    computed: list[ComputedKPI]
    counts: dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Sign + ratio helpers
# ---------------------------------------------------------------------------


def _apply_sign(num: float, den: float, sign_handling: str) -> tuple[float, float]:
    if sign_handling == "abs_num":
        return abs(num), den
    if sign_handling == "abs_den":
        return num, abs(den)
    if sign_handling == "abs_both":
        return abs(num), abs(den)
    if sign_handling == "signed":
        return num, den
    return num, den  # raw / derived / unknown → no transform


def _ratio(num: float | None, den: float | None, sign_handling: str) -> float | None:
    if num is None or den is None or den == 0:
        return None
    n, d = _apply_sign(num, den, sign_handling)
    if d == 0:
        return None
    return n / d


def _resolve(
    values: MappedValues,
    ref: VoiceRef,
    anchor_year: str,
    year_order: list[str],
) -> float | None:
    anchor_idx = year_order.index(anchor_year)
    target_idx = ref.shifted(anchor_idx)
    if target_idx < 0 or target_idx >= len(year_order):
        return None
    target_year = year_order[target_idx]
    return values.get(ref.voice_id, target_year)


# ---------------------------------------------------------------------------
# Aggregations
# ---------------------------------------------------------------------------


def _ordered_actual_years(years: Iterable[str]) -> list[str]:
    """Order historical years from oldest to newest using the canonical sequence."""
    canonical = ("Y-3", "Y-2", "Y-1", "Y0")
    seen = set(years)
    return [y for y in canonical if y in seen]


def _avg_3y(
    per_year: dict[str, float],
    lfl_years: set[str],
) -> tuple[float | None, bool]:
    """Average of Y-2, Y-1, Y0 restricted to LFL years (drop the rest).

    Returns (value, lfl_warning). The warning fires when at least one
    of {Y-2, Y-1, Y0} was excluded for being not-LFL: the aggregation
    is still emitted on whatever LFL subset is left.
    """
    window = ("Y-2", "Y-1", "Y0")
    available = [y for y in window if y in per_year]
    lfl_subset = [y for y in available if y in lfl_years]
    used = lfl_subset or available
    if not used:
        return None, False
    value = sum(per_year[y] for y in used) / len(used)
    warning = bool(set(available) - set(used))
    return value, warning


def _last_3y_cagr(
    per_year: dict[str, float],
    lfl_years: set[str],
) -> tuple[float | None, bool]:
    """CAGR Y-3 → Y0; both endpoints must be present (and ideally LFL).

    Returns (value, lfl_warning).
    """
    start = per_year.get("Y-3")
    end = per_year.get("Y0")
    if start is None or end is None:
        return None, False
    if start == 0:
        return None, False
    sign = 1 if start > 0 else -1
    if sign * end <= 0:
        # Negative ratio under a fractional power is undefined. Refuse.
        return None, False
    cagr = (end / start) ** (1 / 3) - 1
    warning = not {"Y-3", "Y0"}.issubset(lfl_years)
    return cagr, warning


def _y0_value(
    per_year: dict[str, float],
    _lfl_years: set[str],
) -> tuple[float | None, bool]:
    return per_year.get("Y0"), False


_AGG_FNS = {
    "avg_3y": _avg_3y,
    "last_3y_cagr": _last_3y_cagr,
    "y0_value": _y0_value,
}


# ---------------------------------------------------------------------------
# Calibration score
# ---------------------------------------------------------------------------


def _calibration_for_kpi(actual_years: list[str], lfl_years: set[str]) -> float:
    """0 / 0.4 / 0.7 / 1.0 — flow 03 §6.

    Counts how many *historical* years are available in the project's
    actuals; not-LFL years contribute 0.5 each. The score reflects the
    coverage of the input data, not how many per-year derived values
    the KPI happened to produce (a YoY KPI on 2 input years still
    yields one derived value, but the calibration is "2 LFL years"
    → 0.7).
    """
    if not actual_years:
        return 0.0
    weighted = sum(1.0 if y in lfl_years else 0.5 for y in actual_years)
    if weighted >= 3.0:
        return 1.0
    if weighted >= 2.0:
        return 0.7
    if weighted >= 1.0:
        return 0.4
    return 0.0


# ---------------------------------------------------------------------------
# KPI computation entry point
# ---------------------------------------------------------------------------


def _compute_single(
    spec: dict,
    values: MappedValues,
    actual_years: list[str],
    lfl_set: set[str],
) -> ComputedKPI:
    kpi_id = spec["kpi_id"]
    if spec.get("is_template"):
        return ComputedKPI(
            kpi_id=kpi_id,
            values_by_year={},
            default_for_projection=None,
            calibration_score=0.0,
            lfl_warning=False,
            not_computable_reason="template",
            used_aggregation=None,
        )

    num_ref = parse_voice_ref(spec.get("numerator"))
    den_expr = spec.get("denominator")
    den_ref = parse_voice_ref(den_expr) if den_expr is not None else None

    if num_ref is None or (den_expr is not None and den_ref is None):
        return ComputedKPI(
            kpi_id=kpi_id,
            values_by_year={},
            default_for_projection=None,
            calibration_score=0.0,
            lfl_warning=False,
            not_computable_reason="unsupported_formula",
            used_aggregation=None,
        )

    sign_handling = spec.get("sign_handling", "raw")
    family = spec.get("famiglia")
    # Growth KPIs encode "ratio of same voice across years" in the
    # registry (e.g. ``pl.rev.net[t] / pl.rev.net[t-k]``) but the spec
    # treats the value as an *annualised* growth rate (unit=pct,
    # expected ~0.10 for +10%). For lag k = ``den_ref.offset - num_ref.offset``,
    # the canonical conversion is ``ratio**(1/k) - 1`` (CAGR over k
    # years; reduces to ``ratio - 1`` when k = 1, i.e. YoY).
    growth_lag: int | None = None
    if family == "growth" and den_ref is not None:
        lag = den_ref.offset - num_ref.offset
        growth_lag = lag if lag >= 1 else None
    per_year: dict[str, float] = {}
    for year in actual_years:
        num_value = _resolve(values, num_ref, year, actual_years)
        if num_value is None:
            continue
        if den_ref is None:
            value = num_value if sign_handling != "abs_num" else abs(num_value)
        else:
            den_value = _resolve(values, den_ref, year, actual_years)
            value = _ratio(num_value, den_value, sign_handling)
        if value is None:
            continue
        if growth_lag is not None:
            if value <= 0:
                # Fractional power of a non-positive ratio is undefined.
                continue
            value = value ** (1 / growth_lag) - 1.0
        per_year[year] = value

    if not per_year:
        return ComputedKPI(
            kpi_id=kpi_id,
            values_by_year={},
            default_for_projection=None,
            calibration_score=0.0,
            lfl_warning=False,
            not_computable_reason="missing_inputs",
            used_aggregation=None,
        )

    aggregation = spec.get("default_aggregation") or "y0_value"
    if growth_lag is not None:
        # The growth-lag transform already encodes the annualised rate
        # at the anchor year; ``default_aggregation: last_3y_cagr`` on
        # growth KPIs is documentary (the per-year value at Y0 is the
        # CAGR). Use Y0 directly and fold the LFL window check into a
        # ``lfl_warning`` flag for the modal.
        default_for_projection = per_year.get("Y0")
        end_window = ("Y0",) if growth_lag <= 1 else ("Y0", f"Y-{growth_lag}")
        lfl_warning = not all(y in lfl_set for y in end_window if y in actual_years)
        used_agg = aggregation
    else:
        agg_fn = _AGG_FNS.get(aggregation)
        if agg_fn is None:
            default_for_projection = per_year.get("Y0")
            lfl_warning = False
            used_agg = "y0_value"
        else:
            default_for_projection, lfl_warning = agg_fn(per_year, lfl_set)
            used_agg = aggregation

    calibration = _calibration_for_kpi(actual_years, lfl_set)

    return ComputedKPI(
        kpi_id=kpi_id,
        values_by_year=per_year,
        default_for_projection=default_for_projection,
        calibration_score=calibration,
        lfl_warning=lfl_warning,
        not_computable_reason=None,
        used_aggregation=used_agg,
    )


def compute_historical_kpis(
    values: MappedValues,
    registries: Registries,
) -> HistoricalKPISnapshot:
    """Compute every KPI in the registry against the project's mapped values."""
    actual_years = _ordered_actual_years(values.years_present)
    lfl_set = set(values.years_lfl)

    computed: list[ComputedKPI] = []
    counts = {
        "total": 0,
        "computed": 0,
        "not_computable": 0,
        "unsupported_formula": 0,
        "template": 0,
        "missing_inputs": 0,
    }
    for spec in registries.kpis.values():
        counts["total"] += 1
        result = _compute_single(spec, values, actual_years, lfl_set)
        computed.append(result)
        if result.not_computable_reason is None:
            counts["computed"] += 1
        else:
            counts["not_computable"] += 1
            counts[result.not_computable_reason] = (
                counts.get(result.not_computable_reason, 0) + 1
            )
    return HistoricalKPISnapshot(
        project_id=values.project_id, computed=computed, counts=counts
    )


__all__ = [
    "ComputedKPI",
    "HistoricalKPISnapshot",
    "compute_historical_kpis",
]

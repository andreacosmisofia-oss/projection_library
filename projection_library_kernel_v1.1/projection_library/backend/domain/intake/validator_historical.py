"""Historical validator (M5) — hand-coded subset of rules from
``flows/03_validation_historical.md``.

We deliberately do not execute the ``formula_python`` strings stored in
``validation_rules.yaml``: most of them are placeholders inherited from
the spec sheet and are not faithful to the rule's stated intent.
Implementing the documented intent in code is more reliable, more
testable, and avoids a fragile dependency on an evaluator that does
not exist yet.

Rules covered (severity in parentheses):
- DI_002 (block): every critical voice has a Y0 actual
- DI_011 (error): P&L revenues > 0, P&L costs < 0
- DI_013 (block): historical balance check |assets+liab+equity| ≤ tol
- AI_005 (error): subtotal voice == sum of components (tolerance 0.5%)
- SC_001 (error): revenue voices positive
- SC_002 (error): COGS / OPEX / D&A voices negative
- SC_006 (error): cash positive
- SC_007 (error): D&A voices negative
- CP_001 (warning): equity opening Y == equity closing Y-1 (≥2 years)
- CP_002 (warning): revenue trend continuity (≥2 years)
- CF_005 (error): perimeter set on the project
- CF_006 (error): currency = "EUR" (pilot constraint)

Out of scope for M5: anything that requires projected output (engine
run), the formula evaluator (M9), method configs (M6).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Literal

from backend.domain.intake.mapping_resolver import MappedValues
from backend.infrastructure.db.models import Project
from backend.infrastructure.registry.loader import Registries


Severity = Literal["block", "error", "warning", "info"]


@dataclass(frozen=True)
class HistoricalValidationIssue:
    rule_id: str
    severity: Severity
    voice_id: str | None
    year: str | None
    message: str
    context: dict = field(default_factory=dict)


@dataclass(frozen=True)
class HistoricalValidationReport:
    issues: list[HistoricalValidationIssue]

    @property
    def can_proceed(self) -> bool:
        return not any(i.severity == "block" for i in self.issues)

    def summary(self) -> dict[str, int]:
        out = {"block": 0, "error": 0, "warning": 0, "info": 0}
        for i in self.issues:
            out[i.severity] += 1
        return out


# ---------------------------------------------------------------------------
# Critical voices (used by DI_002 and the quality scorer)
# ---------------------------------------------------------------------------

CRITICAL_VOICE_GROUPS: dict[str, tuple[str, ...]] = {
    "revenue": ("pl.rev.net", "pl.rev.gross_total", "pl.rev.gross.product_sales"),
    "cogs": ("pl.cogs.total", "pl.cogs.materials.raw"),
    "cash": ("bs.nfp.cash",),
    "equity": (
        "bs.equity.share_capital_open",
        "bs.equity.share_capital.close",
        "bs.equity.retained_earnings_open",
        "bs.equity.retained_earnings.close",
        "bs.equity.total_close",
    ),
    "fa_or_nwc": (
        "bs.fa.tangible.gross_close",
        "bs.fa.tangible.net_close",
        "bs.nwc.ar.close",
        "bs.nwc.inventory.close",
    ),
}


def _has_any(values: MappedValues, candidates: Iterable[str], year: str) -> bool:
    return any(values.get(v, year) is not None for v in candidates)


# ---------------------------------------------------------------------------
# Individual rule implementations
# ---------------------------------------------------------------------------


def _di_002_y0_critical_voices(
    values: MappedValues, _registries: Registries, _project: Project
) -> list[HistoricalValidationIssue]:
    """DI_002 — Y0 actual present for each critical voice group."""
    issues: list[HistoricalValidationIssue] = []
    if "Y0" not in values.years_present:
        issues.append(
            HistoricalValidationIssue(
                rule_id="DI_002_y0_actual_complete",
                severity="block",
                voice_id=None,
                year="Y0",
                message="Y0 column is missing — Y0 actual is the mandatory anchor",
            )
        )
        return issues

    for group, candidates in CRITICAL_VOICE_GROUPS.items():
        if not _has_any(values, candidates, "Y0"):
            issues.append(
                HistoricalValidationIssue(
                    rule_id="DI_002_y0_actual_complete",
                    severity="block",
                    voice_id=None,
                    year="Y0",
                    message=(
                        f"No Y0 value mapped for critical group '{group}' "
                        f"(expected one of: {', '.join(candidates)})"
                    ),
                    context={"group": group, "candidates": list(candidates)},
                )
            )
    return issues


def _expected_pl_sign(voice_id: str) -> Literal["positive", "negative"] | None:
    """Hand-coded P&L sign expectation (M5 simplification).

    The voice_registry's ``sign`` field encodes the natural economic
    sign, which for P&L matches "revenue positive, cost negative". We
    use voice_id prefixes to keep the rule self-contained and avoid
    brittle field-by-field interpretations.
    """
    if voice_id.startswith("pl.rev."):
        return "positive"
    if voice_id.startswith(
        ("pl.cogs.", "pl.opex.", "pl.da.", "pl.impairment.")
    ):
        return "negative"
    return None


def _di_011_pl_sign_consistency(
    values: MappedValues, _registries: Registries, _project: Project
) -> list[HistoricalValidationIssue]:
    """DI_011 — P&L cost rows < 0, P&L revenue rows > 0 across all years."""
    issues: list[HistoricalValidationIssue] = []
    for voice_id, year_values in values.values.items():
        expected = _expected_pl_sign(voice_id)
        if expected is None:
            continue
        for year, amount in year_values.items():
            if amount == 0:
                continue
            if expected == "positive" and amount < 0:
                issues.append(
                    HistoricalValidationIssue(
                        rule_id="DI_011_actual_consuntivo_signed_consistent",
                        severity="error",
                        voice_id=voice_id,
                        year=year,
                        message=(
                            f"{voice_id} {year}: expected revenue ≥ 0 "
                            f"(got {amount})"
                        ),
                        context={"amount": amount, "expected_sign": "positive"},
                    )
                )
            elif expected == "negative" and amount > 0:
                issues.append(
                    HistoricalValidationIssue(
                        rule_id="DI_011_actual_consuntivo_signed_consistent",
                        severity="error",
                        voice_id=voice_id,
                        year=year,
                        message=(
                            f"{voice_id} {year}: expected cost ≤ 0 "
                            f"(got {amount})"
                        ),
                        context={"amount": amount, "expected_sign": "negative"},
                    )
                )
    return issues


def _balance_check_tolerance(total_assets: float) -> float:
    """Same tolerance used by DI_013 in the spec: max(1.0, 0.0001 × |assets|)."""
    return max(1.0, 0.0001 * abs(total_assets))


def _di_013_balance_check_historical(
    values: MappedValues, _registries: Registries, _project: Project
) -> list[HistoricalValidationIssue]:
    """DI_013 — for each historical year, |Σ SP_assets + Σ SP_liab + Σ SP_equity| ≤ tol.

    Operates directly on raw_voices (grouped by ``voice_user_section``)
    so the check works regardless of mapping completeness.
    """
    issues: list[HistoricalValidationIssue] = []
    asset_rows = values.raw_by_section.get("SP_assets", [])
    liab_rows = values.raw_by_section.get("SP_liabilities", [])
    eq_rows = values.raw_by_section.get("SP_equity", [])
    if not asset_rows and not liab_rows and not eq_rows:
        return issues

    by_year: dict[str, dict[str, float]] = {}
    for label, year, amount in asset_rows:
        by_year.setdefault(year, {"assets": 0.0, "liab": 0.0, "equity": 0.0})
        by_year[year]["assets"] += amount
    for label, year, amount in liab_rows:
        by_year.setdefault(year, {"assets": 0.0, "liab": 0.0, "equity": 0.0})
        by_year[year]["liab"] += amount
    for label, year, amount in eq_rows:
        by_year.setdefault(year, {"assets": 0.0, "liab": 0.0, "equity": 0.0})
        by_year[year]["equity"] += amount

    for year, totals in sorted(by_year.items()):
        delta = totals["assets"] + totals["liab"] + totals["equity"]
        tol = _balance_check_tolerance(totals["assets"])
        if abs(delta) > tol:
            issues.append(
                HistoricalValidationIssue(
                    rule_id="DI_013_balance_check_historical",
                    severity="block",
                    voice_id="bs.balance_check",
                    year=year,
                    message=(
                        f"Balance sheet does not balance in {year}: "
                        f"assets={totals['assets']:.2f}, "
                        f"liab={totals['liab']:.2f}, "
                        f"equity={totals['equity']:.2f}, Δ={delta:.2f} "
                        f"(tolerance {tol:.2f})"
                    ),
                    context={
                        "assets": totals["assets"],
                        "liabilities": totals["liab"],
                        "equity": totals["equity"],
                        "delta": delta,
                        "tolerance": tol,
                    },
                )
            )
    return issues


# Subtotal voice → list of expected component voice_ids. Conservative
# coverage for the historical phase (M5); the projected counterpart
# AI_005 in E0_post will extend these once the engine wires them.
_SUBTOTAL_COMPONENTS: dict[str, tuple[str, ...]] = {
    "pl.rev.gross_total": (
        "pl.rev.gross.product_sales",
        "pl.rev.gross.service_revenue",
        "pl.rev.gross.subscription",
        "pl.rev.gross.license",
        "pl.rev.gross.usage_based",
        "pl.rev.gross.rental",
        "pl.rev.gross.project_contract",
        "pl.rev.gross.other",
    ),
    "pl.cogs.total": (
        "pl.cogs.materials.raw",
        "pl.cogs.materials.purchased_finished",
        "pl.cogs.labour.direct",
        "pl.cogs.subcontracting",
        "pl.cogs.overhead.variable",
        "pl.cogs.overhead.fixed",
        "pl.cogs.inventory_writeoff",
        "pl.cogs.logistics_inbound",
    ),
}


def _ai_005_subtotal_consistency(
    values: MappedValues, _registries: Registries, _project: Project
) -> list[HistoricalValidationIssue]:
    """AI_005 — subtotal == Σ components within 0.5% tolerance."""
    issues: list[HistoricalValidationIssue] = []
    for subtotal_voice, components in _SUBTOTAL_COMPONENTS.items():
        if not values.has(subtotal_voice):
            continue
        for year in values.years_for(subtotal_voice):
            stored = values.get(subtotal_voice, year)
            if stored is None:
                continue
            present_components = [
                values.get(c, year) for c in components if values.has(c)
            ]
            present_components = [c for c in present_components if c is not None]
            if not present_components:
                continue
            expected = sum(present_components)
            tol = max(0.5, 0.005 * abs(stored))
            if abs(stored - expected) > tol:
                issues.append(
                    HistoricalValidationIssue(
                        rule_id="AI_005_subtotal_consistency_historical",
                        severity="error",
                        voice_id=subtotal_voice,
                        year=year,
                        message=(
                            f"{subtotal_voice} {year}: stored={stored:.2f} "
                            f"vs Σ components={expected:.2f} "
                            f"(Δ={stored - expected:.2f}, tol={tol:.2f})"
                        ),
                        context={
                            "stored": stored,
                            "expected": expected,
                            "delta": stored - expected,
                            "tolerance": tol,
                            "components_used": [c for c in components if values.has(c)],
                        },
                    )
                )
    return issues


def _sc_sign_rules(
    values: MappedValues, _registries: Registries, _project: Project
) -> list[HistoricalValidationIssue]:
    """SC_001/002/006/007 — sign rules on storico (revenues, costs, cash, D&A).

    Reuses the same prefix logic as DI_011 but emits distinct rule ids
    so the UI can group/filter. Cash-specific check operates on
    bs.nfp.cash via the mapping (not via raw section).
    """
    issues: list[HistoricalValidationIssue] = []
    cash_id = "bs.nfp.cash"
    if values.has(cash_id):
        for year, amount in values.values[cash_id].items():
            if amount < 0:
                issues.append(
                    HistoricalValidationIssue(
                        rule_id="SC_006_cash_positive",
                        severity="error",
                        voice_id=cash_id,
                        year=year,
                        message=f"Cash must be ≥ 0 (got {amount} in {year})",
                        context={"amount": amount},
                    )
                )

    for voice_id, year_values in values.values.items():
        for year, amount in year_values.items():
            if voice_id.startswith("pl.rev.") and amount < 0:
                issues.append(
                    HistoricalValidationIssue(
                        rule_id="SC_001_revenues_positive",
                        severity="error",
                        voice_id=voice_id,
                        year=year,
                        message=(
                            f"{voice_id} {year}: revenue must be ≥ 0 "
                            f"(got {amount})"
                        ),
                        context={"amount": amount},
                    )
                )
            elif voice_id.startswith("pl.da.") and amount > 0:
                issues.append(
                    HistoricalValidationIssue(
                        rule_id="SC_007_da_negative",
                        severity="error",
                        voice_id=voice_id,
                        year=year,
                        message=(
                            f"{voice_id} {year}: depreciation/amortisation "
                            f"must be ≤ 0 (got {amount})"
                        ),
                        context={"amount": amount},
                    )
                )
            elif (
                voice_id.startswith(("pl.cogs.", "pl.opex.", "pl.impairment."))
                and amount > 0
            ):
                issues.append(
                    HistoricalValidationIssue(
                        rule_id="SC_002_costs_negative",
                        severity="error",
                        voice_id=voice_id,
                        year=year,
                        message=(
                            f"{voice_id} {year}: operating cost must be ≤ 0 "
                            f"(got {amount})"
                        ),
                        context={"amount": amount},
                    )
                )
    return issues


def _cp_cross_period_rules(
    values: MappedValues, _registries: Registries, _project: Project
) -> list[HistoricalValidationIssue]:
    """CP_001/002 — opening = prior close (equity), revenue trend continuity.

    Skipped if fewer than 2 years are present in the actual data.
    """
    issues: list[HistoricalValidationIssue] = []
    if len(values.years_present) < 2:
        return issues

    # CP_001: equity.retained_earnings_open(t) ≈ equity.retained_earnings.close(t-1)
    open_id = "bs.equity.retained_earnings_open"
    close_id = "bs.equity.retained_earnings.close"
    if values.has(open_id) and values.has(close_id):
        order = values.years_present
        for prev, curr in zip(order, order[1:]):
            opening = values.get(open_id, curr)
            closing_prev = values.get(close_id, prev)
            if opening is None or closing_prev is None:
                continue
            tol = max(0.5, 0.005 * max(abs(opening), abs(closing_prev)))
            if abs(opening - closing_prev) > tol:
                issues.append(
                    HistoricalValidationIssue(
                        rule_id="CP_001_opening_equals_prior_close",
                        severity="warning",
                        voice_id=open_id,
                        year=curr,
                        message=(
                            f"Retained earnings opening {curr}={opening:.2f} "
                            f"differs from closing {prev}={closing_prev:.2f} "
                            f"(Δ={opening - closing_prev:.2f})"
                        ),
                        context={
                            "opening": opening,
                            "prior_close": closing_prev,
                        },
                    )
                )

    # CP_002: revenue trend continuity — flag YoY change > 100% as suspicious
    rev_id = "pl.rev.net"
    if values.has(rev_id):
        order = values.years_present
        for prev, curr in zip(order, order[1:]):
            v_prev = values.get(rev_id, prev)
            v_curr = values.get(rev_id, curr)
            if v_prev in (None, 0) or v_curr is None:
                continue
            yoy = (v_curr - v_prev) / abs(v_prev)
            if abs(yoy) > 1.0:
                issues.append(
                    HistoricalValidationIssue(
                        rule_id="CP_002_revenue_trend_continuity",
                        severity="warning",
                        voice_id=rev_id,
                        year=curr,
                        message=(
                            f"Revenue YoY {prev}→{curr}={yoy:+.1%} exceeds "
                            f"±100% — verify data quality"
                        ),
                        context={"yoy": yoy, "prev": v_prev, "curr": v_curr},
                    )
                )
    return issues


def _cf_configuration_rules(
    _values: MappedValues, _registries: Registries, project: Project
) -> list[HistoricalValidationIssue]:
    """CF_005/CF_006 — perimeter set, currency = EUR (pilot constraint)."""
    issues: list[HistoricalValidationIssue] = []
    if not project.perimeter:
        issues.append(
            HistoricalValidationIssue(
                rule_id="CF_005_perimeter_consistency",
                severity="error",
                voice_id=None,
                year=None,
                message=(
                    "Project perimeter is not set — declare it before "
                    "running the engine"
                ),
            )
        )
    if (project.currency or "").upper() != "EUR":
        issues.append(
            HistoricalValidationIssue(
                rule_id="CF_006_currency_consistency",
                severity="error",
                voice_id=None,
                year=None,
                message=(
                    f"Currency '{project.currency}' is not supported in "
                    f"pilot v1.1 (EUR only)"
                ),
                context={"currency": project.currency},
            )
        )
    return issues


_RULE_FNS = (
    _di_002_y0_critical_voices,
    _di_011_pl_sign_consistency,
    _di_013_balance_check_historical,
    _ai_005_subtotal_consistency,
    _sc_sign_rules,
    _cp_cross_period_rules,
    _cf_configuration_rules,
)


# ---------------------------------------------------------------------------
# Public runner
# ---------------------------------------------------------------------------


def run_historical_validation(
    values: MappedValues,
    registries: Registries,
    project: Project,
) -> HistoricalValidationReport:
    """Execute every M5 rule and return the consolidated report."""
    issues: list[HistoricalValidationIssue] = []
    for fn in _RULE_FNS:
        issues.extend(fn(values, registries, project))
    severity_order = {"block": 0, "error": 1, "warning": 2, "info": 3}
    issues.sort(
        key=lambda i: (
            severity_order[i.severity],
            i.rule_id,
            i.voice_id or "",
            i.year or "",
        )
    )
    return HistoricalValidationReport(issues=issues)


__all__ = [
    "CRITICAL_VOICE_GROUPS",
    "HistoricalValidationIssue",
    "HistoricalValidationReport",
    "Severity",
    "run_historical_validation",
]

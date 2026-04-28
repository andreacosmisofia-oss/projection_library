"""Add formula_python field to method_registry.yaml records.

M1.3 — populates the machine-readable Python formulas for the 62 methods
and 19 derived rules defined in registries/method_registry.yaml.

Mapping is hardcoded in METHOD_FORMULAS and DERIVED_RULE_FORMULAS.

Namespace assumed by formulas:
  voices, assumptions, drivers, kpis, year, prev_year, voice
  resolve(voice_id, year) -> effective_value (base + override delta)
  safe_div(num, den)      -> None if den == 0
  pmt(balance, rate, n)   -> annuity payment

Insertion rules:
  - For methods: formula_python is inserted right after formula_sintesi.
  - For derived_rules: formula_python is inserted right after formula.
  - Idempotent: if formula_python already exists for a record, it is
    overwritten in place (same indentation, same position).

Run from repo root or from this script's directory:
  python scripts/add_formulas.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = ROOT / "registries" / "method_registry.yaml"

METHOD_FORMULAS: dict[str, str] = {
    # extrapolation (4)
    "flat": "resolve(voice, prev_year)",
    "historical_avg_growth": "resolve(voice, prev_year) * (1 + assumptions[voice]['growth_rate'][year])",
    "cagr_extrapolation": "resolve(voice, 'Y0') * (1 + assumptions[voice]['cagr'][year]) ** {'Y1':1,'Y2':2,'Y3':3}[year]",
    "inflation_indexed_growth": "resolve(voice, prev_year) * (1 + assumptions[voice]['cpi_rate'][year])",

    # ratio (24)
    "pct_net_revenue": "assumptions[voice]['pct'][year] * resolve('pl.rev.net', year)",
    "pct_revenue_with_drift": "(assumptions[voice]['pct_start'][year] + (assumptions[voice]['pct_target'][year] - assumptions[voice]['pct_start'][year]) * assumptions[voice]['drift_progress'][year]) * resolve('pl.rev.net', year)",
    "pct_inventory_writeoff": "-abs(assumptions[voice]['rate'][year]) * resolve('bs.nwc.inventory.total_avg', year)",
    "pct_gross_revenue": "assumptions[voice]['pct'][year] * resolve('pl.rev.gross_total', year)",
    "pct_revenue_residual": "assumptions[voice]['pct'][year] * resolve('pl.rev.net', year)",
    "days_target": "assumptions[voice]['sign'][year] * safe_div(resolve(assumptions[voice]['denominator_voice'][year], year), 365) * assumptions[voice]['days'][year]",
    "days_target_with_drift": "assumptions[voice]['sign'][year] * safe_div(resolve(assumptions[voice]['denominator_voice'][year], year), 365) * (assumptions[voice]['days_start'][year] + (assumptions[voice]['days_target'][year] - assumptions[voice]['days_start'][year]) * assumptions[voice]['drift_progress'][year])",
    "pct_related_flow": "assumptions[voice]['sign'][year] * assumptions[voice]['pct'][year] * resolve(assumptions[voice]['denominator_voice'][year], year)",
    "allowance_pct_ar_gross": "-abs(assumptions[voice]['ecl_rate'][year]) * resolve('bs.nwc.ar.trade_gross', year)",
    "inventory_production_cycle_days": "assumptions[voice]['cycle_days'][year] * assumptions[voice]['unit_cost'][year] * drivers[f'driver.{voice}.production_volume'][year] / 365",
    "capex_pct_revenue": "assumptions[voice]['pct'][year] * resolve('pl.rev.net', year)",
    "capex_pct_gross_base": "assumptions[voice]['pct'][year] * abs(resolve('bs.fa.tangible.gross_close', prev_year))",
    "disposals_pct_gross_base": "-assumptions[voice]['rate'][year] * abs(resolve(assumptions[voice]['gross_voice'][year], prev_year))",
    "rou_new_leases_pct_base": "assumptions[voice]['rate'][year] * resolve('bs.fa.rou.gross_close', prev_year)",
    "lease_payment_pct_opening": "-assumptions[voice]['pct'][year] * abs(resolve('bs.nfp.lease_liability.close', prev_year))",
    "warranty_usage_pct_balance": "-assumptions[voice]['rate'][year] * abs(resolve('bs.provisions.warranty.balance_close', prev_year))",
    "employee_benefits_service_cost_rate": "assumptions[voice]['rate'][year] * abs(resolve('pl.opex.labour.total', year))",
    "employee_benefits_payments_pct_balance": "-assumptions[voice]['turnover'][year] * abs(resolve('bs.employee_benefits.balance_close', prev_year))",
    "warranty_rate_revenue": "-assumptions[voice]['rate'][year] * resolve('pl.rev.gross.product_sales', year)",
    "warranty_pct_installed_base": "-assumptions[voice]['rate'][year] * drivers[f'driver.{voice}.installed_base_value'][year]",
    "vat_balance_ratio": "assumptions[voice]['sign'][year] * assumptions[voice]['vat_rate'][year] * assumptions[voice]['avg_periods_unpaid'][year] * resolve(assumptions[voice]['flow_voice'][year], year) / 12",
    "dividend_payout_ratio": "-assumptions[voice]['payout'][year] * max(0, resolve('pl.net_income', prev_year))",
    "dividend_per_share": "-assumptions[voice]['dps'][year] * drivers[f'driver.{voice}.shares_outstanding'][year]",
    "deferred_tax_simplified": "resolve(voice, prev_year) * (1 + assumptions[voice]['drift'][year])",

    # operational_driver (12)
    "volume_price": "drivers[f'driver.{voice}.volume'][year] * assumptions[voice]['price_per_unit'][year]",
    "volume_unit_cost": "-drivers[f'driver.{voice}.volume'][year] * assumptions[voice]['unit_cost'][year]",
    "volume_price_split_growth": "(drivers[f'driver.{voice}.volume'][prev_year] * (1 + assumptions[voice]['volume_growth'][year])) * (assumptions[voice]['price'][prev_year] * (1 + assumptions[voice]['price_growth'][year]))",
    "bom_input_cost": "-drivers[f'driver.{voice}.volume'][year] * sum(drivers[f'driver.{voice}.bom_{m}_qty'][year] * assumptions[voice][f'bom_{m}_price'][year] for m in assumptions[voice]['bom_materials'][year])",
    "capacity_utilization_price": "drivers[f'driver.{voice}.capacity'][year] * assumptions[voice]['utilization_rate'][year] * assumptions[voice]['price_per_unit'][year]",
    "headcount_unit_cost": "-drivers[f'driver.{voice}.headcount'][year] * assumptions[voice]['cost_per_head'][year]",
    "multi_driver_chain": "prod(drivers[f'driver.{voice}.{d}'][year] for d in assumptions[voice]['driver_chain'][year])",
    "per_employee_fixed_cost": "-drivers['driver.headcount.total'][year] * assumptions[voice]['cost_per_employee'][year]",
    "variable_fixed_split": "-(drivers[f'driver.{voice}.volume'][year] * assumptions[voice]['variable_rate'][year] + assumptions[voice]['fixed_base'][year])",
    "capex_per_unit": "drivers[f'driver.{voice}.new_units'][year] * assumptions[voice]['capex_per_unit'][year]",
    "rou_new_leases_per_unit": "drivers[f'driver.{voice}.new_units'][year] * assumptions[voice]['lease_value_per_unit'][year]",
    "occupancy_load_factor": "drivers[f'driver.{voice}.units'][year] * drivers[f'driver.{voice}.days_open'][year] * assumptions[voice]['load_factor'][year] * assumptions[voice]['tariff'][year]",

    # build_up (6)
    "account_by_account": "sum(drivers[f'driver.{voice}.account_{a}'][year] for a in assumptions[voice]['top_accounts'][year]) + assumptions[voice]['long_tail'][year]",
    "cohort_buildup": "sum(drivers[f'driver.saas.cohort_{c}_size'][year] * (assumptions[voice]['retention_rate'][year] ** drivers[f'driver.saas.cohort_{c}_age'][year]) * assumptions[voice]['arpu'][year] for c in assumptions[voice]['cohort_ids'][year])",
    "backlog_conversion": "resolve(f'driver.{voice}.backlog_open', year) * assumptions[voice]['conversion_rate'][year] + drivers[f'driver.{voice}.new_bookings'][year] * assumptions[voice]['partial_conversion_rate'][year]",
    "order_intake_rollforward": "resolve(f'driver.{voice}.backlog_open', year) + drivers[f'driver.{voice}.intake'][year] - drivers[f'driver.{voice}.backlog_close'][year]",
    "book_to_bill": "safe_div(drivers[f'driver.{voice}.orders'][year], assumptions[voice]['b2b_ratio'][year])",
    "contract_renewal_waterfall": "assumptions[voice]['active'][year] + assumptions[voice]['expiring'][year] * assumptions[voice]['renewal_rate'][year] * (1 + assumptions[voice]['uplift'][year]) + assumptions[voice]['new'][year]",

    # bridge (2)
    "revenue_bridge": "resolve(voice, prev_year) + sum(assumptions[voice][f'movement_{m}'][year] for m in assumptions[voice]['movements'][year])",
    "arr_bridge": "resolve(voice, prev_year) + drivers['driver.saas.new_arr'][year] + drivers['driver.saas.expansion_arr'][year] - abs(drivers['driver.saas.churn_arr'][year]) - abs(drivers['driver.saas.contraction_arr'][year])",

    # probabilistic (3)
    "pipeline_weighted": "sum(drivers[f'driver.{voice}.pipeline_{phase}'][year] * assumptions[voice][f'win_rate_{phase}'][year] for phase in assumptions[voice]['pipeline_phases'][year])",
    "weighted_exposure": "-sum(assumptions[voice][f'case_{c}_probability'][year] * assumptions[voice][f'case_{c}_exposure'][year] for c in assumptions[voice]['cases'][year])",
    "allowance_aging_bucket": "-sum(assumptions[voice][f'bucket_{b}_amount'][year] * assumptions[voice][f'bucket_{b}_ecl_rate'][year] for b in assumptions[voice]['buckets'][year])",

    # rollforward (1)
    "rollforward_explicit_flow": "resolve(voice, prev_year) + assumptions[voice]['inflow'][year] - abs(assumptions[voice]['outflow'][year])",

    # debt_schedule (2)
    "term_loan_amortization_linear": "-safe_div(drivers[f'driver.{voice}.initial_principal'][year], drivers[f'driver.{voice}.term_years'][year])",
    "term_loan_amortization_annuity": "-pmt(resolve(voice, prev_year), drivers[f'driver.{voice}.rate'][year], drivers[f'driver.{voice}.remaining_years'][year])",

    # manual (8)
    "manual_one_off": "assumptions[voice]['value'][year]",
    "manual_provision_schedule": "-abs(assumptions[voice]['value'][year])",
    "manual_zero_placeholder": "0.0",
    "manual_schedule": "assumptions[voice]['value'][year]",
    "manual_zero": "0.0",
    "manual_impairment_schedule": "-abs(assumptions[voice]['value'][year])",
    "manual_lease_schedule": "assumptions[voice]['value'][year]",
    "manual_tax_input": "assumptions[voice]['value'][year]",
}

DERIVED_RULE_FORMULAS: dict[str, str] = {
    "da_mid_year_convention": "-safe_div(max(0, (resolve(assumptions[voice]['gross_voice'][year], prev_year) + resolve(assumptions[voice]['gross_voice'][year], year)) / 2 - assumptions[voice]['non_depreciable'][year]), assumptions[voice]['useful_life'][year])",
    "ifrs15_movement_from_sp": "-(resolve('bs.nwc.contract_liab', year) - resolve('bs.nwc.contract_liab', prev_year)) + (resolve('bs.nwc.contract_assets', year) - resolve('bs.nwc.contract_assets', prev_year))",
    "nwc_change_for_cf": "-(resolve('bs.nwc.operating.final', year) - resolve('bs.nwc.operating.final', prev_year))",
    "retained_earnings_identity": "resolve('bs.equity.retained_earnings.close', prev_year) + resolve('pl.net_income', year) + resolve('bs.equity.dividends', year) + resolve('bs.equity.buyback', year)",
    "cash_identity_from_cf": "resolve('bs.nfp.cash', prev_year) + resolve('cf.net_change_cash', year)",
    "interest_expense_avg_balance": "-abs((resolve('bs.nfp.borrowings.balance_close', prev_year) + resolve('bs.nfp.borrowings.balance_close', year)) / 2) * assumptions[voice]['cost_of_debt'][year]",
    "lease_interest_avg_balance": "-abs((resolve('bs.nfp.lease_liability.close', prev_year) + resolve('bs.nfp.lease_liability.close', year)) / 2) * assumptions[voice]['lease_implicit_rate'][year]",
    "interest_income_cash_avg": "(resolve('bs.nfp.cash', prev_year) + resolve('bs.nfp.cash', year)) / 2 * assumptions[voice]['cash_yield'][year]",
    "tax_current_etr_simplified": "-max(0, resolve('pl.ebt', year)) * assumptions[voice]['etr'][year]",
    "balance_check": "resolve('bs.total_assets', year) + resolve('bs.total_liabilities', year) - resolve('bs.equity.total_close', year)",
    "taxable_income_bridge": "resolve('pl.ebt', year) + assumptions[voice]['permanent_addbacks'][year] - assumptions[voice]['permanent_deductions'][year] + assumptions[voice]['temporary_differences'][year]",
    "nol_utilization": "min(resolve('pl.taxable_income', year), resolve('bs.tax.nol_carryforward.close', prev_year) * assumptions[voice]['utilization_limit'][year])",
    "current_tax_with_nol": "-max(0, resolve('pl.taxable_income', year) - resolve('pl.nol_used', year)) * assumptions[voice]['etr'][year]",
    "gross_close_aggregation": "resolve(f'bs.fa.{family}.gross_open', year) + sum(resolve(f, year) for f in assumptions[voice]['inflows'][year]) - sum(abs(resolve(f, year)) for f in assumptions[voice]['outflows'][year])",
    "acc_depr_close_aggregation": "resolve(f'bs.fa.{family}.acc_depr_open', year) + resolve(f'pl.da.{family}', year) - abs(resolve(f'bs.fa.{family}.disposals_acc_depr', year)) - abs(resolve(f'bs.fa.{family}.impairment_acc', year))",
    "net_book_value": "resolve(f'bs.fa.{family}.gross_close', year) + resolve(f'bs.fa.{family}.acc_depr_close', year)",
    "subtotal_aggregation": "sum(resolve(c, year) for c in assumptions[voice]['children'][year])",
    "employee_benefits_interest_cost": "-abs((resolve('bs.employee_benefits.balance_close', prev_year) + resolve('bs.employee_benefits.balance_close', year)) / 2) * assumptions[voice]['discount_rate'][year]",
    "lease_liability_interest_accrued": "-abs((resolve('bs.nfp.lease_liability.close', prev_year) + resolve('bs.nfp.lease_liability.close', year)) / 2) * assumptions[voice]['lease_implicit_rate'][year]",
}


def yaml_quote(value: str) -> str:
    """Wrap a Python expression as a YAML double-quoted scalar.

    Formulas use single quotes for dict keys, so double quotes are safe
    as long as no embedded double quote or backslash exists.
    """
    if '"' in value or "\\" in value:
        raise ValueError(f"unsupported character in formula: {value!r}")
    return f'"{value}"'


def patch_registry(text: str) -> tuple[str, dict[str, int]]:
    """Insert formula_python lines into the registry text.

    Returns the patched text and a stats dict.
    """
    lines = text.splitlines(keepends=False)
    out: list[str] = []
    section: str | None = None        # "methods" | "derived_rules" | None
    current_id: str | None = None
    current_indent: str = ""
    formula_anchor = False             # next-line check after id-line
    stats = {
        "methods_seen": 0,
        "methods_patched": 0,
        "methods_overwritten": 0,
        "derived_seen": 0,
        "derived_patched": 0,
        "derived_overwritten": 0,
        "missing_method_mappings": 0,
        "missing_derived_mappings": 0,
        "unknown_method_ids": [],
        "unknown_derived_ids": [],
    }

    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        stripped = line.lstrip()

        # Section markers (top-level keys).
        if line.startswith("methods:"):
            section = "methods"
            out.append(line)
            i += 1
            continue
        if line.startswith("derived_rules:"):
            section = "derived_rules"
            out.append(line)
            i += 1
            continue

        # Record start.
        if section == "methods" and stripped.startswith("- method_id:"):
            current_id = stripped.split(":", 1)[1].strip()
            current_indent = line[: len(line) - len(stripped)]
            stats["methods_seen"] += 1
            out.append(line)
            i += 1
            continue

        if section == "derived_rules" and stripped.startswith("- derived_rule_id:"):
            current_id = stripped.split(":", 1)[1].strip()
            current_indent = line[: len(line) - len(stripped)]
            stats["derived_seen"] += 1
            out.append(line)
            i += 1
            continue

        # Within a record, look for the anchor key after which formula_python goes.
        # methods   -> insert after formula_sintesi
        # derived   -> insert after formula
        if current_id is not None and section == "methods":
            # Detect the field key. Indentation expected: current_indent + "  ".
            field_indent = current_indent + "  "
            if line.startswith(field_indent + "formula_sintesi:"):
                out.append(line)
                # Look ahead: if next line is already formula_python, replace it.
                next_line = lines[i + 1] if i + 1 < n else ""
                formula = METHOD_FORMULAS.get(current_id)
                if formula is None:
                    stats["missing_method_mappings"] += 1
                    stats["unknown_method_ids"].append(current_id)
                    i += 1
                    continue
                inserted = f"{field_indent}formula_python: {yaml_quote(formula)}"
                if next_line.startswith(field_indent + "formula_python:"):
                    out.append(inserted)
                    stats["methods_overwritten"] += 1
                    i += 2
                else:
                    out.append(inserted)
                    stats["methods_patched"] += 1
                    i += 1
                continue

        if current_id is not None and section == "derived_rules":
            field_indent = current_indent + "  "
            if line.startswith(field_indent + "formula:") and not line.startswith(field_indent + "formula_python:"):
                out.append(line)
                next_line = lines[i + 1] if i + 1 < n else ""
                formula = DERIVED_RULE_FORMULAS.get(current_id)
                if formula is None:
                    stats["missing_derived_mappings"] += 1
                    stats["unknown_derived_ids"].append(current_id)
                    i += 1
                    continue
                inserted = f"{field_indent}formula_python: {yaml_quote(formula)}"
                if next_line.startswith(field_indent + "formula_python:"):
                    out.append(inserted)
                    stats["derived_overwritten"] += 1
                    i += 2
                else:
                    out.append(inserted)
                    stats["derived_patched"] += 1
                    i += 1
                continue

        out.append(line)
        i += 1

    if text.endswith("\n"):
        return "\n".join(out) + "\n", stats
    return "\n".join(out), stats


def main() -> int:
    text = REGISTRY_PATH.read_text(encoding="utf-8")
    patched, stats = patch_registry(text)
    REGISTRY_PATH.write_text(patched, encoding="utf-8")

    print(f"file: {REGISTRY_PATH.relative_to(ROOT)}")
    print(f"methods seen:        {stats['methods_seen']}")
    print(f"methods patched:     {stats['methods_patched']}")
    print(f"methods overwritten: {stats['methods_overwritten']}")
    print(f"derived seen:        {stats['derived_seen']}")
    print(f"derived patched:     {stats['derived_patched']}")
    print(f"derived overwritten: {stats['derived_overwritten']}")

    issues = 0
    if stats["unknown_method_ids"]:
        print(f"missing method mappings ({len(stats['unknown_method_ids'])}):", file=sys.stderr)
        for mid in stats["unknown_method_ids"]:
            print(f"  - {mid}", file=sys.stderr)
        issues += 1
    if stats["unknown_derived_ids"]:
        print(f"missing derived mappings ({len(stats['unknown_derived_ids'])}):", file=sys.stderr)
        for did in stats["unknown_derived_ids"]:
            print(f"  - {did}", file=sys.stderr)
        issues += 1

    extra_methods = set(METHOD_FORMULAS) - {*[]}  # placeholder
    return 0 if issues == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

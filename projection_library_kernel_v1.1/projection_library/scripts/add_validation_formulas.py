"""Add formula_python field to validation_rules.yaml records.

M1.3 — populates the machine-readable Python formulas / custom_function
references for the 73 validation rules defined in
registries/validation_rules.yaml.

Mapping is hardcoded in RULE_FORMULAS keyed by rule_id prefix (e.g.
"DI_001"); the actual rule_id in the YAML extends the prefix with a
descriptive suffix (e.g. "DI_001_required_voices_present").

Insertion rule:
  formula_python is inserted right after regola_sintesi.
  Idempotent: if formula_python already exists, it is overwritten in place.

Markdown autolinks (e.g. "[pl.rev.net](http://pl.rev.net)") in the source
mapping have been pre-cleaned to plain identifiers (e.g. "pl.rev.net").

Run from repo root or from this script's directory:
  python scripts/add_validation_formulas.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = ROOT / "registries" / "validation_rules.yaml"

RULE_FORMULAS: dict[str, str] = {
    # data_integrity (14)
    "DI_001": "all(v in voices for v in required_voices_tier[project.tier_level])",
    "DI_002": "all(voices[v].get('Y0') is not None for v in mapped_voices)",
    "DI_003": "len(mapped_voice_ids) == len(set(mapped_voice_ids))",
    "DI_004": "all(v in voice_registry for v in mapped_voice_ids)",
    "DI_005": "all(m in method_registry for m in configured_method_ids)",
    "DI_006": "all((voice, asm) in assumptions for voice, method in method_configs.items() for asm in method_registry[method]['assumptions'])",
    "DI_007": "all(driver_id in drivers for driver_id in required_drivers(method_configs) if not drivers.get(driver_id, {}).get('skipped'))",
    "DI_008": "not any(voices[v].get('Y0', 0) > 0 for v in mapped_voices if voice_registry[v]['sign'] == 'negative' and voice_registry[v]['nature'] == 'driver')",
    "DI_009": "custom_function: validators.di_009_acyclicity_check",
    "DI_010": "all(dep in voice_registry for v in voice_registry for dep in voice_dependencies.get(v, {}).get('depends_on_voices', []))",
    "DI_011": "not any(voice_registry[v]['nature'] in ('placeholder', 'driver_placeholder') and v in method_configs for v in voice_registry)",
    "DI_012": "project.sector_pack in sector_pack_registry",
    "DI_013": "abs(sum(voices[v].get('Y0',0) for v in bs_asset_voices) + sum(voices[v].get('Y0',0) for v in bs_liab_equity_voices)) <= max(1.0, 0.0001 * abs(sum(voices[v].get('Y0',0) for v in bs_asset_voices)))",
    "DI_014": "project.horizon_years in (1, 2, 3)",

    # accounting_identity (11)
    "AI_001": "abs(resolve('bs.balance_check', year)) <= max(1.0, 0.0001 * abs(resolve('bs.total_assets', year)))",
    "AI_002": "abs(resolve('bs.nfp.cash', year) - (resolve('bs.nfp.cash', prev_year) + resolve('cf.net_change_cash', year))) <= 0.01",
    "AI_003": "abs(resolve('bs.equity.retained_earnings.close', year) - (resolve('bs.equity.retained_earnings.close', prev_year) + resolve('pl.net_income', year) + resolve('bs.equity.dividends', year) + resolve('bs.equity.buyback', year))) <= 0.01",
    "AI_004": "abs(resolve('bs.nfp.net_debt', year) - (resolve('bs.nfp.borrowings.balance_close', year) + resolve('bs.nfp.lease_liability.close', year) - resolve('bs.nfp.cash', year))) <= 0.01",
    "AI_005": "custom_function: validators.ai_005_subtotal_consistency",
    "AI_006": "abs(resolve('pl.ebit', year) - (resolve('pl.ebitda.final', year) + resolve('pl.da.total', year) + resolve('pl.impairment.total', year))) <= 0.01",
    "AI_007": "abs(resolve('pl.ebitda.final', year) - (resolve('pl.gross_profit.final', year) + resolve('pl.opex.total', year) + resolve('pl.provisions.total', year))) <= 0.01",
    "AI_008": "abs(resolve('pl.ebt', year) - (resolve('pl.ebit', year) + resolve('pl.financial.total_net', year) + resolve('pl.equity_method_result', year) + resolve('pl.other.non_operating_total', year))) <= 0.01",
    "AI_009": "custom_function: validators.ai_009_provisions_rollforward",
    "AI_010": "custom_function: validators.ai_010_eb_rollforward",
    "AI_011": "abs(resolve('cf.operating.nwc_change', year) - (resolve('bs.nwc.operating.final', year) - resolve('bs.nwc.operating.final', prev_year))) <= 0.01",

    # sign_consistency (9)
    "SC_001": "resolve('pl.rev.gross_total', year) >= 0",
    "SC_002": "resolve('pl.cogs.total.final', year) <= 0",
    "SC_003": "all(resolve(v, year) >= 0 for v in bs_asset_voices if voice_registry[v]['sign'] == 'positive')",
    "SC_004": "all(resolve(v, year) <= 0 for v in bs_liab_voices if voice_registry[v]['sign'] == 'negative')",
    "SC_005": "resolve('pl.tax.current', year) <= 0",
    "SC_006": "resolve('pl.da.total', year) <= 0",
    "SC_007": "resolve('pl.ebitda.final', year) > -abs(resolve('pl.rev.gross_total', year))",
    "SC_008": "resolve('pl.financial.interest_expense', year) <= 0",
    "SC_009": "resolve('bs.nfp.cash', year) >= 0",

    # range_plausibility (22)
    "RP_001": "safe_div(resolve('pl.rev.net.final', year) - resolve('pl.rev.net.final', prev_year), abs(resolve('pl.rev.net.final', prev_year))) >= -0.50",
    "RP_002": "safe_div(resolve('pl.gross_profit.final', year), resolve('pl.rev.net.final', year)) >= -1.00",
    "RP_003": "safe_div(resolve('pl.ebitda.final', year), resolve('pl.rev.net.final', year)) >= -0.50",
    "RP_004": "safe_div(resolve('bs.nwc.ar.trade_gross', year) * 365, resolve('pl.rev.net.final', year)) <= 365",
    "RP_005": "safe_div(resolve('bs.nwc.inventory.total', year) * 365, abs(resolve('pl.cogs.total.final', year))) <= 365",
    "RP_006": "safe_div(abs(resolve('bs.nwc.ap.trade', year)) * 365, abs(resolve('pl.cogs.total.final', year))) <= 365",
    "RP_007": "safe_div(resolve('bs.nfp.net_debt', year), abs(resolve('pl.ebitda.final', year))) <= 10.0",
    "RP_008": "safe_div(resolve('pl.ebitda.final', year), abs(resolve('pl.financial.interest_expense', year))) >= 1.0",
    "RP_009": "0.0 <= assumptions.get('pl.tax.current', {}).get('etr', {}).get(year, 0.25) <= 0.60",
    "RP_010": "safe_div(abs(resolve('cf.investing.capex.total', year)), resolve('pl.rev.net.final', year)) <= 0.50",
    "RP_011": "safe_div(abs(resolve('pl.da.total', year)), resolve('bs.fa.tangible.gross_close', year) + 0.01) <= 0.50",
    "RP_012": "safe_div(resolve('pl.provisions.total', year), resolve('pl.rev.net.final', year)) >= -0.20",
    "RP_013": "safe_div(resolve('pl.opex.labour.total', year), resolve('pl.rev.net.final', year)) >= -0.80",
    "RP_014": "custom_function: validators.rp_014_revenue_per_head",
    "RP_015": "safe_div(resolve('bs.nwc.operating.final', year), resolve('pl.rev.net.final', year)) >= -0.50",
    "RP_016": "resolve('bs.equity.total_close', year) > 0",
    "RP_017": "resolve('pl.impairment.goodwill', year) >= -resolve('bs.fa.goodwill.net_close', prev_year)",
    "RP_018": "safe_div(resolve('bs.tax.dta_total', year), abs(resolve('pl.tax.current', year)) + 0.01) <= 5.0",
    "RP_019": "resolve('bs.tax.nol_carryforward.close', year) >= 0",
    "RP_020": "safe_div(abs(resolve('bs.nfp.lease_liability.close', year)), resolve('bs.total_assets', year)) <= 0.60",
    "RP_021": "all(-0.50 <= assumptions.get(v, {}).get('growth_rate', {}).get(year, 0) <= 2.00 for v in method_configs if method_configs[v] == 'historical_avg_growth')",
    "RP_022": "all(safe_div(drivers.get(f'driver.{v}.volume', {}).get(year, 0) - drivers.get(f'driver.{v}.volume', {}).get(prev_year, 0), abs(drivers.get(f'driver.{v}.volume', {}).get(prev_year, 1))) <= 2.00 for v in method_configs if method_configs[v] == 'volume_price')",

    # cross_period (8)
    "CP_001": "custom_function: validators.cp_001_opening_equals_prior_close",
    "CP_002": "custom_function: validators.cp_002_revenue_growth_continuity",
    "CP_003": "custom_function: validators.cp_003_margin_continuity",
    "CP_004": "custom_function: validators.cp_004_nwc_days_continuity",
    "CP_005": "safe_div(abs(resolve('cf.investing.capex.total', year)) - abs(resolve('cf.investing.capex.total', prev_year)), abs(resolve('cf.investing.capex.total', prev_year)) + 0.01) <= 1.00",
    "CP_006": "resolve('bs.nfp.borrowings.balance_close', year) <= resolve('bs.nfp.borrowings.balance_close', prev_year) * 1.50",
    "CP_007": "safe_div(resolve('bs.provisions.total', year), resolve('bs.provisions.total', prev_year) + 0.01) <= 3.0",
    "CP_008": "custom_function: validators.cp_008_headcount_growth",

    # configuration (6)
    "CF_001": "project.tier_level in ('minimum', 'standard', 'advanced')",
    "CF_002": "project.horizon_years == 3",
    "CF_003": "project.currency == 'EUR'",
    "CF_004": "project.accounting_standard == 'IFRS'",
    "CF_005": "project.perimeter in ('consolidated', 'legal_entity', 'cgu')",
    "CF_006": "len(project.country) == 2 and project.country.isupper()",

    # calculation_quality (3)
    "CQ_001": "abs(resolve('pl.rev.net.proxy', year) - resolve('pl.rev.net.final', year)) <= max(1.0, 0.001 * abs(resolve('pl.rev.net.final', year)))",
    "CQ_002": "custom_function: validators.cq_002_cf_op_consistency",
    "CQ_003": "abs(resolve('bs.balance_check', year)) <= max(1.0, 0.0001 * abs(resolve('bs.total_assets', year))) and abs(resolve('bs.balance_check', year)) <= abs(resolve('bs.balance_check', prev_year)) * 1.10",
}


def yaml_quote(value: str) -> str:
    """Wrap a Python expression as a YAML double-quoted scalar.

    Formulas use single quotes for dict keys and may contain colons
    (e.g. 'custom_function: validators.x'); double quotes are safe as
    long as no embedded double quote or backslash is present.
    """
    if '"' in value or "\\" in value:
        raise ValueError(f"unsupported character in formula: {value!r}")
    return f'"{value}"'


def rule_prefix(rule_id: str) -> str:
    """Return the 'XX_NNN' prefix of a full rule_id.

    Example: 'DI_001_required_voices_present' -> 'DI_001'.
    """
    parts = rule_id.split("_", 2)
    if len(parts) < 2:
        return rule_id
    return f"{parts[0]}_{parts[1]}"


def is_continuation(line: str, field_indent: str) -> bool:
    """Return True if `line` continues the value of the previous field key.

    A continuation line in YAML plain block style is indented strictly more
    than the key. Empty lines are treated as continuations to preserve them.
    """
    if line == "":
        return True
    if not line.startswith(field_indent):
        return False
    if len(line) <= len(field_indent):
        return True
    return line[len(field_indent)] == " "


def patch_registry(text: str) -> tuple[str, dict]:
    lines = text.splitlines(keepends=False)
    out: list[str] = []
    current_id: str | None = None
    current_indent: str = ""
    stats = {
        "rules_seen": 0,
        "rules_patched": 0,
        "rules_overwritten": 0,
        "missing_mappings": [],
    }

    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        stripped = line.lstrip()

        if stripped.startswith("- rule_id:"):
            current_id = stripped.split(":", 1)[1].strip()
            current_indent = line[: len(line) - len(stripped)]
            stats["rules_seen"] += 1
            out.append(line)
            i += 1
            continue

        if current_id is not None:
            field_indent = current_indent + "  "
            if line.startswith(field_indent + "regola_sintesi:"):
                out.append(line)
                i += 1
                # Consume any continuation lines belonging to regola_sintesi
                # (folded plain scalars can wrap to deeper-indented lines).
                while i < n and is_continuation(lines[i], field_indent):
                    out.append(lines[i])
                    i += 1
                prefix = rule_prefix(current_id)
                formula = RULE_FORMULAS.get(prefix)
                if formula is None:
                    stats["missing_mappings"].append(current_id)
                    continue
                inserted = f"{field_indent}formula_python: {yaml_quote(formula)}"
                if i < n and lines[i].startswith(field_indent + "formula_python:"):
                    out.append(inserted)
                    stats["rules_overwritten"] += 1
                    i += 1
                else:
                    out.append(inserted)
                    stats["rules_patched"] += 1
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
    print(f"rules seen:        {stats['rules_seen']}")
    print(f"rules patched:     {stats['rules_patched']}")
    print(f"rules overwritten: {stats['rules_overwritten']}")

    if stats["missing_mappings"]:
        print(f"missing mappings ({len(stats['missing_mappings'])}):", file=sys.stderr)
        for rid in stats["missing_mappings"]:
            print(f"  - {rid}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

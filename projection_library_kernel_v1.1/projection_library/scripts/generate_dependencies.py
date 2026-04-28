"""Generate voice_dependencies.yaml from voice_registry + method_registry.

M1.4 — for each voice in voice_registry.yaml, resolve:
  - phase / phase_proxy / nature
  - depends_on_voices       (literal resolve('voice_id', ...) extracted
                             from the formula_python of its default_method,
                             plus a manual override map for known subtotals)
  - depends_on_assumptions  (assumptions[voice]['<key>'] keys)
  - depends_on_drivers      (drivers['driver.x.y'] / f-string driver refs /
                             f-string resolves)
  - formula_rule_id         (method_id or derived_rule_id; null if nature=driver)
  - dependency_type         (driver_input | derived_identity | method_output |
                             reference)

Static extraction limitations:
  Methods that iterate over dynamic children (e.g. subtotal_aggregation,
  gross_close_aggregation, account_by_account) cannot expose their voice
  dependencies via static regex on the formula. For the principal subtotals
  / identities the voice list is hardcoded in MANUAL_VOICE_DEPS below.

No topological sort is performed here.

Run from repo root or from this script's directory:
  python scripts/generate_dependencies.py
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
VOICE_REG = ROOT / "registries" / "voice_registry.yaml"
METHOD_REG = ROOT / "registries" / "method_registry.yaml"
OUT_PATH = ROOT / "registries" / "voice_dependencies.yaml"


# Manual overrides for subtotals / identities whose dependencies cannot
# be extracted statically from formula_python. Lists are taken verbatim
# from the M1.4 spec and used as-is, even when an entry does not yet
# exist in voice_registry.yaml — dangling refs are reported by the
# script and resolved in a downstream pass.
MANUAL_VOICE_DEPS: dict[str, list[str]] = {
    "pl.gross_profit": [
        "pl.rev.net",
        "pl.cogs.total",
    ],
    "pl.ebitda": [
        "pl.gross_profit",
        "pl.opex.total",
        "pl.provisions.total",
    ],
    "pl.ebit": [
        "pl.ebitda",
        "pl.da.total",
        "pl.impairment.total",
    ],
    "pl.ebt": [
        "pl.ebit",
        "pl.financial.total_net",
        "pl.equity_method_result",
        "pl.other.non_operating_total",
        "pl.other.fair_value_gain_loss_investment_property",
    ],
    "pl.tax.total": [
        "pl.tax.current",
        "pl.tax.deferred",
    ],
    "pl.net_income": [
        "pl.ebt",
        "pl.tax.total",
    ],
    "pl.rev.net": [
        "pl.rev.gross_total",
        "pl.rev.deductions.total",
        "pl.rev.adjustments_total",
    ],
    "pl.cogs.total": [
        "pl.cogs.materials.raw",
        "pl.cogs.materials.consumables",
        "pl.cogs.subcontracting",
        "pl.cogs.labour.direct",
        "pl.cogs.overhead",
        "pl.cogs.inventory_writeoff",
        "pl.cogs.wip_capitalization",
    ],
    "bs.equity.total_close": [
        "bs.equity.share_capital.close",
        "bs.equity.reserves",
        "bs.equity.retained_earnings.close",
        "bs.equity.oci_total",
        "bs.equity.nci.close",
    ],
    "bs.nfp.net_debt": [
        "bs.nfp.borrowings.balance_close",
        "bs.nfp.lease_liability.close",
        "bs.nfp.cash",
    ],
    "cf.net_change_cash": [
        "cf.operating.total",
        "cf.investing.total",
        "cf.financing.total",
    ],
    "bs.balance_check": [
        "bs.total_assets",
        "bs.total_liabilities_equity",
    ],
}


RE_RESOLVE_LITERAL = re.compile(r"resolve\(\s*['\"]([^'\"]+)['\"]")
RE_RESOLVE_FSTR = re.compile(r"resolve\(\s*f['\"]([^'\"]+)['\"]")
RE_DRIVERS_LITERAL = re.compile(r"drivers\[\s*['\"]([^'\"]+)['\"]")
RE_DRIVERS_FSTR = re.compile(r"drivers\[\s*f['\"]([^'\"]+)['\"]")
RE_ASSUMPTIONS = re.compile(r"assumptions\[voice\]\[\s*['\"]([^'\"]+)['\"]")
RE_ASSUMPTIONS_FSTR = re.compile(r"assumptions\[voice\]\[\s*f['\"]([^'\"]+)['\"]")


def extract_from_formula(formula: str, known_voice_ids: set[str]):
    """Return (voices, drivers, assumptions) referenced in a formula."""
    if not formula:
        return [], [], []

    voices: list[str] = []
    for m in RE_RESOLVE_LITERAL.findall(formula):
        if m in known_voice_ids and m not in voices:
            voices.append(m)

    drivers: list[str] = []
    for rx in (RE_DRIVERS_LITERAL, RE_DRIVERS_FSTR, RE_RESOLVE_FSTR):
        for m in rx.findall(formula):
            if m not in drivers:
                drivers.append(m)

    assumptions: list[str] = []
    for rx in (RE_ASSUMPTIONS, RE_ASSUMPTIONS_FSTR):
        for m in rx.findall(formula):
            if m not in assumptions:
                assumptions.append(m)

    return voices, drivers, assumptions


def map_dependency_type(nature: str) -> str:
    if nature == "driver":
        return "driver_input"
    if nature == "derived_identity":
        return "derived_identity"
    if nature == "derived":
        return "method_output"
    if nature in ("reference", "placeholder", "driver_placeholder", "driver_slot"):
        return "reference"
    return "reference"


def get_formula(default_method: str, methods_by_id: dict, rules_by_id: dict):
    if not default_method:
        return None, None
    if default_method in methods_by_id:
        return default_method, methods_by_id[default_method].get("formula_python")
    if default_method in rules_by_id:
        return default_method, rules_by_id[default_method].get("formula_python")
    return None, None


def main() -> None:
    voice_data = yaml.safe_load(VOICE_REG.read_text())
    method_data = yaml.safe_load(METHOD_REG.read_text())

    methods_by_id = {m["method_id"]: m for m in method_data.get("methods", [])}
    rules_by_id = {r["derived_rule_id"]: r for r in method_data.get("derived_rules", [])}
    known_voice_ids = {v["voice_id"] for v in voice_data["voices"]}

    out_voices: list[dict] = []
    for v in voice_data["voices"]:
        voice_id = v["voice_id"]
        nature = v["nature"]
        default_method = v.get("default_method")

        rule_id, formula = get_formula(default_method, methods_by_id, rules_by_id)
        formula_rule_id = None if nature == "driver" else rule_id

        voices_dep, drivers_dep, assumps_dep = extract_from_formula(
            formula or "", known_voice_ids
        )
        voices_dep = [x for x in voices_dep if x != voice_id]

        # Apply manual override for known subtotals / identities
        if voice_id in MANUAL_VOICE_DEPS:
            voices_dep = list(MANUAL_VOICE_DEPS[voice_id])

        out_voices.append(
            {
                "voice_id": voice_id,
                "phase": v.get("calc_phase_final"),
                "phase_proxy": v.get("calc_phase_proxy"),
                "nature": nature,
                "depends_on_voices": voices_dep,
                "depends_on_assumptions": assumps_dep,
                "depends_on_drivers": drivers_dep,
                "formula_rule_id": formula_rule_id,
                "dependency_type": map_dependency_type(nature),
            }
        )

    write_yaml(out_voices)
    report(out_voices, known_voice_ids)


def write_yaml(out_voices: list[dict]) -> None:
    lines = ["voices:\n"]
    for entry in out_voices:
        lines.append(f"- voice_id: {entry['voice_id']}\n")
        lines.append(f"  phase: {fmt(entry['phase'])}\n")
        lines.append(f"  phase_proxy: {fmt(entry['phase_proxy'])}\n")
        lines.append(f"  nature: {entry['nature']}\n")
        lines.extend(_list_block("depends_on_voices", entry["depends_on_voices"]))
        lines.extend(_list_block("depends_on_assumptions", entry["depends_on_assumptions"]))
        lines.extend(_list_block("depends_on_drivers", entry["depends_on_drivers"]))
        lines.append(f"  formula_rule_id: {fmt(entry['formula_rule_id'])}\n")
        lines.append(f"  dependency_type: {entry['dependency_type']}\n")
    OUT_PATH.write_text("".join(lines))


def fmt(val) -> str:
    return "null" if val is None else str(val)


def _list_block(key: str, items: list[str]) -> list[str]:
    if not items:
        return [f"  {key}: []\n"]
    out = [f"  {key}:\n"]
    out.extend(f"  - {x}\n" for x in items)
    return out


def report(out_voices: list[dict], known_voice_ids: set[str]) -> None:
    print(f"Voci processate: {len(out_voices)}")

    overridden = [v for v in out_voices if v["voice_id"] in MANUAL_VOICE_DEPS]
    print(f"Override manuali applicati: {len(overridden)}")

    dangling: list[tuple[str, str]] = []
    for v in out_voices:
        for dep in v["depends_on_voices"]:
            if dep not in known_voice_ids:
                dangling.append((v["voice_id"], dep))
    if dangling:
        print(f"\nDangling refs (non in voice_registry): {len(dangling)}")
        for src, dep in dangling:
            print(f"  {src} -> {dep}")


if __name__ == "__main__":
    main()

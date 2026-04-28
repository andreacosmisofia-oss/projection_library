"""Build sample balance datasets and verify SP balance.

Sign convention:
- P&L: revenues positive, costs negative
- SP: assets positive, liabilities and equity negative
- SP balances when sum(assets) + sum(liabilities) + sum(equity) == 0

Plug policy:
- Any residual SP gap is absorbed into the dataset's cash row.
- The "unbalanced" fixture deliberately deviates from this after plug.
"""
import copy
import sys
from pathlib import Path

from openpyxl import Workbook

OUT_DIR = Path(__file__).resolve().parent.parent / "sample_data"
OUT_DIR.mkdir(parents=True, exist_ok=True)

CASSA_LABEL_TIER = "Cassa e disponibilità"
CASSA_LABEL_GENERIC = "Cassa"

# ---------------------------------------------------------------------------
# Dataset definitions
# ---------------------------------------------------------------------------

TIER1_ROWS = [
    ("Ricavi delle vendite",       "P&L",            2100),
    ("Costo del venduto",          "P&L",           -1100),
    ("Costi del personale",        "P&L",            -420),
    ("Altri costi operativi",      "P&L",            -180),
    ("Ammortamenti",               "P&L",             -90),
    ("Proventi/oneri finanziari",  "P&L",             -45),
    ("Immobilizzazioni nette",     "SP_assets",       920),
    ("Crediti commerciali",        "SP_assets",       380),
    ("Rimanenze",                  "SP_assets",       210),
    ("Altre attività correnti",    "SP_assets",        80),
    (CASSA_LABEL_TIER,             "SP_assets",       180),
    ("Debiti commerciali",         "SP_liabilities", -210),
    ("Debiti finanziari",          "SP_liabilities", -350),
    ("Altre passività correnti",   "SP_liabilities",  -95),
    ("Capitale sociale",           "SP_equity",      -100),
    ("Riserve e utili a nuovo",    "SP_equity",     -1015),
]

# Tier 2: same voices with Y-1 (~10% lower) plus more granular voices.
TIER2_BASE = [(label, section, round(y0 * 0.9), y0) for (label, section, y0) in TIER1_ROWS]

TIER2_EXTRA = [
    ("Ricavi prodotti",                "P&L",            1720,  1900),
    ("Ricavi servizi",                 "P&L",             160,   200),
    ("Materie prime",                  "P&L",            -610,  -680),
    ("Manodopera diretta",             "P&L",            -280,  -310),
    ("Costi commerciali",              "P&L",             -95,  -105),
    ("Costi generali e amministrativi","P&L",             -72,   -75),
    ("Fondi rischi",                   "SP_liabilities",  -45,   -52),
    ("Crediti per imposte anticipate", "SP_assets",        11,    15),
]

TIER2_ROWS = TIER2_BASE + TIER2_EXTRA

SAAS_ROWS = [
    ("Subscription revenue",          "P&L",            1200,  1500),
    ("Professional services",         "P&L",             180,   200),
    ("Costo del personale tecnico",   "P&L",            -480,  -560),
    ("Costi commerciali e marketing", "P&L",            -320,  -380),
    ("G&A",                           "P&L",            -140,  -160),
    ("Ammortamenti",                  "P&L",             -85,   -95),
    ("Oneri finanziari",              "P&L",             -22,   -18),
    ("Immobilizzazioni nette",        "SP_assets",       280,   310),
    ("Crediti commerciali",           "SP_assets",        95,   115),
    (CASSA_LABEL_GENERIC,             "SP_assets",       420,   485),
    ("Altre attività",                "SP_assets",        45,    52),
    ("Debiti commerciali",            "SP_liabilities",  -65,   -78),
    ("Deferred revenue",              "SP_liabilities", -180,  -220),
    ("Debiti finanziari",             "SP_liabilities", -120,  -100),
    ("Capitale sociale",              "SP_equity",       -50,   -50),
    ("Riserve e perdite accumulate",  "SP_equity",      -135,  -341),
]

SAAS_DRIVERS = [
    ("driver.saas.arr_opening",      1100, 1380),
    ("driver.saas.new_arr",           420,  480),
    ("driver.saas.expansion_arr",     120,  150),
    ("driver.saas.churn_arr",        -180, -210),
    ("driver.saas.contraction_arr",   -80,  -90),
    ("driver.saas.arr_closing",      1380, 1710),
]

RETAIL_ROWS = [
    ("Ricavi negozi",                "P&L",            3200,  3500),
    ("Costo del venduto",            "P&L",           -1920, -2100),
    ("Costi personale",              "P&L",            -640,  -700),
    ("Costi marketing",              "P&L",            -160,  -175),
    ("Ammortamenti PPE",             "P&L",             -85,   -90),
    ("Ammortamenti ROU",             "P&L",            -280,  -295),
    ("Oneri finanziari",             "P&L",             -45,   -42),
    ("Lease interest (IFRS16)",      "P&L",             -95,   -88),
    ("Immobilizzazioni nette",       "SP_assets",       620,   650),
    ("ROU assets netti",             "SP_assets",      1120,   980),
    ("Crediti commerciali",          "SP_assets",       180,   195),
    ("Rimanenze",                    "SP_assets",       420,   445),
    (CASSA_LABEL_GENERIC,            "SP_assets",       310,   350),
    ("Debiti commerciali",           "SP_liabilities", -380,  -415),
    ("Lease liability corrente",     "SP_liabilities", -280,  -295),
    ("Lease liability non corrente", "SP_liabilities", -840,  -685),
    ("Debiti finanziari",            "SP_liabilities", -200,  -180),
    ("Capitale sociale",             "SP_equity",      -100,  -100),
    ("Riserve e utili",              "SP_equity",      -470,  -610),
]

REAL_ESTATE_ROWS = [
    ("Ricavi locazioni",                       "P&L",             850,   920),
    ("Costi gestione immobili",                "P&L",            -180,  -195),
    ("Costi personale",                        "P&L",             -95,  -102),
    ("Ammortamenti (immobili uso proprio)",    "P&L",             -45,   -48),
    ("Fair value gain investment property",    "P&L",             120,    95),
    ("Oneri finanziari",                       "P&L",            -180,  -172),
    ("Immobili uso proprio netti",             "SP_assets",       980,   950),
    ("Investment property (fair value)",       "SP_assets",      4200,  4350),
    ("Crediti per canoni",                     "SP_assets",        95,   102),
    (CASSA_LABEL_GENERIC,                      "SP_assets",       280,   310),
    ("Debiti commerciali",                     "SP_liabilities",  -85,   -92),
    ("Mutui ipotecari",                        "SP_liabilities",-2800, -2650),
    ("Altre passività",                        "SP_liabilities", -120,  -128),
    ("Capitale sociale",                       "SP_equity",      -500,  -500),
    ("Riserve e rivalutazioni",                "SP_equity",     -2025, -2025),
    ("Utili reinvestiti",                      "SP_equity",      -300,  -470),
]

# ---------------------------------------------------------------------------
# IO helpers
# ---------------------------------------------------------------------------

def write_balance_sheet(path: Path, header: list, rows: list,
                        extra_sheets: list[tuple[str, list, list]] | None = None) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Balance"
    ws.append(header)
    for row in rows:
        ws.append(list(row))
    for sheet_name, sheet_header, sheet_rows in (extra_sheets or []):
        ws2 = wb.create_sheet(sheet_name)
        ws2.append(sheet_header)
        for row in sheet_rows:
            ws2.append(list(row))
    wb.save(path)


# ---------------------------------------------------------------------------
# Balance helpers
# ---------------------------------------------------------------------------

def sp_balance(rows, year_idx: int) -> dict:
    assets = sum(r[year_idx] for r in rows if r[1] == "SP_assets")
    liab = sum(r[year_idx] for r in rows if r[1] == "SP_liabilities")
    eq = sum(r[year_idx] for r in rows if r[1] == "SP_equity")
    return {"assets": assets, "liabilities": liab, "equity": eq,
            "sum": assets + liab + eq}


def pl_net(rows, year_idx: int) -> int:
    return sum(r[year_idx] for r in rows if r[1] == "P&L")


def plug_cassa(rows: list, year_idx: int, year_name: str, cassa_label: str) -> int:
    bal = sp_balance(rows, year_idx)
    gap = bal["sum"]
    if gap == 0:
        print(f"  [{year_name}] no plug needed (gap = 0)")
        return 0
    for i, r in enumerate(rows):
        if r[0] == cassa_label:
            lst = list(r)
            lst[year_idx] -= gap
            rows[i] = tuple(lst)
            print(f"  [{year_name}] plug {cassa_label}: {-gap:+d} (gap absorbed: {gap:+d})")
            return gap
    raise RuntimeError(f"Cash row '{cassa_label}' not found ({year_name})")


def adjust_row(rows: list, label: str, year_idx: int, delta: int) -> None:
    for i, r in enumerate(rows):
        if r[0] == label:
            lst = list(r)
            lst[year_idx] += delta
            rows[i] = tuple(lst)
            return
    raise RuntimeError(f"Row '{label}' not found for adjustment")


def report(rows, year_idx: int, year_name: str) -> dict:
    bal = sp_balance(rows, year_idx)
    print(f"\n[{year_name}] SP check:")
    print(f"  assets      = {bal['assets']}")
    print(f"  liabilities = {bal['liabilities']}")
    print(f"  equity      = {bal['equity']}")
    print(f"  sum (must=0) = {bal['sum']}")
    print(f"  P&L net      = {pl_net(rows, year_idx)}")
    return bal


# ---------------------------------------------------------------------------
# Build pipeline
# ---------------------------------------------------------------------------

def build_dataset(name: str, rows: list, year_cols: list[tuple[int, str]],
                  cassa_label: str) -> list:
    """Plug each year independently into the cash row. Returns the mutated rows."""
    print(f"\n--- {name} (pre-plug) ---")
    for idx, year_name in year_cols:
        report(rows, idx, f"{name} / {year_name}")
    print(f"\n--- {name} (plug) ---")
    for idx, year_name in year_cols:
        plug_cassa(rows, idx, f"{name} / {year_name}", cassa_label)
    print(f"\n--- {name} (post-plug) ---")
    finals = []
    for idx, year_name in year_cols:
        finals.append((year_name, report(rows, idx, f"{name} / {year_name}")))
    return finals


def main() -> int:
    summary: list[tuple[str, str, int]] = []  # (file, year, sp_sum)

    # 1. Tier 1
    finals = build_dataset("Tier 1", TIER1_ROWS, [(2, "Y0")], CASSA_LABEL_TIER)
    write_balance_sheet(
        OUT_DIR / "tier1_minimal_balance.xlsx",
        ["voice_label", "voice_section", "Y0"], TIER1_ROWS,
    )
    for yr, bal in finals:
        summary.append(("tier1_minimal_balance.xlsx", yr, bal["sum"]))

    # 2. Tier 2 clean
    finals = build_dataset(
        "Tier 2", TIER2_ROWS, [(2, "Y-1"), (3, "Y0")], CASSA_LABEL_TIER,
    )
    write_balance_sheet(
        OUT_DIR / "tier2_industrial_clean.xlsx",
        ["voice_label", "voice_section", "Y-1", "Y0"], TIER2_ROWS,
    )
    for yr, bal in finals:
        summary.append(("tier2_industrial_clean.xlsx", yr, bal["sum"]))

    # 3. Tier 2 unbalanced — copy of clean, then -500 on Cassa Y0 (DI_013 fixture)
    tier2_unbalanced = copy.deepcopy(TIER2_ROWS)
    adjust_row(tier2_unbalanced, CASSA_LABEL_TIER, 3, -500)
    print("\n--- Tier 2 unbalanced (post-tamper) ---")
    bal_ym1 = report(tier2_unbalanced, 2, "Tier 2 unbalanced / Y-1")
    bal_y0 = report(tier2_unbalanced, 3, "Tier 2 unbalanced / Y0")
    write_balance_sheet(
        OUT_DIR / "tier2_industrial_unbalanced.xlsx",
        ["voice_label", "voice_section", "Y-1", "Y0"], tier2_unbalanced,
    )
    summary.append(("tier2_industrial_unbalanced.xlsx", "Y-1", bal_ym1["sum"]))
    summary.append(("tier2_industrial_unbalanced.xlsx", "Y0", bal_y0["sum"]))

    # 4. SaaS ARR bridge
    finals = build_dataset(
        "SaaS", SAAS_ROWS, [(2, "Y-1"), (3, "Y0")], CASSA_LABEL_GENERIC,
    )
    write_balance_sheet(
        OUT_DIR / "saas_arr_bridge.xlsx",
        ["voice_label", "voice_section", "Y-1", "Y0"], SAAS_ROWS,
        extra_sheets=[("SaaS Drivers", ["driver_id", "Y-1", "Y0"], SAAS_DRIVERS)],
    )
    for yr, bal in finals:
        summary.append(("saas_arr_bridge.xlsx", yr, bal["sum"]))

    # 5. Retail IFRS 16
    finals = build_dataset(
        "Retail IFRS16", RETAIL_ROWS, [(2, "Y-1"), (3, "Y0")], CASSA_LABEL_GENERIC,
    )
    write_balance_sheet(
        OUT_DIR / "retail_lease_ifrs16.xlsx",
        ["voice_label", "voice_section", "Y-1", "Y0"], RETAIL_ROWS,
    )
    for yr, bal in finals:
        summary.append(("retail_lease_ifrs16.xlsx", yr, bal["sum"]))

    # 6. Real estate IAS 40
    finals = build_dataset(
        "Real Estate IAS40", REAL_ESTATE_ROWS, [(2, "Y-1"), (3, "Y0")], CASSA_LABEL_GENERIC,
    )
    write_balance_sheet(
        OUT_DIR / "real_estate_ias40.xlsx",
        ["voice_label", "voice_section", "Y-1", "Y0"], REAL_ESTATE_ROWS,
    )
    for yr, bal in finals:
        summary.append(("real_estate_ias40.xlsx", yr, bal["sum"]))

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("SAMPLE DATASET BALANCE SUMMARY")
    print("=" * 60)
    print(f"{'file':<40} {'year':<6} {'sp_sum':>8}")
    print("-" * 60)
    for fname, yr, val in summary:
        marker = "OK" if val == 0 else f"FAIL ({val:+d})"
        print(f"{fname:<40} {yr:<6} {val:>8}  {marker}")

    # Expected: tier2_industrial_unbalanced.xlsx Y0 must be != 0; everything else == 0.
    expected_unbalanced = {("tier2_industrial_unbalanced.xlsx", "Y0")}
    failures = []
    for fname, yr, val in summary:
        key = (fname, yr)
        if key in expected_unbalanced:
            if val == 0:
                failures.append(f"{fname} {yr}: expected != 0, got 0")
        else:
            if val != 0:
                failures.append(f"{fname} {yr}: expected 0, got {val}")
    if failures:
        print("\nSTATUS: unexpected balance results:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nSTATUS: all balanced datasets verified; unbalanced fixture deviates as expected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

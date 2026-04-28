"""Build tier1 and tier2 sample balance datasets and verify SP balance.

Sign convention:
- P&L: revenues positive, costs negative
- SP: assets positive, liabilities and equity negative
- SP balances when sum(assets) + sum(liabilities) + sum(equity) == 0
"""
from pathlib import Path

from openpyxl import Workbook

OUT_DIR = Path(__file__).resolve().parent.parent / "sample_data"
OUT_DIR.mkdir(parents=True, exist_ok=True)

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
    ("Cassa e disponibilità",      "SP_assets",       180),
    ("Debiti commerciali",         "SP_liabilities", -210),
    ("Debiti finanziari",          "SP_liabilities", -350),
    ("Altre passività correnti",   "SP_liabilities",  -95),
    ("Capitale sociale",           "SP_equity",      -100),
    ("Riserve e utili a nuovo",    "SP_equity",     -1015),
    ("Utile di esercizio",         "SP_equity",      -265),
]

# Tier 2: same voices with Y-1 (~10% lower) plus more granular voices.
# Y-1 = round(Y0 * 0.9) for the inherited rows.
TIER2_BASE = [(label, section, round(y0 * 0.9), y0) for (label, section, y0) in TIER1_ROWS]

TIER2_EXTRA = [
    ("Ricavi prodotti",                "P&L",            1720,  1900),
    ("Ricavi servizi",                 "P&L",             160,   200),
    ("Materie prime",                  "P&L",            -610,  -680),
    ("Manodopera diretta",             "P&L",            -280,  -310),
    ("Costi commerciali",              "P&L",             -95,  -105),
    ("Costi generali e amministrativi","P&L",             -72,   -75),
    ("Fondi rischi",                   "SP_liabilities",  -45,   -52),
]

TIER2_ROWS = TIER2_BASE + TIER2_EXTRA


def write_tier1(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Balance"
    ws.append(["voice_label", "voice_section", "Y0"])
    for row in TIER1_ROWS:
        ws.append(list(row))
    wb.save(path)


def write_tier2(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Balance"
    ws.append(["voice_label", "voice_section", "Y-1", "Y0"])
    for row in TIER2_ROWS:
        ws.append(list(row))
    wb.save(path)


def sp_balance(rows, year_idx: int) -> dict:
    assets = sum(r[year_idx] for r in rows if r[1] == "SP_assets")
    liab = sum(r[year_idx] for r in rows if r[1] == "SP_liabilities")
    eq = sum(r[year_idx] for r in rows if r[1] == "SP_equity")
    return {
        "assets": assets,
        "liabilities": liab,
        "equity": eq,
        "sum": assets + liab + eq,
        "abs_check_assets_eq_liab_plus_eq": assets + liab + eq,
    }


def pl_net(rows, year_idx: int) -> int:
    return sum(r[year_idx] for r in rows if r[1] == "P&L")


def main() -> None:
    tier1_path = OUT_DIR / "tier1_minimal_balance.xlsx"
    tier2_path = OUT_DIR / "tier2_industrial_clean.xlsx"
    write_tier1(tier1_path)
    write_tier2(tier2_path)
    print(f"Wrote {tier1_path}")
    print(f"Wrote {tier2_path}")

    # Tier1 rows have shape (label, section, Y0): year_idx = 2
    t1 = sp_balance(TIER1_ROWS, 2)
    print("\n[Tier 1] Y0 SP check:")
    print(f"  assets      = {t1['assets']}")
    print(f"  liabilities = {t1['liabilities']}")
    print(f"  equity      = {t1['equity']}")
    print(f"  sum (must=0) = {t1['sum']}")
    print(f"  P&L net      = {pl_net(TIER1_ROWS, 2)}")

    # Tier2 rows have shape (label, section, Y-1, Y0): year_idx = 2 (Y-1) or 3 (Y0)
    t2_ym1 = sp_balance(TIER2_ROWS, 2)
    t2_y0 = sp_balance(TIER2_ROWS, 3)
    print("\n[Tier 2] Y-1 SP check:")
    print(f"  assets      = {t2_ym1['assets']}")
    print(f"  liabilities = {t2_ym1['liabilities']}")
    print(f"  equity      = {t2_ym1['equity']}")
    print(f"  sum (must=0) = {t2_ym1['sum']}")
    print(f"  P&L net      = {pl_net(TIER2_ROWS, 2)}")
    print("\n[Tier 2] Y0 SP check:")
    print(f"  assets      = {t2_y0['assets']}")
    print(f"  liabilities = {t2_y0['liabilities']}")
    print(f"  equity      = {t2_y0['equity']}")
    print(f"  sum (must=0) = {t2_y0['sum']}")
    print(f"  P&L net      = {pl_net(TIER2_ROWS, 3)}")


if __name__ == "__main__":
    main()

"""Build tier1 and tier2 sample balance datasets and verify SP balance.

Sign convention:
- P&L: revenues positive, costs negative
- SP: assets positive, liabilities and equity negative
- SP balances when sum(assets) + sum(liabilities) + sum(equity) == 0

Auto-plug policy:
- After applying user corrections, residual SP gaps with |gap| < PLUG_THRESHOLD
  are absorbed into "Cassa e disponibilità".
- Larger gaps are reported and require explicit user instructions.
"""
import sys
from pathlib import Path

from openpyxl import Workbook

OUT_DIR = Path(__file__).resolve().parent.parent / "sample_data"
OUT_DIR.mkdir(parents=True, exist_ok=True)

PLUG_THRESHOLD = 5
CASSA_LABEL = "Cassa e disponibilità"

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
    (CASSA_LABEL,                  "SP_assets",       180),
    ("Debiti commerciali",         "SP_liabilities", -210),
    ("Debiti finanziari",          "SP_liabilities", -350),
    ("Altre passività correnti",   "SP_liabilities",  -95),
    ("Capitale sociale",           "SP_equity",      -100),
    ("Riserve e utili a nuovo",    "SP_equity",     -1015),
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
    ("Crediti per imposte anticipate", "SP_assets",        11,    15),
]

TIER2_ROWS = TIER2_BASE + TIER2_EXTRA


def write_excel(path: Path, header: list, rows: list) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Balance"
    ws.append(header)
    for row in rows:
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
    }


def pl_net(rows, year_idx: int) -> int:
    return sum(r[year_idx] for r in rows if r[1] == "P&L")


def auto_plug_cassa(rows: list, year_idx: int, year_name: str) -> tuple[int, bool]:
    """Plug Cassa for the given year if |gap| < PLUG_THRESHOLD.

    Returns (gap_before_plug, plugged).
    """
    bal = sp_balance(rows, year_idx)
    gap = bal["sum"]  # need to add (-gap) to assets to balance
    if gap == 0:
        return 0, False
    if abs(gap) < PLUG_THRESHOLD:
        for i, r in enumerate(rows):
            if r[0] == CASSA_LABEL:
                lst = list(r)
                lst[year_idx] -= gap
                rows[i] = tuple(lst)
                print(f"  [{year_name}] auto-plug Cassa: {gap:+d} (|gap| < {PLUG_THRESHOLD})")
                return gap, True
        raise RuntimeError(f"Cassa row not found in rows for plug ({year_name})")
    print(
        f"  [{year_name}] GAP RESIDUO {gap:+d} >= {PLUG_THRESHOLD} — "
        f"plug NON applicato, attendo istruzioni"
    )
    return gap, False


def report(rows, year_idx: int, year_name: str) -> dict:
    bal = sp_balance(rows, year_idx)
    print(f"\n[{year_name}] SP check:")
    print(f"  assets      = {bal['assets']}")
    print(f"  liabilities = {bal['liabilities']}")
    print(f"  equity      = {bal['equity']}")
    print(f"  sum (must=0) = {bal['sum']}")
    print(f"  P&L net      = {pl_net(rows, year_idx)}")
    return bal


def main() -> int:
    tier1_path = OUT_DIR / "tier1_minimal_balance.xlsx"
    tier2_path = OUT_DIR / "tier2_industrial_clean.xlsx"

    print("=== Pre-plug balance ===")
    report(TIER1_ROWS, 2, "Tier 1 / Y0")
    report(TIER2_ROWS, 2, "Tier 2 / Y-1")
    report(TIER2_ROWS, 3, "Tier 2 / Y0")

    print("\n=== Auto-plug pass ===")
    _, p_t1 = auto_plug_cassa(TIER1_ROWS, 2, "Tier 1 / Y0")
    _, p_t2_ym1 = auto_plug_cassa(TIER2_ROWS, 2, "Tier 2 / Y-1")
    _, p_t2_y0 = auto_plug_cassa(TIER2_ROWS, 3, "Tier 2 / Y0")

    print("\n=== Post-plug balance ===")
    final_t1 = report(TIER1_ROWS, 2, "Tier 1 / Y0")
    final_t2_ym1 = report(TIER2_ROWS, 2, "Tier 2 / Y-1")
    final_t2_y0 = report(TIER2_ROWS, 3, "Tier 2 / Y0")

    write_excel(tier1_path, ["voice_label", "voice_section", "Y0"], TIER1_ROWS)
    write_excel(tier2_path, ["voice_label", "voice_section", "Y-1", "Y0"], TIER2_ROWS)
    print(f"\nWrote {tier1_path}")
    print(f"Wrote {tier2_path}")

    all_balanced = (
        final_t1["sum"] == 0
        and final_t2_ym1["sum"] == 0
        and final_t2_y0["sum"] == 0
    )
    if not all_balanced:
        print("\nSTATUS: SP NOT balanced for at least one year — awaiting instructions.")
        return 1
    print("\nSTATUS: SP balanced for all years.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

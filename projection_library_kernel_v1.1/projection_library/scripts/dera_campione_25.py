"""Pipeline DERA → campione stratificato 25 aziende → Excel.

Esecuzione:
    python dera_campione_25.py
    python dera_campione_25.py --folder "C:/Users/andre/OneDrive/Desktop/2026q1"
    python dera_campione_25.py --folder "C:/Users/andre/OneDrive/Desktop/2026q1" --seed 42

Step implementati (corrispondono al documento Power Query allegato):
  0  Lettura sub.txt
  1  Forza tipi testo su colonne critiche
  2  Filtro form = 10-K
  3  Colonna sic2 (prime 2 cifre, int)
  4  Esclusione settori (utilities, finanza, mining, costruzioni)
  5  Deduplica per CIK (tieni il filing più recente)
  6  Separazione aziende nominate (garantite nel campione)
  7  Campione casuale sul pool residuo → totale 25
  8  Colonne finali: adsh, cik, name, sic, sic2, afs, form, period, fy, filed
  9  Lettura num.txt sugli adsh selezionati (filtro coreg + dimh vuoti)
 10  Lettura pre.txt sugli adsh selezionati (filtro stmt ∈ {BS, IS, CF})
 11  Join num ⋈ pre su (adsh, tag, version) + applicazione negating
 12  Output Excel: un workbook per azienda + consolidato

Output (nella stessa cartella dello script oppure --out):
  campione_25/
    00_campione_sub.xlsx          — le 25 aziende con metadati sub.txt
    {TICKER_o_CIK}_financials.xlsx — dati contabili per azienda (IS/BS/CF)
    ALL_25_financials.xlsx         — pivot consolidato
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Aziende garantite (dalla lista nel documento)
# FCX (Freeport-McMoRan) esclusa: SIC 1040 = metal mining, filtrato allo Step 4
# ---------------------------------------------------------------------------

NAMED_SUBSTRINGS: list[str] = [
    "CATERPILLAR",
    "PROCTER",
    "GENERAL MOTORS",
    "PFIZER",
    "ORACLE",
    "AT&T",
    "FEDEX",
    "NIKE",
    "BOEING",
]

# SIC a 2 cifre da escludere
SIC2_EXCLUDE_EXACT   = {49}                   # utilities regolate
SIC2_EXCLUDE_RANGES  = [(60, 67), (10, 14), (15, 17)]   # finanza, mining, costruzioni

TARGET_TOTAL = 25


# ---------------------------------------------------------------------------
# Lettura robusta file DERA (tab-delimited, encoding misto)
# ---------------------------------------------------------------------------

def read_dera_txt(path: Path, usecols: list[str] | None = None,
                  dtype: dict | None = None, chunksize: int | None = None):
    """Legge un file DERA txt (tab-sep).  Ritorna DataFrame o iterator."""
    kwargs: dict = {
        "sep": "\t",
        "encoding": "latin-1",        # DERA usa latin-1, non utf-8
        "low_memory": False,
        "on_bad_lines": "warn",
    }
    if usecols:
        kwargs["usecols"] = usecols
    if dtype:
        kwargs["dtype"] = dtype
    if chunksize:
        kwargs["chunksize"] = chunksize
    return pd.read_csv(path, **kwargs)


# ---------------------------------------------------------------------------
# Step 0-8: selezione del campione da sub.txt
# ---------------------------------------------------------------------------

def build_sample(folder: Path, seed: int | None) -> pd.DataFrame:
    sub_path = folder / "sub.txt"
    if not sub_path.exists():
        sys.exit(f"ERROR: sub.txt non trovato in {folder}")

    print(f"[0] Lettura sub.txt da {sub_path} …", flush=True)
    # Step 1: forza tipi testo sulle colonne critiche
    str_cols = {"adsh": str, "cik": str, "sic": str, "afs": str, "form": str,
                "name": str, "period": str, "fy": str, "filed": str}
    sub = read_dera_txt(sub_path, dtype=str_cols)
    print(f"    {len(sub):,} righe totali")

    # Step 2: filtro form = 10-K
    sub = sub[sub["form"].str.strip() == "10-K"].copy()
    print(f"[2] Dopo filtro 10-K: {len(sub):,} righe")

    # Step 3: sic2
    sub["sic2"] = pd.to_numeric(sub["sic"].str[:2], errors="coerce").astype("Int64")

    # Step 4: esclusione settori
    mask_ok = sub["sic2"].notna()
    mask_ok &= ~sub["sic2"].isin(SIC2_EXCLUDE_EXACT)
    for lo, hi in SIC2_EXCLUDE_RANGES:
        mask_ok &= ~((sub["sic2"] >= lo) & (sub["sic2"] <= hi))
    sub = sub[mask_ok].copy()
    print(f"[4] Dopo esclusione settori: {len(sub):,} righe")

    # Step 5: deduplica per CIK (tieni il filing più recente)
    sub["filed"] = sub["filed"].str.strip()
    sub = (
        sub.sort_values("filed", ascending=False)
           .drop_duplicates(subset="cik", keep="first")
           .reset_index(drop=True)
    )
    print(f"[5] Dopo deduplica CIK: {len(sub):,} aziende")

    # Step 6/7bis: estrai aziende nominate
    name_upper = sub["name"].str.upper().fillna("")
    mask_named = pd.Series(False, index=sub.index)
    for substr in NAMED_SUBSTRINGS:
        mask_named |= name_upper.str.contains(substr, regex=False)

    named_df  = sub[mask_named].copy()
    residuo   = sub[~mask_named].copy()

    print(f"[6] Aziende nominate trovate: {len(named_df)}")
    for _, row in named_df.iterrows():
        print(f"      {row['name'][:50]:<50}  CIK={row['cik']}  SIC={row['sic']}")

    # Step 6: campione casuale dal pool residuo
    n_random = max(0, TARGET_TOTAL - len(named_df))
    if n_random > len(residuo):
        print(f"WARNING: pool residuo ({len(residuo)}) < richiesto ({n_random}). "
              "Usa tutto il pool.")
        n_random = len(residuo)

    rng = random.Random(seed)
    residuo_shuffled = residuo.sample(frac=1, random_state=rng.randint(0, 2**31),
                                      ).reset_index(drop=True)
    random_df = residuo_shuffled.head(n_random).copy()

    # Combina e dedup finale
    sample = pd.concat([named_df, random_df], ignore_index=True).drop_duplicates(
        subset="cik", keep="first"
    )

    # Step 8: colonne finali
    keep_cols = [c for c in
                 ["adsh", "cik", "name", "sic", "sic2", "afs", "form", "period", "fy", "filed"]
                 if c in sample.columns]
    sample = sample[keep_cols].reset_index(drop=True)

    print(f"\n[8] Campione finale: {len(sample)} aziende")
    print(sample[["name", "cik", "sic", "filed"]].to_string(index=False))
    return sample


# ---------------------------------------------------------------------------
# Step 9-11: lettura num.txt + pre.txt e join
# ---------------------------------------------------------------------------

def load_financials(folder: Path, adsh_list: list[str]) -> pd.DataFrame:
    num_path = folder / "num.txt"
    pre_path = folder / "pre.txt"

    adsh_set = set(adsh_list)

    # --- num.txt ---
    print("\n[9] Lettura num.txt (filtraggio in chunk) …", flush=True)
    num_cols = ["adsh", "tag", "version", "coreg", "ddate", "qtrs", "uom",
                "dimh", "iprx", "value"]
    chunks_num = []
    chunk_iter = read_dera_txt(
        num_path,
        usecols=[c for c in num_cols if True],
        dtype={"adsh": str, "tag": str, "version": str,
               "coreg": str, "dimh": str, "uom": str},
        chunksize=500_000,
    )
    for chunk in chunk_iter:
        # Filtra adsh del campione
        chunk = chunk[chunk["adsh"].isin(adsh_set)]
        if chunk.empty:
            continue
        # coreg vuoto (entità consolidata, non co-registrant)
        chunk = chunk[chunk["coreg"].fillna("").str.strip() == ""]
        # dimh vuoto = nessuna dimensione (niente segmenti, niente member)
        chunk = chunk[chunk["dimh"].fillna("").str.strip().isin(["", "0"])]
        chunks_num.append(chunk)

    if not chunks_num:
        print("    WARNING: nessun dato num.txt trovato per gli adsh selezionati.")
        return pd.DataFrame()

    num = pd.concat(chunks_num, ignore_index=True)
    num["value"] = pd.to_numeric(num["value"], errors="coerce")
    print(f"    {len(num):,} righe num dopo filtri")

    # --- pre.txt ---
    print("[10] Lettura pre.txt …", flush=True)
    pre_cols = ["adsh", "report", "line", "stmt", "tag", "version", "plabel", "negating"]
    pre = read_dera_txt(
        pre_path,
        usecols=pre_cols,
        dtype={"adsh": str, "tag": str, "version": str, "stmt": str,
               "plabel": str, "negating": str},
    )
    pre = pre[pre["adsh"].isin(adsh_set)]
    # Tieni solo rendiconti principali
    pre = pre[pre["stmt"].isin(["BS", "IS", "CF"])].copy()
    print(f"    {len(pre):,} righe pre dopo filtri (BS/IS/CF)")

    # --- Join num ⋈ pre su (adsh, tag, version) ---
    print("[11] Join num ⋈ pre …", flush=True)
    merged = num.merge(pre, on=["adsh", "tag", "version"], how="inner")

    # Applica negating: se negating == "1" il valore viene invertito di segno
    neg_mask = merged["negating"].fillna("0").str.strip() == "1"
    merged.loc[neg_mask, "value"] = -merged.loc[neg_mask, "value"]

    print(f"    {len(merged):,} righe dopo join")
    return merged


# ---------------------------------------------------------------------------
# Step 12: Output Excel
# ---------------------------------------------------------------------------

def export_excel(sample: pd.DataFrame, financials: pd.DataFrame,
                 out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    # --- 00_campione_sub.xlsx ---
    sub_path = out_dir / "00_campione_sub.xlsx"
    with pd.ExcelWriter(sub_path, engine="openpyxl") as w:
        sample.to_excel(w, sheet_name="Campione 25", index=False)
        _autofit(w.sheets["Campione 25"])
    print(f"\n[12] {sub_path.name}")

    if financials.empty:
        print("    Nessun dato finanziario da esportare.")
        return

    # Pivot base: una riga per (name, stmt, tag/plabel, ddate)
    fin = financials.copy()
    # Aggiungi nome azienda
    cik_to_name = dict(zip(sample["cik"].astype(str), sample["name"]))
    adsh_to_cik = dict(zip(sample["adsh"].astype(str), sample["cik"].astype(str)))
    fin["cik"]  = fin["adsh"].map(adsh_to_cik)
    fin["name"] = fin["cik"].map(cik_to_name)

    # Colonne utili per l'output
    fin_out = fin[["name", "cik", "adsh", "stmt", "tag", "plabel",
                   "ddate", "qtrs", "uom", "value"]].copy()
    fin_out["ddate"] = fin_out["ddate"].astype(str)

    # --- File per azienda ---
    for (cik, adsh, name), grp in fin_out.groupby(["cik", "adsh", "name"]):
        safe_name = "".join(c if c.isalnum() or c in " _-" else "_" for c in str(name))[:40]
        fname = out_dir / f"{safe_name}_financials.xlsx"
        with pd.ExcelWriter(fname, engine="openpyxl") as w:
            for stmt, stmt_grp in grp.groupby("stmt"):
                sheet = stmt_grp.drop(columns=["cik", "adsh", "name", "stmt"]) \
                                .sort_values(["ddate", "tag"])
                sheet.to_excel(w, sheet_name=str(stmt), index=False)
                _autofit(w.sheets[str(stmt)])
        print(f"    {fname.name}")

    # --- ALL_25_financials.xlsx: pivot annuale per tag ---
    print("\n    Costruzione consolidato …")
    # Filtro: qtrs=4 (annuale) o qtrs=0 (istantaneo BS) per ridurre il rumore
    ann = fin_out[fin_out["qtrs"].isin([0, 4])].copy()
    ann["year"] = ann["ddate"].str[:4]

    pivot = ann.pivot_table(
        index=["name", "stmt", "tag", "plabel"],
        columns="year",
        values="value",
        aggfunc="first",
    ).reset_index()

    all_path = out_dir / "ALL_25_financials.xlsx"
    with pd.ExcelWriter(all_path, engine="openpyxl") as w:
        for stmt in ["IS", "BS", "CF"]:
            sub_piv = pivot[pivot["stmt"] == stmt].drop(columns=["stmt"])
            if sub_piv.empty:
                continue
            sub_piv.to_excel(w, sheet_name=stmt, index=False)
            _autofit(w.sheets[stmt])
    print(f"    {all_path.name}  [consolidato]")


def _autofit(ws) -> None:
    """Adatta larghezza colonne in modo approssimativo."""
    from openpyxl.utils import get_column_letter
    for col_cells in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col_cells[0].column)
        for cell in col_cells:
            try:
                max_len = max(max_len, len(str(cell.value or "")))
            except Exception:
                pass
        ws.column_dimensions[col_letter].width = min(max_len + 2, 60)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Pipeline DERA → campione 25 aziende → Excel")
    p.add_argument(
        "--folder", "-f",
        default=r"C:\Users\andre\OneDrive\Desktop\2026q1",
        help="Cartella contenente sub.txt, num.txt, pre.txt (default: %(default)s)",
    )
    p.add_argument(
        "--out", "-o",
        default=None,
        help="Cartella output (default: <folder>/campione_25)",
    )
    p.add_argument(
        "--seed", "-s",
        type=int,
        default=None,
        help="Seed random per riproducibilità (default: None = nuovo campione ogni run)",
    )
    p.add_argument(
        "--no-financials",
        action="store_true",
        help="Salta la lettura di num.txt/pre.txt (solo sub.txt → campione)",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    folder  = Path(args.folder)
    out_dir = Path(args.out) if args.out else folder / "campione_25"

    if not folder.exists():
        sys.exit(f"ERROR: cartella non trovata: {folder}\n"
                 f"Usa --folder per specificare il percorso corretto.")

    print("=" * 65)
    print("DERA 10-K — Campione 25 aziende (settori finanza/regolati esclusi)")
    print(f"Cartella DERA : {folder}")
    print(f"Output        : {out_dir}")
    print(f"Seed random   : {args.seed}")
    print("=" * 65 + "\n")

    # Steps 0-8
    sample = build_sample(folder, seed=args.seed)

    # Steps 9-11 (opzionale)
    financials = pd.DataFrame()
    if not args.no_financials:
        num_path = folder / "num.txt"
        pre_path = folder / "pre.txt"
        if num_path.exists() and pre_path.exists():
            adsh_list = sample["adsh"].dropna().tolist()
            financials = load_financials(folder, adsh_list)
        else:
            missing = [f for f in [num_path, pre_path] if not f.exists()]
            print(f"\nWARNING: file mancanti {[str(m) for m in missing]}")
            print("  Usa --no-financials per saltare o verifica il percorso.")

    # Step 12
    export_excel(sample, financials, out_dir)

    print("\nFatto.")


if __name__ == "__main__":
    main()

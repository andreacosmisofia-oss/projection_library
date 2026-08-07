"""
Download Italian ESEF (inline XBRL) annual report packages from filings.xbrl.org.

Run this script from a machine with unrestricted internet access.
All downloads are public filings under EU Regulation 2019/815.

Usage:
    python download_esef.py [--out-dir ./esef_downloads]
"""

import argparse
import sys
import time
import urllib.request
from pathlib import Path

COMPANIES = [
    {
        "name": "Brembo SpA",
        "lei": "549300BLWVJN2BAT0A44",
        "isin": "IT0003796171",
        "country": "IT",
        "year": "2023-12-31",
        "url": "https://filings.xbrl.org/549300BLWVJN2BAT0A44/2023-12-31/ESEF/IT/0/549300BLWVJN2BAT0A44-2023-12-31-it.zip",
        "filename": "brembo-2023-esef.zip",
    },
    {
        "name": "Recordati SpA (EN)",
        "lei": "815600FBF92FD3531704",
        "isin": "IT0003828271",
        "country": "IT",
        "year": "2023-12-31",
        "url": "https://filings.xbrl.org/815600FBF92FD3531704/2023-12-31/ESEF/IT/0/815600FBF92FD3531704-2023-12-31-en.zip",
        "filename": "recordati-2023-esef-en.zip",
    },
    {
        "name": "Recordati SpA (IT)",
        "lei": "815600FBF92FD3531704",
        "isin": "IT0003828271",
        "country": "IT",
        "year": "2023-12-31",
        "url": "https://filings.xbrl.org/815600FBF92FD3531704/2023-12-31/ESEF/IT/1/815600FBF92FD3531704-2023-12-31-it.zip",
        "filename": "recordati-2023-esef-it.zip",
    },
    {
        "name": "Reply SpA",
        "lei": "815600DAEFB0388F3521",
        "isin": "IT0005282865",
        "country": "IT",
        "year": "2023-12-31",
        "url": "https://filings.xbrl.org/815600DAEFB0388F3521/2023-12-31/ESEF/IT/0/815600DAEFB0388F3521-2023-12-31.zip",
        "filename": "reply-2023-esef.zip",
    },
    {
        "name": "Datalogic SpA",
        "lei": "815600A033443037ED66",
        "isin": "IT0001173215",
        "country": "IT",
        "year": "2023-12-31",
        "url": "https://filings.xbrl.org/815600A033443037ED66/2023-12-31/ESEF/IT/0/815600A033443037ED66-2023-12-31-it.zip",
        "filename": "datalogic-2023-esef.zip",
    },
    {
        "name": "Campari Group (Davide Campari-Milano NV)",
        "lei": "213800ED5AN2J56N6Z02",
        "isin": "NL0015435975",
        "country": "NL",
        "year": "2023-12-31",
        "url": "https://filings.xbrl.org/213800ED5AN2J56N6Z02/2023-12-31/ESEF/NL/0/davidecamparimilano-2023-12-31-NL.zip",
        "filename": "campari-2023-esef.zip",
    },
    {
        "name": "Amplifon SpA",
        "lei": "ZYXJDNVM2JI3VBM8G556",
        "isin": "IT0004056444",
        "country": "IT",
        "year": "2022-12-31",
        "url": "https://filings.xbrl.org/ZYXJDNVM2JI3VBM8G556/2022-12-31/ESEF/IT/0/ZYXJDNVM2JI3VBM8G556-2022-12-31-it.zip",
        "filename": "amplifon-2022-esef.zip",
    },
    # These four weren't in the filings.xbrl.org index — try company IR pages directly
    {
        "name": "De'Longhi SpA",
        "lei": "8156000E09A52C4F8A38",
        "isin": "IT0003115950",
        "country": "IT",
        "year": "2023-12-31",
        "url": None,
        "ir_page": "https://www.delonghigroup.com/en/investor-relations",
        "oam": "https://www.emarketstorage.it/",
        "filename": "delonghi-2023-esef.zip",
    },
    {
        "name": "Brunello Cucinelli SpA",
        "lei": None,
        "isin": "IT0004764699",
        "country": "IT",
        "year": "2023-12-31",
        "url": None,
        "ir_page": "https://investor.brunellocucinelli.com/en/services/archive/investor/financial-reports",
        "oam": "https://www.emarketstorage.it/",
        "filename": "brunellocucinelli-2023-esef.zip",
    },
    {
        "name": "Tod's SpA",
        "lei": None,
        "isin": "IT0003007021",
        "country": "IT",
        "year": "2023-12-31",
        "url": None,
        "ir_page": "https://www.todsgroup.com/en/investor-relations/financial-reports",
        "oam": "https://www.emarketstorage.it/",
        "filename": "tods-2023-esef.zip",
    },
]


def download(company: dict, out_dir: Path) -> bool:
    url = company.get("url")
    if not url:
        print(f"  SKIP {company['name']}: no direct URL — check IR page: {company.get('ir_page')}")
        return False

    dest = out_dir / company["filename"]
    if dest.exists():
        print(f"  EXISTS {dest.name} ({dest.stat().st_size // 1024} KB)")
        return True

    print(f"  Downloading {company['name']} …", end=" ", flush=True)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "xbrl-research/1.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
        dest.write_bytes(data)
        print(f"OK ({len(data) // 1024} KB) → {dest.name}")
        return True
    except Exception as exc:
        print(f"FAILED: {exc}")
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default="./esef_downloads", help="Output directory")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output: {out_dir.resolve()}\n")

    ok = failed = skipped = 0
    for company in COMPANIES:
        if company.get("url"):
            result = download(company, out_dir)
            if result:
                ok += 1
            else:
                failed += 1
            time.sleep(1)
        else:
            download(company, out_dir)
            skipped += 1

    print(f"\nDone: {ok} downloaded, {failed} failed, {skipped} need manual IR page download")


if __name__ == "__main__":
    main()

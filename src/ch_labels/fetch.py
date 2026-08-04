"""
Download a bulk accounts ZIP into raw/.
Supports daily and monthly files; resumes partial downloads via Range headers.

Usage:
  python -m ch_labels.fetch --daily              # most recent daily (~30 MB)
  python -m ch_labels.fetch --monthly            # most recent monthly (~500 MB–2.4 GB)
  python -m ch_labels.fetch --monthly October2024
  python -m ch_labels.fetch --daily 2025-07-01
"""

import argparse
import sys
from pathlib import Path

import httpx
from tqdm import tqdm

from .recon import (
    DAILY_INDEX, MONTHLY_INDEX,
    fetch_page, parse_daily_links, parse_monthly_links,
    HEADERS,
)

RAW_DIR = Path(__file__).parents[2] / "raw"
CHUNK   = 1 << 20  # 1 MB


def download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    existing = dest.stat().st_size if dest.exists() else 0
    headers = {**HEADERS}
    if existing:
        headers["Range"] = f"bytes={existing}-"

    with httpx.Client(headers=headers, follow_redirects=True, timeout=120) as client:
        with client.stream("GET", url) as r:
            if r.status_code == 416:
                print(f"Already complete: {dest}")
                return dest
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0)) + existing
            mode = "ab" if existing else "wb"
            with open(dest, mode) as f, tqdm(
                total=total,
                initial=existing,
                unit="B",
                unit_scale=True,
                desc=dest.name,
            ) as bar:
                for chunk in r.iter_bytes(CHUNK):
                    f.write(chunk)
                    bar.update(len(chunk))
    return dest


def resolve_daily(name_hint: str | None) -> dict:
    entries = parse_daily_links(fetch_page(DAILY_INDEX))
    if not entries:
        print("No daily files found.", file=sys.stderr)
        sys.exit(1)
    if name_hint:
        matches = [e for e in entries if name_hint in e["name"]]
        return matches[-1] if matches else entries[-1]
    return entries[-1]


def resolve_monthly(name_hint: str | None) -> dict:
    entries = parse_monthly_links(fetch_page(MONTHLY_INDEX))
    if not entries:
        print("No monthly files found on recent index. Try historic index.", file=sys.stderr)
        sys.exit(1)
    if name_hint:
        matches = [e for e in entries if name_hint.lower() in e["name"].lower()]
        return matches[-1] if matches else entries[-1]
    return entries[-1]


def main(args=None):
    parser = argparse.ArgumentParser(description="Download CH bulk accounts ZIP")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--daily",   nargs="?", const=True, metavar="DATE",
                       help="Download a daily file (YYYY-MM-DD or latest)")
    group.add_argument("--monthly", nargs="?", const=True, metavar="MONTHYEAR",
                       help="Download a monthly file (e.g. October2024 or latest)")
    opts = parser.parse_args(args)

    if opts.daily is not None:
        hint = None if opts.daily is True else opts.daily
        target = resolve_daily(hint)
    else:
        hint = None if opts.monthly is True else opts.monthly
        target = resolve_monthly(hint)

    dest = RAW_DIR / target["name"]
    print(f"Target : {target['url']}")
    print(f"Dest   : {dest}")
    download(target["url"], dest)
    print(f"\nSaved  : {dest}  ({dest.stat().st_size / 1_048_576:.1f} MB)")
    return dest


if __name__ == "__main__":
    main()

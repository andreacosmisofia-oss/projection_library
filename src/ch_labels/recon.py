"""
Reconnaissance: inspect the Companies House bulk data index without downloading.
Prints available packages, sizes, dates, and license info.
"""

import re
import sys
from datetime import datetime

import httpx
from rich.console import Console
from rich.table import Table

BULK_INDEX = "https://download.companieshouse.gov.uk/en_accountsdata.html"
HEADERS = {"User-Agent": "ch-label-extractor/0.1 (research; andrea.cosmi.sofia@gmail.com)"}

console = Console()


def fetch_index() -> str:
    with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=30) as client:
        r = client.get(BULK_INDEX)
        r.raise_for_status()
        return r.text


def parse_links(html: str) -> list[dict]:
    """Extract ZIP links with approximate sizes from the index page."""
    pattern = re.compile(
        r'href="([^"]*Accounts_Monthly_Data[^"]*\.zip)"[^>]*>.*?</a>',
        re.IGNORECASE | re.DOTALL,
    )
    entries = []
    for m in pattern.finditer(html):
        url = m.group(1)
        if not url.startswith("http"):
            url = "https://download.companieshouse.gov.uk/" + url.lstrip("/")
        name = url.split("/")[-1]
        # try to parse date from filename e.g. Accounts_Monthly_Data-March2024.zip
        date_m = re.search(r"(\w+)(\d{4})", name)
        date_str = f"{date_m.group(1)} {date_m.group(2)}" if date_m else "?"
        entries.append({"name": name, "url": url, "date_str": date_str})
    return entries


def head_size(url: str) -> str:
    try:
        with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=15) as client:
            r = client.head(url)
            cl = r.headers.get("content-length")
            if cl:
                mb = int(cl) / 1_048_576
                return f"{mb:.0f} MB"
    except Exception:
        pass
    return "?"


def main():
    console.print("[bold]Companies House bulk accounts — reconnaissance[/bold]\n")
    console.print(f"Fetching index: {BULK_INDEX}")

    html = fetch_index()

    # License block
    lic_m = re.search(
        r"(Open Government Licence|Creative Commons|OGL)[^<]{0,200}",
        html,
        re.IGNORECASE,
    )
    console.print(
        f"\n[bold]License:[/bold] {lic_m.group(0).strip() if lic_m else 'not found in page — check manually'}"
    )

    entries = parse_links(html)
    if not entries:
        console.print("[red]No monthly ZIP links found — index format may have changed.[/red]")
        console.print("Raw snippet:\n", html[:2000])
        sys.exit(1)

    console.print(f"\n[bold]{len(entries)} monthly packages found.[/bold]")
    console.print("Checking size of the most recent package…")

    latest = entries[-1]
    size = head_size(latest["url"])

    table = Table(title="Available packages (last 6)")
    table.add_column("Filename", style="cyan")
    table.add_column("Date", style="green")
    table.add_column("URL")
    for e in entries[-6:]:
        sz = size if e is latest else ""
        table.add_row(e["name"], e["date_str"], e["url"][:60] + "…")

    console.print(table)
    console.print(f"\n[bold]Most recent:[/bold] {latest['name']}  size ≈ {size}")
    console.print(f"URL: {latest['url']}")

    return entries


if __name__ == "__main__":
    main()

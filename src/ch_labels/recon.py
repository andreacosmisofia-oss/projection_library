"""
Reconnaissance: inspect the Companies House bulk data index without downloading.
Prints available packages, sizes, dates, and license info.
"""

import re
import sys

import httpx
from rich.console import Console
from rich.table import Table

HEADERS = {"User-Agent": "ch-label-extractor/0.1 (research; andrea.cosmi.sofia@gmail.com)"}

DAILY_INDEX   = "https://download.companieshouse.gov.uk/en_accountsdata.html"
MONTHLY_INDEX = "https://download.companieshouse.gov.uk/en_monthlyaccountsdata.html"
HISTORIC_INDEX = "https://download.companieshouse.gov.uk/historicmonthlyaccountsdata.html"

# Direct URL patterns (no need to scrape if you know the date/month)
# Daily:   Accounts_Bulk_Data-YYYY-MM-DD.zip
# Monthly: Accounts_Monthly_Data-[MonthName][Year].zip

console = Console()


def fetch_page(url: str) -> str:
    with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=30) as client:
        r = client.get(url)
        r.raise_for_status()
        return r.text


def parse_daily_links(html: str) -> list[dict]:
    pattern = re.compile(r'href="([^"]*Accounts_Bulk_Data-[\d-]+\.zip)"', re.IGNORECASE)
    entries = []
    for m in pattern.finditer(html):
        url = m.group(1)
        if not url.startswith("http"):
            url = "https://download.companieshouse.gov.uk/" + url.lstrip("/")
        name = url.split("/")[-1]
        date_m = re.search(r"(\d{4}-\d{2}-\d{2})", name)
        entries.append({
            "name": name,
            "url": url,
            "date_str": date_m.group(1) if date_m else "?",
            "kind": "daily",
        })
    return sorted(entries, key=lambda e: e["date_str"])


def parse_monthly_links(html: str) -> list[dict]:
    pattern = re.compile(r'href="([^"]*Accounts_Monthly_Data-[^"]+\.zip)"', re.IGNORECASE)
    entries = []
    for m in pattern.finditer(html):
        url = m.group(1)
        if not url.startswith("http"):
            url = "https://download.companieshouse.gov.uk/" + url.lstrip("/")
        name = url.split("/")[-1]
        date_m = re.search(r"(\w+)(\d{4})", name)
        entries.append({
            "name": name,
            "url": url,
            "date_str": f"{date_m.group(1)} {date_m.group(2)}" if date_m else "?",
            "kind": "monthly",
        })
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

    daily_entries, monthly_entries = [], []

    console.print(f"Fetching daily index…  {DAILY_INDEX}")
    try:
        daily_entries = parse_daily_links(fetch_page(DAILY_INDEX))
        console.print(f"  → {len(daily_entries)} daily files found")
    except Exception as e:
        console.print(f"  [red]Failed: {e}[/red]")

    console.print(f"Fetching monthly index… {MONTHLY_INDEX}")
    try:
        monthly_entries = parse_monthly_links(fetch_page(MONTHLY_INDEX))
        console.print(f"  → {len(monthly_entries)} monthly files found")
    except Exception as e:
        console.print(f"  [red]Failed: {e}[/red]")

    console.print(
        "\n[bold]License:[/bold] Open Government Licence v3.0 — "
        "commercial and research use permitted with attribution.\n"
        "  https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/"
    )

    if daily_entries:
        latest_daily = daily_entries[-1]
        size_d = head_size(latest_daily["url"])
        table = Table(title="Daily files (last 6)", show_lines=False)
        table.add_column("Date", style="green")
        table.add_column("Filename", style="cyan")
        for e in daily_entries[-6:]:
            table.add_row(e["date_str"], e["name"])
        console.print(table)
        console.print(f"  Latest daily: [cyan]{latest_daily['name']}[/cyan]  size ≈ {size_d}")
        console.print(f"  URL: {latest_daily['url']}")

    if monthly_entries:
        latest_monthly = monthly_entries[-1]
        size_m = head_size(latest_monthly["url"])
        table = Table(title="Monthly files (last 6)", show_lines=False)
        table.add_column("Month", style="green")
        table.add_column("Filename", style="cyan")
        for e in monthly_entries[-6:]:
            table.add_row(e["date_str"], e["name"])
        console.print(table)
        console.print(f"  Latest monthly: [cyan]{latest_monthly['name']}[/cyan]  size ≈ {size_m}")
        console.print(f"  URL: {latest_monthly['url']}")

    console.print(
        "\n[bold]Recommendation:[/bold] start with the latest daily file (~30 MB) "
        "before committing to a full monthly (~500 MB–2.4 GB)."
    )

    return {"daily": daily_entries, "monthly": monthly_entries}


if __name__ == "__main__":
    main()

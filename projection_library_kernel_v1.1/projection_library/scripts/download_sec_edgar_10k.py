"""Download 10-K filings from SEC EDGAR for a set of US companies.

For each ticker the script downloads:
  1. submissions.json   – full filing history from the EDGAR submissions API
  2. company_facts.json – all US-GAAP XBRL concepts from the company-facts API
  3. 10k_latest/        – filing-index + primary document of the most-recent 10-K

Output tree:
  sec_edgar_10k/
    {TICKER}/
      submissions.json
      company_facts.json
      10k_latest/
        filing_index.json
        {primary_document}

SEC EDGAR fair-use requirements:
  - User-Agent header must identify the application and a contact e-mail.
  - Observe the 10 requests-per-second rate limit.
"""
import json
import sys
import time
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

USER_AGENT = "projection-library-sec-downloader andrea.cosmi.sofia@gmail.com"

# Verified CIK numbers (zero-padded to 10 digits is done at runtime).
COMPANIES: dict[str, int] = {
    "CAT":  18230,       # Caterpillar Inc.
    "PG":   80424,       # Procter & Gamble Co.
    "GM":   1467858,     # General Motors Co.
    "PFE":  78003,       # Pfizer Inc.
    "ORCL": 1341439,     # Oracle Corporation
    "T":    732717,      # AT&T Inc.
    "FCX":  831259,      # Freeport-McMoRan Inc.
    "FDX":  1048911,     # FedEx Corporation
    "NKE":  320187,      # Nike Inc.
    "BA":   12927,       # Boeing Co.
}

BASE_DATA  = "https://data.sec.gov"
BASE_EDGAR = "https://www.sec.gov/Archives/edgar/data"

# Seconds between consecutive requests to respect the SEC 10 req/s limit.
REQUEST_DELAY = 0.15

OUT_DIR = Path(__file__).resolve().parent.parent / "sec_edgar_10k"


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def _get(url: str, session: requests.Session) -> requests.Response:
    """GET with rate-limiting and basic error handling."""
    time.sleep(REQUEST_DELAY)
    resp = session.get(url, timeout=30)
    resp.raise_for_status()
    return resp


def _save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"    saved → {path.relative_to(OUT_DIR.parent)}")


def _save_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    print(f"    saved → {path.relative_to(OUT_DIR.parent)}")


# ---------------------------------------------------------------------------
# Per-company download
# ---------------------------------------------------------------------------

def download_company(ticker: str, cik: int, session: requests.Session) -> dict:
    """Download all three artefacts for one company. Returns a summary dict."""
    cik_str   = str(cik).zfill(10)
    company_dir = OUT_DIR / ticker
    summary: dict = {"ticker": ticker, "cik": cik, "status": "ok", "errors": []}

    print(f"\n{'='*60}")
    print(f"  {ticker}  (CIK {cik_str})")
    print(f"{'='*60}")

    # ------------------------------------------------------------------
    # 1. Submissions metadata
    # ------------------------------------------------------------------
    subs_url  = f"{BASE_DATA}/submissions/CIK{cik_str}.json"
    subs_path = company_dir / "submissions.json"
    try:
        print(f"  [1/3] submissions …")
        subs_data = _get(subs_url, session).json()
        _save_json(subs_path, subs_data)
        summary["entity_name"] = subs_data.get("name", "")
        summary["sic"]         = subs_data.get("sic", "")
        summary["sic_desc"]    = subs_data.get("sicDescription", "")
    except Exception as exc:
        msg = f"submissions failed: {exc}"
        print(f"    ERROR: {msg}")
        summary["errors"].append(msg)
        subs_data = {}

    # ------------------------------------------------------------------
    # 2. Company facts (US-GAAP XBRL)
    # ------------------------------------------------------------------
    facts_url  = f"{BASE_DATA}/api/xbrl/companyfacts/CIK{cik_str}.json"
    facts_path = company_dir / "company_facts.json"
    try:
        print(f"  [2/3] company facts (US-GAAP) …")
        facts_data = _get(facts_url, session).json()
        _save_json(facts_path, facts_data)
        gaap_concepts = list(facts_data.get("facts", {}).get("us-gaap", {}).keys())
        summary["gaap_concepts"] = len(gaap_concepts)
    except Exception as exc:
        msg = f"company_facts failed: {exc}"
        print(f"    ERROR: {msg}")
        summary["errors"].append(msg)

    # ------------------------------------------------------------------
    # 3. Most-recent 10-K filing (index + primary document)
    # ------------------------------------------------------------------
    print(f"  [3/3] latest 10-K filing …")
    filing_dir = company_dir / "10k_latest"

    try:
        recent_filings = subs_data.get("filings", {}).get("recent", {})
        forms     = recent_filings.get("form",       [])
        accessions = recent_filings.get("accessionNumber", [])
        dates      = recent_filings.get("filingDate",      [])
        primaries  = recent_filings.get("primaryDocument",  [])

        # Find the most-recent 10-K (exact match)
        tenk_idx = next(
            (i for i, f in enumerate(forms) if f == "10-K"),
            None,
        )
        if tenk_idx is None:
            raise ValueError("no 10-K found in recent filings; try older page")

        accession_raw  = accessions[tenk_idx]             # "0000018230-24-000009"
        accession_nd   = accession_raw.replace("-", "")   # "000001823024000009"
        filing_date    = dates[tenk_idx]
        primary_doc    = primaries[tenk_idx]

        summary["latest_10k_accession"] = accession_raw
        summary["latest_10k_date"]      = filing_date
        summary["latest_10k_document"]  = primary_doc
        print(f"    accession: {accession_raw}  filed: {filing_date}")

        # Filing index JSON
        index_url  = f"{BASE_EDGAR}/{cik}/{accession_nd}/{accession_nd}-index.json"
        index_path = filing_dir / "filing_index.json"
        index_data = _get(index_url, session).json()
        _save_json(index_path, index_data)

        # Primary 10-K document (htm / xml / txt)
        doc_url  = f"{BASE_EDGAR}/{cik}/{accession_nd}/{primary_doc}"
        doc_path = filing_dir / primary_doc
        doc_resp = _get(doc_url, session)
        _save_bytes(doc_path, doc_resp.content)

    except Exception as exc:
        msg = f"10-K document failed: {exc}"
        print(f"    ERROR: {msg}")
        summary["errors"].append(msg)

    if summary["errors"]:
        summary["status"] = "partial"

    return summary


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Output directory: {OUT_DIR}")

    session = requests.Session()
    session.headers.update({
        "User-Agent":      USER_AGENT,
        "Accept-Encoding": "gzip, deflate",
        "Accept":          "application/json",
    })

    summaries: list[dict] = []
    for ticker, cik in COMPANIES.items():
        try:
            s = download_company(ticker, cik, session)
        except Exception as exc:
            print(f"\nFATAL error for {ticker}: {exc}")
            s = {"ticker": ticker, "cik": cik, "status": "failed", "errors": [str(exc)]}
        summaries.append(s)

    # Save a consolidated manifest
    manifest_path = OUT_DIR / "download_manifest.json"
    manifest = {
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "companies":        summaries,
    }
    _save_json(manifest_path, manifest)

    # Print summary table
    print(f"\n{'='*60}")
    print("DOWNLOAD SUMMARY")
    print(f"{'='*60}")
    header = f"{'TICKER':<8}{'CIK':>10}  {'DATE':>12}  {'STATUS':<10}  ERRORS"
    print(header)
    print("-" * 60)
    for s in summaries:
        date   = s.get("latest_10k_date", "—")
        status = s.get("status", "?")
        errors = "; ".join(s.get("errors", []))[:40]
        print(f"{s['ticker']:<8}{s['cik']:>10}  {date:>12}  {status:<10}  {errors}")
    print(f"\nManifest: {manifest_path}")


if __name__ == "__main__":
    main()

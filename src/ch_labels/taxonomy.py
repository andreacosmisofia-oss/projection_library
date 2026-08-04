"""
Download and parse an FRC XBRL taxonomy suite into ref/.

The FRC does not publish a stable direct ZIP URL — the link lives on the suite page.
This module tries to discover and download the ZIP automatically; if it fails,
it prints the URL to visit manually.

Produces:
  ref/frc_taxonomy.zip        – raw ZIP
  ref/taxonomy_concepts.csv   – concept, data_type, period_type, abstract
  ref/taxonomy_labels.json    – {concept: [standard labels]}

FRC taxonomy suite pages:
  2026: https://www.frc.org.uk/.../2026-frc-taxonomy-suite/
  2025: https://www.frc.org.uk/.../2025-frc-taxonomy-suite/
"""

import json
import re
import zipfile
from pathlib import Path

import httpx
import polars as pl
from lxml import etree
from rich.console import Console

REF_DIR = Path(__file__).parents[2] / "ref"
HEADERS = {"User-Agent": "ch-label-extractor/0.1 (research; andrea.cosmi.sofia@gmail.com)"}

FRC_SUITE_PAGES = [
    "https://www.frc.org.uk/library/standards-codes-policy/accounting-and-reporting/frc-taxonomies/current-frc-taxonomy-suites/2026-frc-taxonomy-suite/",
    "https://www.frc.org.uk/library/standards-codes-policy/accounting-and-reporting/frc-taxonomies/current-frc-taxonomy-suites/2025-frc-taxonomy-suite/",
]

console = Console()


def find_zip_url(page_url: str) -> str | None:
    """Scrape an FRC suite page to find the taxonomy ZIP download link."""
    try:
        with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=30) as client:
            r = client.get(page_url)
            r.raise_for_status()
            html = r.text
        for pat in [
            r'href="([^"]*taxonomy[^"]*\.zip)"',
            r'href="([^"]*frc[^"]*\.zip)"',
            r'href="([^"]*\.zip)"',
        ]:
            m = re.search(pat, html, re.IGNORECASE)
            if m:
                url = m.group(1)
                if not url.startswith("http"):
                    from urllib.parse import urljoin
                    url = urljoin(page_url, url)
                return url
    except Exception as e:
        console.print(f"  [yellow]Could not fetch {page_url}: {e}[/yellow]")
    return None


def download_zip(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    console.print(f"Downloading: {url}")
    with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=300) as client:
        with client.stream("GET", url) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            with open(dest, "wb") as f:
                for chunk in r.iter_bytes(1 << 20):
                    f.write(chunk)
    console.print(f"Saved: {dest}  ({dest.stat().st_size/1_048_576:.1f} MB)")
    return dest


def parse_label_linkbase(content: bytes, concept_labels: dict):
    try:
        root = etree.fromstring(content)
    except Exception:
        return
    ns = {
        "link":  "http://www.xbrl.org/2003/linkbase",
        "xlink": "http://www.w3.org/1999/xlink",
        "xml":   "http://www.w3.org/XML/1998/namespace",
    }
    label_map: dict[str, str] = {}
    for lel in root.findall(".//link:label", ns):
        xlab = lel.get("{http://www.w3.org/1999/xlink}label", "")
        role = lel.get("{http://www.w3.org/1999/xlink}role", "")
        lang = lel.get("{http://www.w3.org/XML/1998/namespace}lang", "en")
        if "en" in lang and "standard" in role.lower():
            label_map[xlab] = (lel.text or "").strip()

    loc_map: dict[str, str] = {}
    for loc in root.findall(".//link:loc", ns):
        href = loc.get("{http://www.w3.org/1999/xlink}href", "")
        xlab = loc.get("{http://www.w3.org/1999/xlink}label", "")
        concept = href.split("#")[-1] if "#" in href else href.split("/")[-1]
        loc_map[xlab] = concept

    for arc in root.findall(".//link:labelArc", ns):
        from_lab = arc.get("{http://www.w3.org/1999/xlink}from", "")
        to_lab   = arc.get("{http://www.w3.org/1999/xlink}to", "")
        concept  = loc_map.get(from_lab, "")
        text     = label_map.get(to_lab, "")
        if concept and text:
            concept_labels.setdefault(concept, [])
            if text not in concept_labels[concept]:
                concept_labels[concept].append(text)


def parse_schema(content: bytes) -> list[dict]:
    concepts = []
    try:
        root = etree.fromstring(content)
    except Exception:
        return concepts
    ns = {"xs": "http://www.w3.org/2001/XMLSchema"}
    for el in root.findall(".//xs:element", ns):
        name = el.get("name", "")
        if not name:
            continue
        concepts.append({
            "concept":     name,
            "data_type":   el.get("type", ""),
            "period_type": el.get("{http://www.xbrl.org/2003/instance}periodType", ""),
            "abstract":    el.get("abstract", "false"),
        })
    return concepts


def process_taxonomy_zip(zip_path: Path) -> tuple[list[dict], dict]:
    concept_labels: dict[str, list[str]] = {}
    all_concepts: list[dict] = []
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        schemas   = [n for n in names if n.endswith(".xsd")]
        labelinks = [n for n in names if n.endswith(".xml") and "lab" in n.lower()]
        console.print(f"  Schemas   : {len(schemas)}")
        console.print(f"  Labelinks : {len(labelinks)}")
        for s in schemas:
            all_concepts.extend(parse_schema(zf.read(s)))
        for lb in labelinks:
            parse_label_linkbase(zf.read(lb), concept_labels)
    return all_concepts, concept_labels


def main():
    REF_DIR.mkdir(parents=True, exist_ok=True)
    tax_zip = REF_DIR / "frc_taxonomy.zip"

    if not tax_zip.exists():
        zip_url = None
        for page in FRC_SUITE_PAGES:
            console.print(f"Looking for ZIP on: {page}")
            zip_url = find_zip_url(page)
            if zip_url:
                console.print(f"  Found: {zip_url}")
                break

        if not zip_url:
            console.print(
                "\n[yellow]Could not discover ZIP URL automatically.[/yellow]\n"
                "Visit one of these pages, download the taxonomy ZIP, "
                f"and save it as:\n  [cyan]{tax_zip}[/cyan]\n\n"
                "Suite pages:\n"
            )
            for p in FRC_SUITE_PAGES:
                console.print(f"  {p}")
            console.print("\nContact: xbrl@frc.org.uk")
            return

        download_zip(zip_url, tax_zip)

    console.print(f"\nParsing {tax_zip}…")
    concepts, concept_labels = process_taxonomy_zip(tax_zip)
    console.print(f"  Concepts parsed   : {len(concepts):,}")
    console.print(f"  Concepts labelled : {len(concept_labels):,}")

    if concepts:
        df = pl.DataFrame(concepts).unique(subset=["concept"])
        p = REF_DIR / "taxonomy_concepts.csv"
        df.write_csv(p)
        console.print(f"Saved: {p}")

    p = REF_DIR / "taxonomy_labels.json"
    p.write_text(json.dumps(concept_labels, indent=2, ensure_ascii=False))
    console.print(f"Saved: {p}")

    return concepts, concept_labels


if __name__ == "__main__":
    main()

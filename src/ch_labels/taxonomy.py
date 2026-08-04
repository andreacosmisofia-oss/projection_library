"""
Download and parse the FRC XBRL taxonomy into ref/.

Produces:
  ref/taxonomy_concepts.csv   – concept, label, data_type, period_type, parent
  ref/taxonomy_labels.json    – {concept: [list of standard labels]}
"""

import re
import zipfile
from io import BytesIO
from pathlib import Path

import httpx
import polars as pl
from lxml import etree
from rich.console import Console

REF_DIR = Path(__file__).parents[2] / "ref"
HEADERS = {"User-Agent": "ch-label-extractor/0.1 (research; andrea.cosmi.sofia@gmail.com)"}

console = Console()

# FRC taxonomy — current release landing page and direct ZIP
FRC_TAXONOMY_INDEX = "https://xbrl.frc.org.uk/taxonomy/current"
FRC_TAXONOMY_ZIP   = "https://xbrl.frc.org.uk/taxonomy/current/taxonomy.zip"

# Fallback: HMRC taxonomy (used for filing)
HMRC_TAXONOMY_ZIP = "https://www.gov.uk/government/uploads/system/uploads/attachment_data/file/taxonomy.zip"


def download_taxonomy(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    console.print(f"Downloading: {url}")
    with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=120) as client:
        r = client.get(url)
        r.raise_for_status()
        dest.write_bytes(r.content)
    console.print(f"Saved: {dest}  ({dest.stat().st_size/1_048_576:.1f} MB)")
    return dest


def parse_label_linkbase(content: bytes, concept_labels: dict):
    """Parse an XBRL label linkbase and populate concept_labels dict."""
    try:
        root = etree.fromstring(content)
    except Exception:
        return

    ns = {
        "link":  "http://www.xbrl.org/2003/linkbase",
        "xlink": "http://www.w3.org/1999/xlink",
        "xml":   "http://www.w3.org/XML/1998/namespace",
    }

    label_els = root.findall(".//link:label", ns)
    loc_els   = root.findall(".//link:loc", ns)
    arc_els   = root.findall(".//link:labelArc", ns)

    # Build href → label_id map
    label_map: dict[str, str] = {}  # label xlink:label → text
    for lel in label_els:
        xlab = lel.get("{http://www.w3.org/1999/xlink}label", "")
        role = lel.get("{http://www.w3.org/1999/xlink}role", "")
        lang = lel.get("{http://www.w3.org/XML/1998/namespace}lang", "en")
        if "en" in lang and "standard" in role.lower():
            label_map[xlab] = (lel.text or "").strip()

    # Loc: concept href → xlink:label
    loc_map: dict[str, str] = {}
    for loc in loc_els:
        href  = loc.get("{http://www.w3.org/1999/xlink}href", "")
        xlab  = loc.get("{http://www.w3.org/1999/xlink}label", "")
        concept = href.split("#")[-1] if "#" in href else href.split("/")[-1]
        loc_map[xlab] = concept

    # Arcs link loc → label
    for arc in arc_els:
        from_lab = arc.get("{http://www.w3.org/1999/xlink}from", "")
        to_lab   = arc.get("{http://www.w3.org/1999/xlink}to", "")
        concept  = loc_map.get(from_lab, "")
        text     = label_map.get(to_lab, "")
        if concept and text:
            concept_labels.setdefault(concept, [])
            if text not in concept_labels[concept]:
                concept_labels[concept].append(text)


def parse_schema(content: bytes) -> list[dict]:
    """Parse an XBRL schema (.xsd) and extract concept metadata."""
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
            "period_type": el.get(
                "{http://www.xbrl.org/2003/instance}periodType", ""
            ),
            "abstract":    el.get("abstract", "false"),
            "nillable":    el.get("nillable", "true"),
        })
    return concepts


def process_taxonomy_zip(zip_path: Path) -> tuple[list[dict], dict]:
    concept_labels: dict[str, list[str]] = {}
    all_concepts: list[dict] = []

    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        schemas   = [n for n in names if n.endswith(".xsd")]
        labelinks = [n for n in names if n.endswith(".xml") and "lab" in n.lower()]

        console.print(f"  Schemas found     : {len(schemas)}")
        console.print(f"  Label linkbases   : {len(labelinks)}")

        for schema in schemas:
            all_concepts.extend(parse_schema(zf.read(schema)))

        for link in labelinks:
            parse_label_linkbase(zf.read(link), concept_labels)

    return all_concepts, concept_labels


def main():
    REF_DIR.mkdir(parents=True, exist_ok=True)

    tax_zip = REF_DIR / "frc_taxonomy.zip"
    if not tax_zip.exists():
        try:
            download_taxonomy(FRC_TAXONOMY_ZIP, tax_zip)
        except Exception as e:
            console.print(f"[yellow]FRC direct URL failed ({e}), trying index…[/yellow]")
            # Try to find the URL from the index page
            with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=30) as client:
                r = client.get(FRC_TAXONOMY_INDEX)
                zip_m = re.search(r'href="([^"]+\.zip)"', r.text)
                if zip_m:
                    url = zip_m.group(1)
                    if not url.startswith("http"):
                        url = "https://xbrl.frc.org.uk" + url
                    download_taxonomy(url, tax_zip)
                else:
                    console.print("[red]Could not find taxonomy ZIP. Check FRC website manually.[/red]")
                    console.print(f"Manual download: {FRC_TAXONOMY_INDEX}")
                    return

    console.print(f"\nParsing {tax_zip}…")
    concepts, concept_labels = process_taxonomy_zip(tax_zip)

    console.print(f"  Concepts parsed   : {len(concepts):,}")
    console.print(f"  Concepts labelled : {len(concept_labels):,}")

    # Save concepts CSV
    if concepts:
        df = pl.DataFrame(concepts)
        df = df.unique(subset=["concept"])
        concepts_path = REF_DIR / "taxonomy_concepts.csv"
        df.write_csv(concepts_path)
        console.print(f"Saved: {concepts_path}")

    # Save labels JSON
    import json
    labels_path = REF_DIR / "taxonomy_labels.json"
    labels_path.write_text(json.dumps(concept_labels, indent=2, ensure_ascii=False))
    console.print(f"Saved: {labels_path}")

    return concepts, concept_labels


if __name__ == "__main__":
    main()

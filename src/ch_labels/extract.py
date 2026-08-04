"""
Extract (label, tag, value, unit, period, doc_type, company_size) from every
iXBRL/XBRL document inside a bulk ZIP.

Output: out/facts_<zipname>.parquet  (one row per fact)
"""

import io
import json
import re
import zipfile
from pathlib import Path
from typing import Iterator

import polars as pl
from lxml import etree
from tqdm import tqdm

RAW_DIR = Path(__file__).parents[2] / "raw"
OUT_DIR = Path(__file__).parents[2] / "out"

# Namespaces we care about
IX_NS = {
    "ix":      "http://www.xbrl.org/2013/inlineXBRL",
    "ix09":    "http://www.xbrl.org/2008/inlineXBRL",
    "xbrli":   "http://www.xbrl.org/2003/instance",
    "xbrldi":  "http://xbrl.org/2006/xbrldi",
    "link":    "http://www.xbrl.org/2003/linkbase",
    "xlink":   "http://www.w3.org/1999/xlink",
}

# Taxonomy prefixes we want to keep (FRC / HMRC / UK GAAP / IFRS)
INTERESTING_PREFIXES = re.compile(
    r"^(uk-bus|uk-core|uk-direp|uk-gaap|frs|hmrc|ifrs|us-gaap|dei)",
    re.IGNORECASE,
)


def _qname_parts(name: str) -> tuple[str, str]:
    """Split '{ns}local' or 'prefix:local' into (ns_or_prefix, local)."""
    if name.startswith("{"):
        ns, local = name[1:].split("}", 1)
        return ns, local
    if ":" in name:
        prefix, local = name.split(":", 1)
        return prefix, local
    return "", name


def _tag_from_element(el: etree._Element, nsmap: dict) -> str:
    """Return 'prefix:local' using the document's own nsmap."""
    ns, local = _qname_parts(el.tag)
    if ns:
        for pref, uri in nsmap.items():
            if uri == ns and pref:
                return f"{pref}:{local}"
        # fallback: use last segment of URI
        slug = ns.rstrip("/").split("/")[-1]
        return f"{slug}:{local}"
    return local


def _attr_tag(name_attr: str) -> str:
    """Convert a 'prefix:local' name attribute to canonical tag string."""
    return name_attr.strip()


def extract_ixbrl(content: bytes, filename: str) -> list[dict]:
    """Parse one iXBRL or XBRL document and return a list of fact dicts."""
    rows = []
    try:
        root = etree.fromstring(content)
    except etree.XMLSyntaxError:
        # Some filings are HTML with embedded iXBRL — try HTML parser
        try:
            root = etree.fromstring(content, parser=etree.HTMLParser())
        except Exception:
            return rows

    nsmap = {k: v for k, v in root.nsmap.items() if k}  # skip default ns key

    def _resolve_context(ctx_ref: str, ctx_map: dict) -> tuple[str, str]:
        ctx = ctx_map.get(ctx_ref, {})
        period = ctx.get("period", "")
        entity = ctx.get("entity", "")
        return period, entity

    # Build context map (XBRL instance documents)
    ctx_map: dict[str, dict] = {}
    for ctx_el in root.iter("{http://www.xbrl.org/2003/instance}context"):
        cid = ctx_el.get("id", "")
        period_el = ctx_el.find(".//{http://www.xbrl.org/2003/instance}period")
        if period_el is not None:
            instant = period_el.find("{http://www.xbrl.org/2003/instance}instant")
            start   = period_el.find("{http://www.xbrl.org/2003/instance}startDate")
            end     = period_el.find("{http://www.xbrl.org/2003/instance}endDate")
            if instant is not None:
                period_str = instant.text or ""
            elif start is not None and end is not None:
                period_str = f"{start.text}/{end.text}"
            else:
                period_str = ""
        else:
            period_str = ""
        ctx_map[cid] = {"period": period_str}

    # Build unit map
    unit_map: dict[str, str] = {}
    for unit_el in root.iter("{http://www.xbrl.org/2003/instance}unit"):
        uid = unit_el.get("id", "")
        meas = unit_el.find("{http://www.xbrl.org/2003/instance}measure")
        if meas is not None:
            unit_map[uid] = (meas.text or "").split(":")[-1]

    # Detect doc type / company size from a few heuristics
    doc_type = _guess_doc_type(root)
    company_size = _guess_company_size(root)

    # --- iXBRL inline facts ---
    for tag_name in (
        "nonNumeric", "nonFraction", "fraction",
        "{http://www.xbrl.org/2013/inlineXBRL}nonNumeric",
        "{http://www.xbrl.org/2013/inlineXBRL}nonFraction",
        "{http://www.xbrl.org/2008/inlineXBRL}nonNumeric",
        "{http://www.xbrl.org/2008/inlineXBRL}nonFraction",
    ):
        for el in root.iter(tag_name):
            name_attr = el.get("name", "")
            if not name_attr:
                continue
            label = _collect_text(el).strip()
            if not label:
                continue
            ctx_ref = el.get("contextRef", "")
            unit_ref = el.get("unitRef", "")
            period, _ = _resolve_context(ctx_ref, ctx_map)
            unit = unit_map.get(unit_ref, unit_ref)
            rows.append({
                "label":        label,
                "tag":          _attr_tag(name_attr),
                "value":        el.get("value") or label,
                "unit":         unit,
                "period":       period,
                "doc_type":     doc_type,
                "company_size": company_size,
                "source_file":  filename,
            })

    # --- Plain XBRL instance facts (non-inline) ---
    if not rows:
        for el in root.iter():
            ns, local = _qname_parts(el.tag)
            if not ns or ns == "http://www.xbrl.org/2003/instance":
                continue
            tag_str = _tag_from_element(el, nsmap)
            if not INTERESTING_PREFIXES.match(tag_str):
                continue
            label = (el.text or "").strip()
            if not label:
                continue
            ctx_ref = el.get("contextRef", "")
            unit_ref = el.get("unitRef", "")
            period, _ = _resolve_context(ctx_ref, ctx_map)
            unit = unit_map.get(unit_ref, unit_ref)
            rows.append({
                "label":        label,
                "tag":          tag_str,
                "value":        label,
                "unit":         unit,
                "period":       period,
                "doc_type":     doc_type,
                "company_size": company_size,
                "source_file":  filename,
            })

    return rows


def _collect_text(el: etree._Element) -> str:
    """Collect all text inside an element, skipping hidden child elements."""
    parts = []
    if el.text:
        parts.append(el.text)
    for child in el:
        style = (child.get("style") or "").lower()
        if "display:none" not in style and "display: none" not in style:
            parts.append(_collect_text(child))
        if child.tail:
            parts.append(child.tail)
    return " ".join(p for p in parts if p.strip())


def _guess_doc_type(root: etree._Element) -> str:
    text = (etree.tostring(root, method="text", encoding="unicode") or "")[:4000].lower()
    if "full accounts" in text:
        return "full"
    if "abridged" in text:
        return "abridged"
    if "filleted" in text:
        return "filleted"
    if "micro" in text:
        return "micro"
    if "small" in text:
        return "small"
    return "unknown"


def _guess_company_size(root: etree._Element) -> str:
    text = (etree.tostring(root, method="text", encoding="unicode") or "")[:4000].lower()
    for size in ("micro", "small", "medium", "large"):
        if size in text:
            return size
    return "unknown"


def _is_xbrl(name: str) -> bool:
    return name.lower().endswith((".xml", ".xbrl", ".ixbrl", ".xhtml", ".html", ".htm"))


def process_zip(zip_path: Path) -> pl.DataFrame:
    rows_all: list[dict] = []
    stats = {"total": 0, "ixbrl": 0, "xbrl": 0, "skipped": 0}

    with zipfile.ZipFile(zip_path) as outer:
        names = outer.namelist()
        # Each entry may itself be a ZIP (one per company)
        inner_zips = [n for n in names if n.lower().endswith(".zip")]
        xml_direct = [n for n in names if _is_xbrl(n)]

        items = inner_zips if inner_zips else xml_direct
        for item_name in tqdm(items, desc=zip_path.name, unit="filing"):
            try:
                raw = outer.read(item_name)
                if item_name.lower().endswith(".zip"):
                    with zipfile.ZipFile(io.BytesIO(raw)) as inner:
                        for fname in inner.namelist():
                            if _is_xbrl(fname):
                                stats["total"] += 1
                                content = inner.read(fname)
                                is_ix = b"inlineXBRL" in content[:2000] or b"ix:" in content[:2000]
                                if is_ix:
                                    stats["ixbrl"] += 1
                                else:
                                    stats["xbrl"] += 1
                                rows_all.extend(extract_ixbrl(content, fname))
                else:
                    stats["total"] += 1
                    is_ix = b"inlineXBRL" in raw[:2000] or b"ix:" in raw[:2000]
                    if is_ix:
                        stats["ixbrl"] += 1
                    else:
                        stats["xbrl"] += 1
                    rows_all.extend(extract_ixbrl(raw, item_name))
            except Exception as exc:
                stats["skipped"] += 1

    print(f"\nStats for {zip_path.name}:")
    print(f"  Total documents : {stats['total']}")
    print(f"  iXBRL           : {stats['ixbrl']} ({100*stats['ixbrl']//max(stats['total'],1)}%)")
    print(f"  plain XBRL      : {stats['xbrl']}")
    print(f"  Skipped (errors): {stats['skipped']}")
    print(f"  Facts extracted : {len(rows_all)}")

    if not rows_all:
        return pl.DataFrame()

    df = pl.DataFrame(rows_all, infer_schema_length=1000)
    return df


def main(zip_name: str | None = None):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if zip_name:
        zip_path = RAW_DIR / zip_name
    else:
        zips = sorted(RAW_DIR.glob("*.zip"))
        if not zips:
            print("No ZIPs in raw/")
            return
        zip_path = zips[-1]

    print(f"Processing: {zip_path}")
    df = process_zip(zip_path)

    if df.is_empty():
        print("No facts extracted.")
        return

    out_path = OUT_DIR / f"facts_{zip_path.stem}.parquet"
    df.write_parquet(out_path)
    print(f"Saved: {out_path}  ({len(df)} rows, {out_path.stat().st_size/1_048_576:.1f} MB)")
    return out_path


if __name__ == "__main__":
    import sys
    main(sys.argv[1] if len(sys.argv) > 1 else None)

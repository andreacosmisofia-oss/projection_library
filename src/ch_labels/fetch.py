"""
Download the most recent (or a named) monthly bulk ZIP into raw/.
Resumes partial downloads via Range headers.
"""

import sys
from pathlib import Path

import httpx
from tqdm import tqdm

from .recon import fetch_index, parse_links, HEADERS

RAW_DIR = Path(__file__).parents[2] / "raw"
CHUNK = 1 << 20  # 1 MB


def download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    existing = dest.stat().st_size if dest.exists() else 0
    headers = {**HEADERS}
    if existing:
        headers["Range"] = f"bytes={existing}-"

    with httpx.Client(headers=headers, follow_redirects=True, timeout=60) as client:
        with client.stream("GET", url) as r:
            if r.status_code == 416:  # already complete
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


def main(name: str | None = None):
    html = fetch_index()
    entries = parse_links(html)
    if not entries:
        print("No packages found.", file=sys.stderr)
        sys.exit(1)

    if name:
        matches = [e for e in entries if name.lower() in e["name"].lower()]
        target = matches[-1] if matches else None
    else:
        target = entries[-1]

    if not target:
        print(f"Package not found: {name}", file=sys.stderr)
        sys.exit(1)

    dest = RAW_DIR / target["name"]
    print(f"Target: {target['url']}")
    print(f"Destination: {dest}")
    download(target["url"], dest)
    print(f"\nSaved: {dest}  ({dest.stat().st_size / 1_048_576:.1f} MB)")
    return dest


if __name__ == "__main__":
    import sys
    main(sys.argv[1] if len(sys.argv) > 1 else None)

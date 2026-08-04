"""
Aggregate facts parquet → out/dictionary.parquet + out/dictionary.csv

Schema:
  label       str   – as it appears in the document
  tag         str   – XBRL tag with namespace prefix
  freq        int   – occurrences across all filings
  tag_freq    int   – total occurrences of this tag (all labels)
  label_rank  int   – rank of this label for its tag (1 = most frequent)
"""

import sys
from pathlib import Path

import polars as pl
from rich.console import Console
from rich.table import Table

OUT_DIR = Path(__file__).parents[2] / "out"
console = Console()


def build_dictionary(facts_path: Path) -> pl.DataFrame:
    df = pl.read_parquet(facts_path)

    # Count (label, tag) pairs
    pairs = (
        df.group_by(["label", "tag"])
        .agg(pl.len().alias("freq"))
        .sort("freq", descending=True)
    )

    # Tag-level total frequency
    tag_totals = (
        pairs.group_by("tag")
        .agg(pl.col("freq").sum().alias("tag_freq"))
    )

    pairs = pairs.join(tag_totals, on="tag")

    # Rank of each label within its tag
    pairs = pairs.with_columns(
        pl.col("freq")
        .rank(method="dense", descending=True)
        .over("tag")
        .cast(pl.Int32)
        .alias("label_rank")
    )

    return pairs.sort(["freq"], descending=True)


def report(dictionary: pl.DataFrame):
    n_pairs  = len(dictionary)
    n_tags   = dictionary["tag"].n_unique()
    n_labels = dictionary["label"].n_unique()

    labels_per_tag = (
        dictionary.group_by("tag")
        .agg(pl.len().alias("n_labels"))
        .sort("n_labels", descending=True)
    )
    avg_lpt  = labels_per_tag["n_labels"].mean()
    max_lpt  = labels_per_tag["n_labels"].max()
    worst_tag = labels_per_tag.row(0, named=True)["tag"]

    console.print("\n[bold]Aggregation summary[/bold]")
    console.print(f"  Distinct (label, tag) pairs : {n_pairs:,}")
    console.print(f"  Distinct tags               : {n_tags:,}")
    console.print(f"  Distinct labels             : {n_labels:,}")
    console.print(f"  Labels per tag (avg)        : {avg_lpt:.1f}")
    console.print(f"  Labels per tag (max)        : {max_lpt}  [{worst_tag}]")

    # Top-50 by frequency
    top50 = dictionary.head(50)
    table = Table(title="\nTop 50 pairs by frequency", show_lines=False)
    table.add_column("#",      style="dim", width=4)
    table.add_column("freq",   style="green", width=8)
    table.add_column("label",  style="cyan", max_width=50)
    table.add_column("tag",    style="yellow", max_width=55)

    for i, row in enumerate(top50.iter_rows(named=True), 1):
        table.add_row(str(i), str(row["freq"]), row["label"], row["tag"])

    console.print(table)


def main(facts_glob: str | None = None):
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if facts_glob:
        paths = list(Path(".").glob(facts_glob))
    else:
        paths = sorted(OUT_DIR.glob("facts_*.parquet"))

    if not paths:
        console.print("[red]No facts parquet files found.[/red]")
        sys.exit(1)

    console.print(f"Loading {len(paths)} parquet file(s)…")
    if len(paths) == 1:
        df = pl.read_parquet(paths[0])
    else:
        df = pl.concat([pl.read_parquet(p) for p in paths])

    console.print(f"Total facts: {len(df):,}")

    # Save a temporary facts parquet for the aggregation call
    tmp = OUT_DIR / "_tmp_facts.parquet"
    df.write_parquet(tmp)

    dictionary = build_dictionary(tmp)
    tmp.unlink(missing_ok=True)

    # Save outputs
    dict_parquet = OUT_DIR / "dictionary.parquet"
    dict_csv     = OUT_DIR / "dictionary.csv"
    dictionary.write_parquet(dict_parquet)
    dictionary.write_csv(dict_csv)

    console.print(f"\nSaved: {dict_parquet}")
    console.print(f"Saved: {dict_csv}")

    report(dictionary)
    return dictionary


if __name__ == "__main__":
    import sys
    main(sys.argv[1] if len(sys.argv) > 1 else None)

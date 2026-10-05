"""Orchestration: read CSV, scrape each store, write CSV + JSON + report."""

import argparse
import csv
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from .aggregate import OUTPUT_COLUMNS, build_record, build_skipped_record
from .fetch import Fetcher
from .models import Target
from .resolve import load_targets
from .sources import acquire


def _write_raw(raw_dir: Path, target, acquired) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "domain": target.domain,
        "url": target.url,
        "status": acquired.status,
        "source_used": acquired.source_used,
        "products": [asdict(p) for p in acquired.products],
        "pages": [{"url": p.url, "text": p.text} for p in acquired.pages],
        "source_rows": target.rows,
    }
    (raw_dir / f"{target.domain}.json").write_text(json.dumps(payload, indent=1))


def _write_report(out_dir: Path, records: list[dict], target_count: int) -> None:
    statuses = Counter(r["scrape_status"] for r in records)
    js_required = [r["domain"] for r in records if r["scrape_status"] == "js_required"]
    no_products = [r["domain"] for r in records if r["scrape_status"] == "no_products"]
    errors = [
        (r["domain"], r["scrape_status"])
        for r in records
        if r["scrape_status"] in ("error", "blocked")
    ]
    with_knits = sum(1 for r in records if r["knit_count"] > 0)  # always an int here

    lines = [
        "# Scrape Run Report",
        "",
        f"- Total input rows: {len(records)}",
        f"- Stores fetched: {target_count}",
        f"- Stores showing knitwear: {with_knits}",
        "",
        "## Status counts",
        "",
    ]
    lines += [f"- `{status}`: {count}" for status, count in statuses.most_common()]
    lines += ["", "## Needs a headless browser (js_required)", ""]
    lines += [f"- {d}" for d in js_required] or ["- none"]
    lines += ["", "## Readable, but no catalogue found (no_products)", ""]
    lines += [f"- {d}" for d in no_products] or ["- none"]
    lines += ["", "## Errors and blocks", ""]
    lines += [f"- {d}: {s}" for d, s in errors] or ["- none"]
    (out_dir / "run-report.md").write_text("\n".join(lines) + "\n")


def run(input_csv: str, out_dir: str, raw_dir: str, fetcher=None) -> list[dict]:
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    raw_path = Path(raw_dir)

    targets, skipped = load_targets(input_csv)
    fetcher = fetcher or Fetcher(cache_dir=Path(out_dir).parent / ".cache")

    records: list[dict] = []
    for i, target in enumerate(targets, 1):
        print(f"[{i}/{len(targets)}] {target.domain}", flush=True)
        acquired = acquire(target, fetcher)
        _write_raw(raw_path, target, acquired)
        # One output row per original CSV row, even when several collapsed
        # into a single scraped domain (e.g. www. and non-www. duplicates).
        for row in target.rows:
            per_row = Target(domain=target.domain, url=target.url, rows=[row])
            records.append(build_record(per_row, acquired))
    for row, reason in skipped:
        records.append(build_skipped_record(row, reason))

    csv_name = Path(input_csv).stem + "-enriched.csv"
    with open(out_path / csv_name, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=OUTPUT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)

    _write_report(out_path, records, len(targets))
    print(f"\nWrote {len(records)} rows to {out_path / csv_name}")
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape prospect store websites.")
    parser.add_argument("input_csv", help="CSV with a 'website' column")
    parser.add_argument("--out", default="data/out", help="output directory")
    parser.add_argument("--raw", default="data/raw", help="raw JSON directory")
    args = parser.parse_args()
    run(args.input_csv, args.out, args.raw)


if __name__ == "__main__":
    main()

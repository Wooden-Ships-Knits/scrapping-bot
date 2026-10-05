# 0006 — Tidy tables, many output writers, no HTML

**Date:** 2026-10-05
**Status:** Accepted

## Context

The operator wants output in every useful format, not only CSV, so the data can be
analysed in Excel, Google Sheets, DuckDB, pandas or BI tools. The later analysis
(competitor or partner?) needs products, vendors, pages and contacts at their own
grain. HTML is not needed.

## Decision

- Each run produces **seven tidy tables**: `runs`, `inputs`, `stores`, `products`,
  `pages`, `contacts`, `changes`. They share `run_id` and `domain` as join keys.
- The **canonical store** for a run is one JSONL file per table under
  `data/runs/<run_id>/`. JSONL is appended record by record, so a stopped run resumes
  and a crash loses at most one record.
- At the end of the run, **writers** turn the canonical tables into the formats the
  operator chose: JSON, JSONL, CSV, TSV, Excel (one sheet per table), Parquet, SQLite,
  DuckDB, Google Sheets and PostgreSQL. Adding a format means adding one writer.
- Writers never overwrite or delete earlier data. Google Sheets gets a new tab per
  run; PostgreSQL rows are appended with `run_id`.
- **HTML is never stored or exported.** Pages keep their extracted text. Products keep
  the full source object (`raw`) from the feed, structured data or captured JSON.
- Change detection compares a run's canonical tables with the previous run's.

## Rejected alternatives

- **One wide CSV row per store** (v1). Products, pages and contacts lose their own
  rows, which the analysis needs.
- **A database as the only store.** Requires a running server for every run. A
  database is one writer among several instead.
- **Keeping HTML.** Large and not needed for analysis. The trade-off: re-parsing a page
  with a new extractor later requires fetching it again.

## Consequences

- Flat formats (CSV, TSV, Excel) store nested fields such as `raw` and `tags` as JSON
  text.
- Excel has a limit of 1,048,576 rows per sheet. The Excel writer warns and splits
  across sheets when a table is larger.
- Google Sheets API quotas apply, so large runs should use Parquet or DuckDB.
- Every writer gets a round-trip test: the same tables in, the same rows out.

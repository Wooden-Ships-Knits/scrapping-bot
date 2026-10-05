# Roadmap

**Updated:** 2026-10-05
**Requirements:** [PRD](../product/prd.md) · **Design:** [Architecture](../architecture/overview.md)

## Where we are

v1 is built and in use for one US city list. For Shopify stores it answers the
question exactly and for free.

The recon run on 2026-08-12 covered 67 store domains in Naples, FL:

| Finding | Count |
|---|---|
| Shopify stores with an open `/products.json` feed | 26 |
| Products retrieved from those feeds, with prices | 6,167 |
| Non-Shopify sites (custom, Wix, WooCommerce, BigCommerce, Squarespace) | 41 |
| Homepage failures: HTTP 403 | 3 (H&M, Macy's, Four Seasons: national chains, not prospects) |
| Homepage failures: broken TLS certificate | 2 |

**No real prospect was lost to bot detection.** The gap is coverage: most non-Shopify
boutiques publish no machine-readable product data, and v1 reads only JSON-LD.

## Known v1 issues

| # | Issue | Where | Effect | Fixed in |
|---|---|---|---|---|
| 1 | Failed fetches (timeouts, 429, 5xx) are cached | `fetch.py`, `get()` | A re-run never retries a temporary failure unless `data/.cache` is deleted | M0 |
| 2 | Sites with no JSON-LD get `ok` with 0 products | `sources.py`, end of `acquire()` | An unreadable catalogue looks like "no knitwear" | M0 |
| 3 | Prices have no currency | `models.Product` | A localised price enters the data silently | M0 |
| 4 | v1 design gaps: OpenGraph price, depth-2 crawl, link-text ranking, parallel domains | `sources.py`, `extract.py` | Lower coverage than designed | M2 |
| 5 | Phone regex matches US formats only | `extract.py` | No phones outside the US | M5 |
| 6 | Only 5,000 characters of text kept per page | `cli.py`, `_write_raw()` | Later analysis sees truncated pages | M0 |

## Milestones

Each milestone ends with a LIMIT run on 2 real stores, then a full run, then a check of
the actual output. A later milestone starts only when the gate is met.

| Milestone | Work | Gate |
|---|---|---|
| **M0. Foundation** | Fix issues 1–3 and 6. Data model with seven tables. Input adapters (text and files). Writers: JSON, JSONL, CSV, TSV, Excel, Parquet, SQLite, DuckDB. LIMIT mode. Reconciliation in the report. Move to `pyproject.toml` + `uv` | All tests pass; the v1 city list gives equivalent data in every format |
| **M1. Survey and benchmark** | Read-only run over the non-Shopify stores; record which stage would succeed. Gold set of 20 sites checked by hand. Benchmark LLM providers and extraction libraries (instructor, ScrapeGraphAI, Crawl4AI) | Coverage matrix and benchmark reviewed; decides M4 |
| **M2. Non-Shopify acquisition** | WooCommerce and Squarespace feeds (Lightspeed if confirmed), `extruct` and app state, product sitemaps, depth-2 crawl, parallel domains, challenge detection | Non-Shopify coverage re-measured against the PRD target |
| **M3. LLM and interface** | LiteLLM + instructor gateway with all listed providers, evidence rule, budget, fallback. TypeScript web app (React + Vite) over a local FastAPI service, with test mode, progress and downloads | A non-technical operator completes the main scenario unaided |
| **M4. Browser render** (gated) | Per-page content check, Camoufox, XHR capture, region-based browser locale | **Only if** M1 finds at least 5 stores that only a browser can read |
| **M5. Global and changes** | Region settings for any country, phone parsing per region, page language detection, Google Sheets input and writer, PostgreSQL writer, change detection | A two-country list and a second run produce a `changes` table |
| **M6. Release and handover** | Full run on a real list. Five handover documents in `docs/operations/`. `CHANGELOG.md`, version 2.0.0 | All absolute PRD metrics met; the team runs one list on its own |

**Change from the earlier plan:** the LLM stage is no longer gated. The operator wants
every listed provider available, and bulk lists from any region are likely to contain
more stores without structured data. The browser stage stays gated.

## Next phase (separate PRD)

**Competitor or partner analysis.** Classify each store from the raw data: own-brand
seller (competitor) or multi-brand retailer (potential partner), knitwear share, price
fit, wholesale openness. Rules first, LLM for unclear cases, a confidence field and a
human checkpoint on every label. Reach-out comes after that.

## Not planned

- Defeating anti-bot protection, logging in, or reading non-public pages. See
  [ADR 0002](../decisions/0002-camoufox-for-rendering-only.md).
- Storing or exporting HTML. See [ADR 0006](../decisions/0006-tidy-tables-multiformat-writers.md).
- A multi-user web product with accounts. See [ADR 0007](../decisions/0007-typescript-web-ui-local-api.md).

# Roadmap

**Updated:** 2026-10-09
**Requirements:** [PRD](../product/prd.md) · **Design:** [Architecture](../architecture/overview.md)

## Where we are

**The final list is built** (branch `feat/final-knitwear-list`,
[ADR 0010](../decisions/0010-final-list-multi-brand-knitwear.md)): every run ends with
the multi-brand stores that sell knitwear and their knitwear products, beside the raw
tables, and the LLM is on by default (`openai/gpt-4o-mini`, US$1 per run) to read
custom sites and judge unclear store types. On the 808 stores of the 2026-10-08 run
the vendor rule alone settled 176 of 267 readable stores as multi-brand, and 171 of
them sell knitwear (21,156 knitwear products). Across all stores the strict rule finds
24,643 knitwear products where the broad flag finds 45,108.

**M0 (foundation) is built** on branch `feat/m0-foundation`: bulk input in any format,
seven tables, eight writers, test mode, reconciled report, and v1 issues 1, 2, 3 and 6
fixed. Its gate is half met: all tests pass and LIMIT runs on five real Naples stores
were checked by reading the output; the full v1 city list still has to be run (the
list is not in the repo).

**The web interface is built** (branch `feat/web-ui`), pulled forward from M3 at the
operator's request so the team can run lists without a terminal. It covers every M0
capability; LLM settings join it in M3. Verified offline by an end-to-end suite and on
real Naples stores through the real interface.

**Store discovery is built** (branch `feat/store-discovery`,
[ADR 0008](../decisions/0008-store-discovery-paid-search.md)): `scrapebot discover`
finds knitwear stores through Google Places, Tavily and an LLM with web search, and
writes the links file a run reads. It replaces the separate knitwear store finder;
the finder's labelling and scraper were not carried over. Every product is now flagged
`is_knitwear`. The web app finds stores too (count, region, items; one click finds and starts a test
run). Run for real on 2026-10-07 with the agent alone (`openai/gpt-5-search-api`): 5
stores asked, 14 found for US$0.07, test run read 2 stores and 2,031 products. Google
Places and Tavily have not run for real yet (no keys).

**Traffic on our own store is built** (branch `feat/own-store-traffic`,
[ADR 0009](../decisions/0009-own-store-traffic-from-shopify-analytics.md)): the web
app's *Traffic toko* page shows live sessions on our Shopify store from Shopify
Analytics and marks likely bots. Checked against the real store on 2026-10-08 (3,722
sessions in 24 hours, 254 from Council Bluffs with no cart addition). Scrapers reading
`/products.json` stay invisible; that needs a proxy in front of the store.

v1 answered the question exactly and for free for Shopify stores.

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

## Known issues

| # | Issue | Where | Effect | Fixed in |
|---|---|---|---|---|
| 1 | ~~Failed fetches (timeouts, 429, 5xx) are cached~~ | `fetch.py` | ~~A re-run never retries a temporary failure~~ | M0 ✓ |
| 2 | ~~Sites with no JSON-LD get `ok` with 0 products~~ | `acquire/` | ~~An unreadable catalogue looks like "no knitwear"~~; now `no_products` | M0 ✓ |
| 3 | ~~Prices have no currency~~ | `models.Product` | ~~A localised price enters the data silently~~ | M0 ✓ |
| 4 | v1 design gaps: OpenGraph price, depth-2 crawl, link-text ranking, parallel domains | `acquire/`, `extract/` | Lower coverage than designed | M2 |
| 5 | Phone regex matches US formats only | `extract/contacts.py` | No phones outside the US | M5 |
| 6 | ~~Only 5,000 characters of text kept per page~~ | `pages` table | ~~Later analysis sees truncated pages~~ | M0 ✓ |
| 7 | ~~For Shopify stores only the homepage (and input deep links) is fetched~~ | `acquire/__init__.py` | ~~Contacts, about and wholesale pages of feed stores are missed~~; priority pages are fetched feed or not (`39ae657`) | M2 ✓ |
| 8 | Pages that fail to load are not recorded, only the stage in `layers_tried` | `acquire/discovery.py` | A broken contact or deep link is invisible in the output | M2 |
| 9 | Export loads every table of a run into memory | `pipeline.py`, `store.py` | Fine for hundreds of stores; a 1,000-link run with long pages may need streaming writers | M2 |
| 10 | Plain `logging` instead of `structlog`; config has no environment overrides | `cli.py`, `config.py` | Standards sections 4 and 7 not yet met; nothing needs secrets before M3 | M3 |
| 11 | ~~A running run cannot be stopped from the interface, and an interrupted run cannot resume~~ | `api/manager.py`, `pipeline.py` | ~~Stopping the server is the only way to stop~~ | M2 ✓ |
| 12 | Shopify's shared edge (23.227.38.x) limits a client IP across all stores: after a burst on 2026-10-05 it answered every Python request with a 429 challenge for a while, while curl still got 200 | `fetch.py` | Shopify stores turn `blocked` until the limit lapses. Mitigated by per-network politeness (one request at a time to 23.227.38.0/24) and the cache; never worked around (ADR 0002). Run large lists in batches | M2 (mitigated) |
| 13 | Discovery has not run against the real Google Places, Tavily or LLM web search APIs | `discover/` | A request format the providers reject shows up only in a real discovery, as an `error` source in the summary | First real discovery |
| 14 | ~~Discovery is CLI only~~ | `cli.py` | ~~Operators without a terminal cannot search for stores~~; the web app has a *Cari toko otomatis* tab | Built 2026-10-07 |
| 15 | Cloudflare puts `/cdn-cgi/challenge-platform/` into ordinary pages; any page under 60,000 characters that holds it is read as a challenge | `fetch.py` `detect_challenge` | Small stores behind Cloudflare turn `blocked` though they answer 200 with their page (shopluxboutique.com, panachenaples.com, shadyandkatie.com on 2026-10-09) | Next |
| 16 | A rate limit on our IP and a store's own block share the status `blocked` | `fetch.py`, Detection page | 306 of 376 `blocked` stores on 2026-10-08 were Shopify stores behind 23.227.38.x, in waves, and opened normally the next day; the Detection page tells the operator to drop them | Next |
| 17 | The HTTP cache never expires | `fetch.py` | A monthly rerun reads last month's pages, so change detection (M5) would see no change | Before M5 |

## Milestones

Each milestone ends with a LIMIT run on 2 real stores, then a full run, then a check of
the actual output. A later milestone starts only when the gate is met.

| Milestone | Work | Gate |
|---|---|---|
| **M0. Foundation** ✓ built | Fix issues 1–3 and 6. Data model with seven tables. Input adapters (text and files). Writers: JSON, JSONL, CSV, TSV, Excel, Parquet, SQLite, DuckDB. LIMIT mode. Reconciliation in the report. Move to `pyproject.toml` + `uv` | All tests pass ✓; the v1 city list gives equivalent data in every format (pending: run the full list) |
| **M1. Survey and benchmark** | Read-only run over the non-Shopify stores; record which stage would succeed. Gold set of 20 sites checked by hand. Benchmark LLM providers and extraction libraries (instructor, ScrapeGraphAI, Crawl4AI) | Coverage matrix and benchmark reviewed; decides M4 |
| **M2. Non-Shopify acquisition** | WooCommerce and Squarespace feeds (Lightspeed if confirmed), `extruct` and app state, product sitemaps, depth-2 crawl, parallel domains, challenge detection | Non-Shopify coverage re-measured against the PRD target |
| **M3. LLM and interface** | LiteLLM + instructor gateway with all listed providers, evidence rule, budget, fallback. ~~TypeScript web app over a local FastAPI service, with test mode, progress and downloads~~ ✓ built early; M3 adds the LLM settings (provider, model, key, budget) to it | A non-technical operator completes the main scenario unaided |
| **M4. Browser render** ✓ built (ungated by the operator, 2026-10-06) | Per-page content check, Camoufox, XHR capture. Region-based browser locale moves to M5 | JavaScript-only stores read in a real run |
| **M5. Global and changes** | Region settings for any country, phone parsing per region, page language detection, Google Sheets input and writer, PostgreSQL writer, change detection | A two-country list and a second run produce a `changes` table |
| **M6. Release and handover** | Full run on a real list. Five handover documents in `docs/operations/`. `CHANGELOG.md`, version 2.0.0 | All absolute PRD metrics met; the team runs one list on its own |

**Change from the earlier plan:** the LLM stage is no longer gated. The operator wants
every listed provider available, and bulk lists from any region are likely to contain
more stores without structured data.

**Change on 2026-10-06:** the browser stage is no longer gated either. The operator
wants JavaScript-only stores read now rather than after the survey. ADR 0002 still
holds: the browser renders, it does not get past challenges.

## Next phase (separate PRD)

**Competitor or partner analysis.** It also decides how the customer list (accounts,
territories, sales) is matched to found stores, which discovery leaves out. Classify
each store from the raw data: own-brand
seller (competitor) or multi-brand retailer (potential partner), knitwear share, price
fit, wholesale openness. Rules first, LLM for unclear cases, a confidence field and a
human checkpoint on every label. Reach-out comes after that.

## Not planned

- Defeating anti-bot protection, logging in, or reading non-public pages. See
  [ADR 0002](../decisions/0002-camoufox-for-rendering-only.md).
- Storing or exporting HTML. See [ADR 0006](../decisions/0006-tidy-tables-multiformat-writers.md).
- A multi-user web product with accounts. See [ADR 0007](../decisions/0007-typescript-web-ui-local-api.md).

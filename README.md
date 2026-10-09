# Store Website Scraper

Finds stores that sell knitwear, then collects evidence about them from their
websites: what they sell (especially knitwear, with prices) and how to contact them.
Built for qualifying wholesale accounts for a knit sweater brand.

The bot **collects evidence only**. It does not judge whether a store is a good
prospect — that is a human decision made against the collected data. That split is
deliberate: it keeps the fragile part (network, unpredictable site layouts) separate
from the judgment part, and lets you re-judge without re-scraping.

## Status

**v2 milestone M0 (foundation) and the web interface are built.** Bulk links in any
format, seven tidy tables, eight output formats, test mode, a reconciled run report,
and a local web interface for all of it. Shopify stores
are read exactly through their product feed; other sites through JSON-LD only, until
M2 adds more ways to read them.

**Every run ends with a final list:** the multi-brand stores that sell knitwear and
their knitwear products (`export/final/`, *Daftar final* in the web app;
[ADR 0010](docs/decisions/0010-final-list-multi-brand-knitwear.md)).

**Still to come:** region settings, Google Sheets and PostgreSQL output, and change detection.
See the [PRD](docs/product/prd.md), the [architecture](docs/architecture/overview.md)
and the [roadmap](docs/planning/roadmap.md). Everything below describes what runs today unless
it says *planned*.

## Setup

Needs [uv](https://docs.astral.sh/uv/) and [pnpm](https://pnpm.io)
(`brew install uv pnpm`) and Node 22+. uv installs the right Python version itself.

```bash
make install        # Python + web dependencies, Camoufox, test browser, git hooks
```

## Interface

```bash
make serve          # builds the web app, starts it on http://127.0.0.1:8765 and opens it
```

Paste links or upload a file, check the preview, pick the output formats, and press
**Mulai scrape**: every store in the list is visited. Watch the run page as it fills
(the reconciliation must say *seimbang*, the stores you know have a catalogue must
show *Ada produk*); **Hentikan** stops it if something looks wrong, and **Lanjutkan**
picks it up later without revisiting finished stores. Progress updates live;
closing the browser does not stop a run, and **Riwayat** lists every run with its
downloads. **Deteksi** shows how often stores detect and block the bot, across every
run: the share of visits blocked, how (Cloudflare, Akamai, HTTP 403…), and which stores
always block, so they can be left out of the next list. The interface is local only
(127.0.0.1) and in Indonesian.

## Finding stores

**In the interface**, the *Cari toko otomatis* tab of the Scrape page does it in one
click: type how many stores, pick a region or continent, tick the items (knitwear,
cashmere/wool, fall/winter, spring/summer, or *Lainnya* with your own words) and press
**Cari toko & mulai scrape**. It finds the stores, then scrapes all of them and opens
the run page. The tab is the default when `.env` has at least one search key. To try a
few stores first, use the command line: `scrapebot run <input> --limit 2`.

**From the command line**, `scrapebot discover` finds knitwear stores and writes them as
a links file for a run ([ADR 0008](docs/decisions/0008-store-discovery-paid-search.md)):

```bash
cp discover.example.yaml data/my-discover.yaml        # edit places, queries, brands
uv run scrapebot discover -c data/my-discover.yaml    # all sources that have a key
uv run scrapebot discover -c data/my-discover.yaml --only web_search,resolve
uv run scrapebot run data/discover/<id>/stores.csv --limit 2   # then scrape them
```

| Source | Key in `.env` | Good at |
|---|---|---|
| `google_places` | `GOOGLE_MAPS_API_KEY` (Places API (New)) | Physical shops: name, address, phone, usually the website |
| `web_search` | `TAVILY_API_KEY` | Online stores; retailers of the `brands` you list |
| `social_search` | `TAVILY_API_KEY` | Boutiques known mainly by an Instagram or Facebook profile, read from search results only |
| `ai_agent` | the key of `ai_agent.model`'s provider, e.g. `GEMINI_API_KEY` | Reading "best boutiques in ..." articles; one run per area |
| `resolve` | `TAVILY_API_KEY` | The website of a store found only by name or profile |

A source without its key is skipped; the others run. Every source is **paid per
request**, so each has a hard cap in the config, the agent a cost cap, and every
successful answer is cached in `data/.cache/discover`: repeating a discovery costs
nothing. Start with two or three places and `ai_agent.max_runs: 1`.

The output, `data/discover/<id>/`, holds `stores.csv` (one row per store, `website`
first, then name, address, phone, profiles, which sources and searches found it),
`stores.json` (every location and note) and `report.json` (per source: status, stores,
paid and cached requests, cost). Discovery never opens a store's website: what a store
sells is read by the run.

## Command line

```bash
uv run scrapebot run data/prospects.xlsx --limit 2      # test mode: first 2 stores
uv run scrapebot run data/prospects.xlsx -f xlsx,parquet # full run, chosen formats
pbpaste | uv run scrapebot run -                         # links pasted as free text
uv run scrapebot run -c config.example.yaml              # settings from a file
```

**Input** can be pasted text (links in any sentence) or a `.txt`, `.csv`, `.tsv`,
`.xlsx`, `.json`, `.jsonl` or `.parquet` file. In a table, the column holding the
links is found automatically (or name it with `--url-column`), and every column is
kept untouched as metadata. Links on the same domain are visited once; a product or
page link is fetched as a priority page. Social profiles, marketplaces (Etsy, Amazon,
...), empty and broken links are skipped with a reason, never dropped silently.

**Always start with `--limit 2`**, read the output, then run the full list.

| Option | Default | |
|---|---|---|
| `-l, --limit N` | full run | Test mode: visit only the first N stores |
| `-f, --format` | `xlsx,csv` | Any of `json,jsonl,csv,tsv,xlsx,parquet,sqlite,duckdb` |
| `-c, --config` | none | YAML settings; see `config.example.yaml`. Flags override it |
| `--url-column` | auto | Column holding the links |
| `--max-links` | 1000 | Inputs with more links are refused before anything is fetched |
| `--runs-dir` | `data/runs` | Where run folders go |

Input lists are not in the repo: everything in `data/` is gitignored because those
files hold prospect and account records. Supply your own.

## How it gets the data

```
links (text or file) → resolve (domain, skip reasons) → fetch homepage
  → site profile (platform, currency) → deep links from the input
  → platform feed ──────────────────────────────────────────┐
  → or: discover pages → URL queue → fetch each page        │
        → no products? → browser render (Camoufox)          │
        → structured extraction → enough? no → LLM*         │
  → products, pages, contacts ←─────────────────────────────┘
  → seven tables (JSONL) → writers → summary + report

* planned or gated: see docs/architecture/overview.md
```

The cheapest and most exact source is tried first, and the run stops at the first
one that yields products:

1. **Platform feed.** Shopify `/products.json` gives titles, prices, tags and
   descriptions for free. It covers ~40% of the prospect list and needs no HTML
   parsing. *Planned:* WooCommerce Store API and Squarespace JSON.
2. **Page discovery.** `sitemap.xml` for non-Shopify sites, or a crawl of the
   homepage's internal links one level deep. About, contact and wholesale pages are
   collected *first*, so a store with thousands of product URLs cannot crowd its own
   contact page out of the 25-page budget.
3. **Structured extraction.** JSON-LD product data on each page. *Planned:*
   Microdata, OpenGraph prices and embedded app state.
4. **Browser render.** For a store still at zero products, Camoufox renders the
   JavaScript-only pages (and a few listing pages) and captures the product JSON they
   load. Same `robots.txt` and delay as HTTP; a challenge page is recorded as
   `blocked`, never bypassed. `--no-render` turns it off.
5. **LLM extraction.** For a store still at zero products, an LLM (any provider
   through LiteLLM; `openai/gpt-4o-mini` by default, US$1 per run) reads the page text
   against a fixed schema. These rows are flagged `needs_review`. On by default; it
   needs `OPENAI_API_KEY` in `.env`, and `--no-llm` turns it off. Without the key the
   run goes on and the report says the LLM was not used.

Then the **final list**: a store qualifies when it resells other brands (three or
more outside brands among its product vendors, or the LLM's judgement when the
vendors are unclear) and sells knitwear by a strict, title-based rule.

Stage 4 is built only if a probe of the non-Shopify sites shows enough stores need
it. No ScrapeGraph library or subscription is used — see
[docs/decisions/](docs/README.md).

## Wholesale analysis

```bash
uv run scrapebot analyze data/runs/<run_id>          # writes data/runs/<run_id>/analysis/
```

Sorts every store of a finished run into **retail partner**, **B2B partner**, **competitor**,
**existing customer**, **not a fit** or **not relevant**, with a 0–100 score for partners and
the reason for every point. Put your own files in `data/inputs/` (gitignored: they hold
customer data):

| File | What | Used for |
|---|---|---|
| `stockists.json` or `.csv` | The store locator's list | Existing stockists, distance to the nearest one |
| `accounts.csv` | A Salesforce account export, as it comes | Existing accounts, their rep and territory |
| `brands.csv` | `brand,relation` with `peer` or `competitor` | Who carries brands like ours; competitors |
| `price_points.csv` | `category,wholesale_usd,retail_usd` | Price fit |

A missing file leaves its columns empty and the analysis README says so. Locations are
geocoded once (OpenStreetMap, about a second each) and cached; `--no-geocode` skips them,
`--territory-miles` sets the conflict radius (15).

## Output

Each run gets its own folder, `data/runs/<run_id>/`, so earlier runs are never
overwritten:

| Path | What |
|---|---|
| `report.md` | Read this first. Reconciliation (links in = processed + skipped), status counts, coverage by source, and the stores that need a look |
| `summary.csv` | One row per input link, original columns first: the qualification view (below) |
| `export/final/` | **The final list**: `final_stores` (multi-brand stores that sell knitwear, with brands, knitwear counts and contacts) and `final_products` (their knitwear), in every format you chose |
| `analysis/` | After `scrapebot analyze`: the **wholesale analysis** (see below) |
| `export/knit/` | **Knitwear only**: every knitwear product of every store that was read, with the store's type and whether it made the final list |
| `export/` | The seven tables in every format you chose |
| `tables/` | The canonical copy of the seven tables (JSONL), from which every export is made |
| `manifest.json` | Config, package versions, durations and counts, for reproducing the run |

**The seven tables** join on `run_id` and `domain`:

| Table | One row per | Highlights |
|---|---|---|
| `runs` | run | config, version, mode |
| `inputs` | input link | link as supplied, status or skip reason, the whole input row in `meta` |
| `stores` | store | `status`, `platform`, `currency` and its source, `layers_tried`, `product_count`, `knit_count`, `focus_count`, `ssl_bypassed` |
| `products` | product | `title`, `price_raw` exactly as the source wrote it, `currency`, `vendor`, `url`, `source`, `evidence_url`, `is_knitwear`, `matched_items` (the items ticked that it matches), full source object in `raw` |
| `pages` | fetched page | `page_kind` (home, about, contact, wholesale, stockist, product, ...), full `text`. Never HTML |
| `contacts` | contact | `email`, `phone`, `instagram`, `facebook`, `tiktok`, `linkedin`, `pinterest`, with the `source_url` it was found on |
| `changes` | change between runs | empty until change detection lands (M5) |

**`summary.csv`** keeps the v1 one-row-per-link view:

| Column | What it tells you |
|---|---|
| `knit_count` | How many products matched knitwear terms |
| `knit_share` | That count as a percentage of the catalogue — the qualification signal |
| `knit_examples` | Up to 5 actual product titles. **This is the evidence** — a count alone tells you nothing |
| `currency` / `currency_mixed` | Currency the store declares (ISO 4217), and whether products use more than one. Empty when the site does not say; a "$" alone is never trusted |
| `emails`, `phone`, `instagram`, `facebook` | Contacts |
| `is_chain` | True for national chains — not wholesale prospects |
| `scrape_status` | Store: `ok` (products found), `no_products` (readable, no catalogue found), `js_required`, `blocked`, `error`. Skipped link: `duplicate`, `over_limit`, `no_website`, `invalid_url`, `social_only`, `marketplace` |
| `ssl_bypassed` | True when the site's TLS certificate is broken and it was read with verification off |
| `source_used` | `shopify_feed`, `sitemap`, or `crawl` |
| `platform` | Detected platform, for example `shopify`, `wix`, `woocommerce` |
| `wholesale_page` | Usually empty for retailers; brands sometimes publish one |
| `about_snippet` | First ~300 chars of their About page |

Prices are exported only as written (`price_raw`): `119,99 €`, `$1,395.00`, `Rp 139.000`.
Reading them into numbers, and converting currencies, is left to the system that
analyses the data. Two sources give minor units: WooCommerce (`price_raw` `22900`, with
`prices.currency_minor_unit` in `raw`) and APIs with a `priceCents`-style key (named
in `raw`).

## Behaviour

Successful responses are cached in `data/.cache`, so re-runs are near-instant.
Failures (timeouts, 429, 5xx) are never cached, so a re-run retries them. Delete the
cache to force fresh fetches.

Every input link is accounted for: the report checks that links in = processed +
skipped. A site that fails is recorded with a status, never dropped — one dead site
cannot abort a run. A writer that fails does not stop the other formats.

The bot respects `robots.txt`, waits 1.5s between requests to the same domain, reads
only public pages, and logs in nowhere. A site that answers 401, 403 or 429 is
recorded as `blocked` and is not bypassed — no CAPTCHA solving, no proxy rotation.
Sites with broken TLS certificates are retried with verification disabled and flagged
`ssl_bypassed`, so the weakened check is visible in the output rather than silent.

## Judging the results

Sort by `knit_share` descending and read `knit_examples`, with `price_raw` in
`products` for their prices. In the exports, filter `products` on `is_knitwear` for the
sweaters alone: every product is kept, knitwear is flagged. High share plus prices near
yours is a strong prospect. Ignore rows where `is_chain` is True.

`knit_count` is deliberately conservative about false positives: a product whose only
knitwear signal is the word "wool" or "shawl" is excluded when its title names a clearly
woven garment (coat, trousers, vest). That keeps wool coats out of the sweater count.

## Development

```bash
make check          # lint, types and tests (Python and web): what CI runs
make e2e            # the interface end to end in a real browser, offline
make dev            # API + Vite with hot reload on http://127.0.0.1:5173
make api-types      # after changing an API model: regenerate the TypeScript types
make fmt            # format and apply safe lint fixes
make help           # every task
```

Needs Node 22+ and pnpm (`brew install pnpm`) for the web app.

All tests run offline against fixtures saved from real prospect sites. No test makes a
network call. How code is written, tested and reviewed is in the
[engineering standards](docs/engineering/standards.md).

## Documentation

- [docs/product/prd.md](docs/product/prd.md) — what v2 does and why
- [docs/architecture/overview.md](docs/architecture/overview.md) — the pipeline, stage by stage
- [docs/engineering/standards.md](docs/engineering/standards.md) — how code is written and tested
- [docs/planning/roadmap.md](docs/planning/roadmap.md) — milestones, gates, known issues
- [docs/README.md](docs/README.md) — index, including design decisions and the archive

# Store Website Scraper

Collects evidence about retail prospects from their websites: what they sell
(especially knitwear, with prices) and how to contact them. Built for qualifying
wholesale accounts for a knit sweater brand.

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

**Still to come:** more ways to read non-Shopify sites, any LLM provider, region settings, Google Sheets and PostgreSQL output, and change detection.
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

Paste links or upload a file, pick the output formats, and press **Jalankan uji**:
test mode visits the first 2 stores. Check the result page (the reconciliation must
say *seimbang*, the stores you know have a catalogue must show *Ada produk*), open the
Excel file, then press **Jalankan seluruh daftar** for the whole list. A full run of a
list that was never tested needs a deliberate confirmation. Progress updates live;
closing the browser does not stop a run, and **Riwayat** lists every run with its
downloads. The interface is local only (127.0.0.1) and in Indonesian.

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
5. **LLM extraction** (*planned*). For a store still at zero products, any LLM
   provider (Gemini, GPT, Claude, Ollama and others, through LiteLLM) reads the page
   text against a fixed schema. These rows are flagged `needs_review`.

Stage 4 is built only if a probe of the non-Shopify sites shows enough stores need
it. No ScrapeGraph library or subscription is used — see
[docs/decisions/](docs/README.md).

## Output

Each run gets its own folder, `data/runs/<run_id>/`, so earlier runs are never
overwritten:

| Path | What |
|---|---|
| `report.md` | Read this first. Reconciliation (links in = processed + skipped), status counts, coverage by source, and the stores that need a look |
| `summary.csv` | One row per input link, original columns first: the qualification view (below) |
| `export/` | The seven tables in every format you chose |
| `tables/` | The canonical copy of the seven tables (JSONL), from which every export is made |
| `manifest.json` | Config, package versions, durations and counts, for reproducing the run |

**The seven tables** join on `run_id` and `domain`:

| Table | One row per | Highlights |
|---|---|---|
| `runs` | run | config, version, mode |
| `inputs` | input link | link as supplied, status or skip reason, the whole input row in `meta` |
| `stores` | store | `status`, `platform`, `currency` and its source, `layers_tried`, `ssl_bypassed` |
| `products` | product | `title`, `price_raw` as found, `price`, `currency`, `vendor`, `url`, `source`, `evidence_url`, full source object in `raw` |
| `pages` | fetched page | `page_kind` (home, about, contact, wholesale, stockist, product, ...), full `text`. Never HTML |
| `contacts` | contact | `email`, `phone`, `instagram`, `facebook`, `tiktok`, `linkedin`, `pinterest`, with the `source_url` it was found on |
| `changes` | change between runs | empty until change detection lands (M5) |

**`summary.csv`** keeps the v1 one-row-per-link view:

| Column | What it tells you |
|---|---|
| `knit_count` | How many products matched knitwear terms |
| `knit_share` | That count as a percentage of the catalogue — the qualification signal |
| `knit_examples` | Up to 5 actual product titles. **This is the evidence** — a count alone tells you nothing |
| `knit_price_min` / `knit_price_max` | The price band of their *sweaters* specifically |
| `price_min` / `price_max` / `price_median` | Store-wide range, for context |
| `currency` / `currency_mixed` | Currency the store declares (ISO 4217), and whether products use more than one. Empty when the site does not say; a "$" alone is never trusted |
| `emails`, `phone`, `instagram`, `facebook` | Contacts |
| `is_chain` | True for national chains — not wholesale prospects |
| `scrape_status` | Store: `ok` (products found), `no_products` (readable, no catalogue found), `js_required`, `blocked`, `error`. Skipped link: `duplicate`, `over_limit`, `no_website`, `invalid_url`, `social_only`, `marketplace` |
| `ssl_bypassed` | True when the site's TLS certificate is broken and it was read with verification off |
| `source_used` | `shopify_feed`, `sitemap`, or `crawl` |
| `platform` | Detected platform, for example `shopify`, `wix`, `woocommerce` |
| `wholesale_page` | Usually empty for retailers; brands sometimes publish one |
| `about_snippet` | First ~300 chars of their About page |

Read `knit_price_min`/`knit_price_max`, not the store-wide range. A boutique spanning
$2–$545 tells you nothing; sweaters at $39–$698 tells you whether your price point fits.

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

Sort by `knit_share` descending and read `knit_examples`. High share plus a price band
overlapping yours is a strong prospect. Ignore rows where `is_chain` is True.

`knit_count` is deliberately conservative about false positives: a product whose only
knitwear signal is the word "wool" or "shawl" is excluded when its title names a clearly
woven garment (coat, trousers, vest). That keeps wool coats out of the sweater price band.

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

- [docs/product/prd.md](docs/product/prd.md) — what v2 does and why (Indonesian)
- [docs/architecture/overview.md](docs/architecture/overview.md) — the pipeline, stage by stage
- [docs/engineering/standards.md](docs/engineering/standards.md) — how code is written and tested
- [docs/planning/roadmap.md](docs/planning/roadmap.md) — milestones, gates, known issues
- [docs/README.md](docs/README.md) — index, including design decisions and the archive

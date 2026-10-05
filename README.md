# Store Website Scraper

Collects evidence about retail prospects from their websites: what they sell
(especially knitwear, with prices) and how to contact them. Built for qualifying
wholesale accounts for a knit sweater brand.

The bot **collects evidence only**. It does not judge whether a store is a good
prospect — that is a human decision made against the collected data. That split is
deliberate: it keeps the fragile part (network, unpredictable site layouts) separate
from the judgment part, and lets you re-judge without re-scraping.

## Status

**v1 is built and in use.** It reads Shopify stores exactly through their product
feed, and other sites through JSON-LD only.

**v2 is in progress.** Bulk links in any format, a local web interface, more ways to
read non-Shopify sites, any LLM provider, region settings, and output in many formats
(Excel, Parquet, JSON, SQLite, DuckDB and more). See the [PRD](docs/product/prd.md),
the [architecture](docs/architecture/overview.md) and the
[roadmap](docs/planning/roadmap.md). Everything below describes what runs today unless
it says *planned*.

## Setup

Needs [uv](https://docs.astral.sh/uv/) (`brew install uv`). uv installs the right
Python version itself.

```bash
make install        # uv sync + git hooks
```

## Run

```bash
uv run scrapebot data/fl-prospects.csv
```

The input CSV needs a `website` column. Every other column is passed through to the
output untouched, so the same command works on a list for any city.

Input lists are not in the repo: everything in `data/` is gitignored because those
files hold prospect and account records. Supply your own.

Options: `--out` (default `data/out`), `--raw` (default `data/raw`).

## How it gets the data

```
input CSV → resolve → fetch homepage → site profile (platform, currency*)
  → platform feed ──────────────────────────────────────────┐
  → or: discover pages → URL queue → fetch each page        │
        → content OK? no → browser render*                  │
        → structured extraction → enough? no → LLM*         │
  → raw products ←──────────────────────────────────────────┘
  → normalise* → validate* → knitwear, prices, contacts → CSV + JSON + report

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
4. **Browser render** (*gated*). Camoufox renders only the pages that come back empty
   or JavaScript-only, and captures the product JSON they load.
5. **LLM extraction** (*planned*). For a store still at zero products, any LLM
   provider (Gemini, GPT, Claude, Ollama and others, through LiteLLM) reads the page
   text against a fixed schema. These rows are flagged `needs_review`.

Stage 4 is built only if a probe of the non-Shopify sites shows enough stores need
it. No ScrapeGraph library or subscription is used — see
[docs/decisions/](docs/README.md).

## Output

**`data/out/<input>-enriched.csv`** — one row per input row, original columns plus:

| Column | What it tells you |
|---|---|
| `knit_count` | How many products matched knitwear terms |
| `knit_share` | That count as a percentage of the catalogue — the qualification signal |
| `knit_examples` | Up to 5 actual product titles. **This is the evidence** — a count alone tells you nothing |
| `knit_price_min` / `knit_price_max` | The price band of their *sweaters* specifically |
| `price_min` / `price_max` / `price_median` | Store-wide range, for context |
| `emails`, `phone`, `instagram`, `facebook` | Contacts |
| `is_chain` | True for national chains — not wholesale prospects |
| `scrape_status` | `ok` (products found), `no_products` (readable, no catalogue found), `js_required`, `blocked`, `error`, `no_website`, `social_only` |
| `ssl_bypassed` | True when the site's TLS certificate is broken and it was read with verification off |
| `source_used` | `shopify_feed`, `sitemap`, or `crawl` |
| `platform` | Detected platform, for example `shopify`, `wix`, `woocommerce` |
| `wholesale_page` | Usually empty for retailers; brands sometimes publish one |
| `about_snippet` | First ~300 chars of their About page |

*Planned* columns: `currency`, `currency_mixed`, `layers_tried`, `needs_review`.

Read `knit_price_min`/`knit_price_max`, not the store-wide range. A boutique spanning
$2–$545 tells you nothing; sweaters at $39–$698 tells you whether your price point fits.

**`data/raw/<domain>.json`** — everything captured: full product list, page text,
all contacts. Re-judging later never requires re-scraping.

**`data/out/run-report.md`** — status counts, plus the list of sites that returned
nothing and would need a headless browser.

## Behaviour

Responses are cached in `data/.cache`, so re-runs are near-instant. Delete that
directory to force a fresh fetch. Failed fetches are currently cached too, so a site
that failed temporarily is only retried after the cache is cleared (*planned fix*).

Every input row always produces an output row. A site that fails is recorded with a
status, never dropped — one dead site cannot abort a 65-site run.

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
make check          # lint, types and tests: the same checks CI runs
make fmt            # format and apply safe lint fixes
make help           # every task
```

All tests run offline against fixtures saved from real prospect sites. No test makes a
network call. How code is written, tested and reviewed is in the
[engineering standards](docs/engineering/standards.md).

## Documentation

- [docs/product/prd.md](docs/product/prd.md) — what v2 does and why (Indonesian)
- [docs/architecture/overview.md](docs/architecture/overview.md) — the pipeline, stage by stage
- [docs/engineering/standards.md](docs/engineering/standards.md) — how code is written and tested
- [docs/planning/roadmap.md](docs/planning/roadmap.md) — milestones, gates, known issues
- [docs/README.md](docs/README.md) — index, including design decisions and the archive

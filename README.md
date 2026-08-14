# Store Website Scraper

Collects evidence about retail prospects from their websites: what they sell
(especially knitwear, with prices) and how to contact them. Built for qualifying
wholesale accounts for a knit sweater brand.

The bot **collects evidence only**. It does not judge whether a store is a good
prospect — that is a human decision made against the collected data. That split is
deliberate: it keeps the fragile part (network, unpredictable site layouts) separate
from the judgment part, and lets you re-judge without re-scraping.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Run

```bash
PYTHONPATH=src .venv/bin/python -m scrapebot data/fl-prospects.csv
```

The input CSV needs a `website` column. Every other column is passed through to the
output untouched, so the same command works on a list for any city.

Input lists are not in the repo — `data/*.csv` is gitignored because those files hold
prospect and account records. Supply your own.

Options: `--out` (default `data/out`), `--raw` (default `data/raw`).

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
| `scrape_status` | `ok`, `js_required`, `blocked`, `ssl_bypassed`, `no_website`, `social_only`, `error` |
| `source_used` | `shopify_feed`, `sitemap`, or `crawl` |
| `wholesale_page` | Usually empty for retailers; brands sometimes publish one |
| `about_snippet` | First ~300 chars of their About page |

Read `knit_price_min`/`knit_price_max`, not the store-wide range. A boutique spanning
$2–$545 tells you nothing; sweaters at $39–$698 tells you whether your price point fits.

**`data/raw/<domain>.json`** — everything captured: full product list, page text,
all contacts. Re-judging later never requires re-scraping.

**`data/out/run-report.md`** — status counts, plus the list of sites that returned
nothing and would need a headless browser.

## How it gets the data

Three strategies, tried in order, stopping at the first that yields products:

1. **Shopify `/products.json`** — a free, structured feed with titles, prices, tags and
   descriptions. Covers ~40% of the prospect list and needs no HTML parsing at all.
2. **`sitemap.xml`** — for non-Shopify sites, to find product/about/contact pages
   directly. Contact and about pages are collected *first*, so a store with thousands
   of product URLs cannot crowd its own contact page out of the page budget.
3. **Crawl** — homepage, then prioritised internal links, one level deep.

## Behaviour

Responses are cached in `data/.cache`, so re-runs are near-instant. Delete that
directory to force a fresh fetch.

Every input row always produces an output row. A site that fails is recorded with a
status, never dropped — one dead site cannot abort a 65-site run.

The bot respects `robots.txt`, waits 1.5s between requests to the same domain, reads
only public pages, and logs in nowhere. Sites with broken TLS certificates are retried
with verification disabled and flagged `ssl_bypassed`, so the weakened check is visible
in the output rather than silent.

## Judging the results

Sort by `knit_share` descending and read `knit_examples`. High share plus a price band
overlapping yours is a strong prospect. Ignore rows where `is_chain` is True.

`knit_count` is deliberately conservative about false positives: a product whose only
knitwear signal is the word "wool" or "shawl" is excluded when its title names a clearly
woven garment (coat, trousers, vest). That keeps wool coats out of the sweater price band.

## Tests

```bash
.venv/bin/pytest
```

All tests run offline against fixtures saved from real prospect sites. No test makes a
network call.

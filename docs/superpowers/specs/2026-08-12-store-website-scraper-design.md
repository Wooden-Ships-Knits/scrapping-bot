# Store Website Scraper — Design

**Date:** 2026-08-12
**Status:** Approved
**Project:** `/Users/webadmin/Automation/scrapping-bot`

## Purpose

We sell and manufacture knit sweaters. We have a Google Maps–sourced list of retail
prospects and need to know, for each one, two things:

1. **Do they sell knitwear, and at what price point?** — the qualify/disqualify signal.
2. **How do we contact them?** — email, phone, socials, wholesale/trade page.

The bot **collects evidence only**. It does not decide whether a store is a good
prospect. Judging happens later, by a human or a separate tool, against the collected
evidence. This split is deliberate: it keeps the fragile part (network, unpredictable
site layouts) separate from the judgment part, and lets us re-judge without re-scraping.

## Input

`data/fl-prospects.csv` — 78 rows, all in Naples FL.

| Property | Count |
|---|---|
| Total rows | 78 |
| With a website | 69 |
| No website | 9 |
| Instagram-only (no real site) | 2 |
| Real websites | 67 |
| Distinct hostnames | 67 |
| Distinct stores after collapsing `www.`/non-`www.` | 65 |

Duplicate hostnames to collapse: `saracampbell.com`, `backofthebayboutique.com`.

Existing columns are passed through untouched: `store_name`, `latitude`, `longitude`,
`website`, `potential_conflict`, `nearest_stockist`, `drive_minutes`, `distance_miles`,
`address`, `found_near`, `types`, `place_id`.

## Reconnaissance findings

A probe of all 67 domains on 2026-08-12 established the following, and these numbers
drive the architecture:

| Finding | Count |
|---|---|
| Shopify stores exposing an open `/products.json` feed | 26 |
| Products retrieved from those feeds, with prices | 6,167 |
| Of those stores showing knitwear keyword hits | 24 |
| Requiring HTML scraping (custom, Wix, WooCommerce, BigCommerce, Squarespace) | 41 |
| — of which the homepage fetch currently fails | 5 |

The 5 failures: `www2.hm.com`, `www.macys.com`, `www.fourseasons.com` (all HTTP 403,
and all national chains that are not wholesale prospects), plus
`designerconsignornaples.com` and `www.shoprcouncil.com` (TLS handshake failure).

Two Shopify-fingerprinted domains returned no feed: `www.jmclaughlin.com`,
`www.yesirosefashion.com`. These fall through to the HTML path.

**Consequence:** roughly 40% of the list needs no HTML parsing at all. The Shopify feed
is the primary acquisition path, not a special case.

## Architecture

A four-stage pipeline processing one store at a time. Each stage has a single
responsibility, a defined input and output, and is testable in isolation.

```
CSV in ──▶ [1] RESOLVE ──▶ [2] ACQUIRE ──▶ [3] EXTRACT ──▶ [4] EMIT ──▶ CSV + JSON out
```

### [1] Resolve — `resolve.py`

Turns CSV rows into a deduplicated work list.

- Normalise URLs: force scheme, strip trailing slash, lowercase host.
- Canonicalise host by stripping a leading `www.`; collapse rows sharing a canonical host.
- Partition rows that need no fetching: blank website → `no_website`;
  Instagram/Facebook URL → `social_only`.

**Output:** list of `Target{canonical_domain, url, source_rows[]}`.

### [2] Acquire — `fetch.py`, `sources.py`

`fetch.py` is the only module that touches the network. It provides one function that
returns `(status, body, final_url)` and never raises for network conditions.

- Disk cache keyed by URL hash, so re-runs are instant and iteration is cheap.
- `robots.txt` fetched once per domain and respected.
- ~1.5s delay between requests to the same domain; 5 domains in parallel.
- 20s timeout; 2 retries with exponential backoff.
- Browser-like `User-Agent`.

`sources.py` tries three acquisition strategies **in order, stopping at the first that
yields product data**:

1. **Shopify feed** — `GET /products.json?limit=250&page=N`, paginating until a page
   returns zero products or a page cap of 8 (2,000 products) is reached. Yields
   structured title, `product_type`, tags, `body_html`, and variant prices.
2. **Sitemap** — `GET /sitemap.xml`, following sitemap-index files one level. Select
   URLs matching `product|collection|shop|about|contact|wholesale|stockist`, capped at 25.
3. **Crawl** — fetch homepage, extract internal links, prioritise those whose href or
   anchor text matches `shop|collection|product|about|contact|brands|wholesale|stockist`.
   Depth 2, max 25 pages per site.

**Output:** `Acquired{source_used, pages[], products[], platform}`.

### [3] Extract — `extract.py`

Pure functions over acquired content. No network access, which makes this the
heavily-tested module.

- **Products** — from the Shopify feed directly; from HTML via JSON-LD
  `schema.org/Product` blocks, then `og:`/`product:price:amount` meta tags, then
  price-pattern text extraction as a last resort.
- **Knit matching** — case-insensitive word-boundary match on:
  `knit, knitwear, sweater, cardigan, pullover, jumper, cashmere, merino, wool,
  crewneck, turtleneck, sweatshirt, poncho, shawl`.
  Matched against title, product type, tags, and the first 400 chars of description.
  **Every match retains its source product title.** A bare count is not evidence.
- **Contacts** — `mailto:` links, then email regex over page text; `tel:` links and
  phone regex; Instagram and Facebook profile URLs.
- **Wholesale page** — URL of any page whose path or link text matches
  `wholesale|stockist|trade|retailer|become-a`.
- **About snippet** — first ~300 chars of the About page, else the meta description.
- **Platform fingerprint** — Shopify, Squarespace, Wix, WooCommerce, BigCommerce,
  other e-commerce, or custom/unknown, from HTML markers.
- **Chain detection** — flags national chains against a small known-chain list
  (H&M, Macy's, Charlotte Russe, Windsor, Bealls, Brandy Melville, Four Seasons)
  plus a heuristic: a store-locator link listing many locations.

### [4] Emit — `aggregate.py`, `cli.py`

Rolls each store's extracted data into one record and writes three artefacts.

**`data/out/<input-name>-enriched.csv`** — original columns plus:

| Column | Meaning |
|---|---|
| `domain` | canonical, deduplicated |
| `scrape_status` | `ok`, `js_required`, `blocked`, `ssl_bypassed`, `no_website`, `social_only`, `error` |
| `source_used` | `shopify_feed`, `sitemap`, `crawl` |
| `platform` | detected platform |
| `is_chain` | True/False |
| `pages_fetched` | count |
| `product_count` | products found |
| `knit_count` | products matching knit terms |
| `knit_share` | `knit_count / product_count`, as a percentage |
| `knit_examples` | up to 5 matching product titles, `; ` joined |
| `knit_price_min`, `knit_price_max` | price band of knit items specifically |
| `price_min`, `price_max`, `price_median` | store-wide range |
| `emails`, `phone`, `instagram`, `facebook` | contacts, `; ` joined |
| `wholesale_page` | URL, if found |
| `about_snippet` | text |
| `fetched_at` | ISO 8601 timestamp |

`knit_price_min`/`knit_price_max` are the primary price signal. A store-wide range of
$2–$545 says nothing useful; sweaters at $39–$698 says exactly whether our price point fits.

**`data/raw/<domain>.json`** — everything captured: full product list, page URLs and
text, all contacts, all knit matches with context, timestamps. Nothing is discarded,
so later re-judging never requires re-scraping.

**`data/out/run-report.md`** — counts by status, the list of `js_required` domains,
the list of errors with reasons, and total runtime.

## Error handling

**The governing rule: every input store produces an output row, always.** A single
failing site never aborts the run and never silently vanishes from the output.

| Condition | Handling |
|---|---|
| Blank website | `no_website`, no fetch attempted |
| Instagram/Facebook only | `social_only`, no fetch attempted |
| HTTP 403 / 429 | `blocked`; combined with `is_chain=True` this is an expected, acceptable outcome |
| TLS handshake failure | one retry with certificate verification disabled, recorded as `ssl_bypassed` so the weakened check is visible in the output, never silent |
| Timeout / DNS failure | 2 retries with backoff, then `error` with the reason recorded |
| Fetch succeeded but no products found on a JS platform | `js_required` — the report names these domains, which is the input to a possible later Playwright pass |
| Malformed JSON / HTML | caught per page; other pages for that store still process |
| Null fields in Shopify feed (`body_html` can be null) | handled explicitly — this bug was hit during reconnaissance |

## Testing

`pytest`, with all tests offline.

- **Fixtures** — real HTML and JSON responses saved from the actual prospect sites into
  `tests/fixtures/`, so tests exercise real-world markup rather than invented markup.
- **Unit tests on `extract.py`** — price parsing (including `$1,395.00` and ranges),
  email extraction, phone extraction, knit matching with context retention, platform
  fingerprinting, chain detection, JSON-LD parsing, null-field handling.
- **Unit tests on `resolve.py`** — URL normalisation, `www.` collapsing (verified against
  the two known duplicates), social-only and blank partitioning.
- **Unit tests on `sources.py`** — feed pagination and stop conditions, sitemap index
  following, link prioritisation, page caps. Network calls stubbed.
- **Integration test** — the full pipeline over cached fixture responses, asserting a
  complete CSV with one row per input store. No network.

## Project structure

```
scrapping-bot/
├── data/
│   ├── fl-prospects.csv              input
│   ├── out/                          enriched CSV + run report
│   ├── raw/                          per-store JSON evidence
│   └── .cache/                       HTTP response cache
├── docs/superpowers/specs/
├── src/scrapebot/
│   ├── resolve.py  fetch.py  sources.py  extract.py  aggregate.py  cli.py
├── tests/
│   └── fixtures/
├── requirements.txt
└── README.md
```

Python 3.11, virtualenv, dependencies `requests`, `beautifulsoup4`, `lxml`, `pytest`.

Invoked as `python -m scrapebot data/fl-prospects.csv`, with input path as an argument
so future city lists run without code changes.

## Scope boundaries

**In scope:** evidence collection as described above.

**Explicitly out of scope:**

- Judging or scoring prospects. The bot collects; humans decide.
- AI/LLM classification of results.
- Full product catalogue export.
- Complete brand/designer rosters per store.
- Headless browser rendering. Deferred deliberately: build the dependency-light HTTP
  version first, let the run report reveal how many sites actually need a browser, and
  add Playwright for those specific sites only if the count justifies it.
- Any outreach, emailing, or CRM integration.

## Legal and ethical position

Reads only publicly accessible pages. Respects `robots.txt`. Rate-limited to well below
any burden on the target servers. Authenticates nowhere and bypasses no access control.
Collects business contact details, not personal data — standard B2B prospecting practice.

One flag for the operator, outside the bot's scope: whether and how to contact buyers
found this way is a CAN-SPAM and commercial-judgment question, not a scraping question.

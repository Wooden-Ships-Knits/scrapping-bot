# Scrapebot System Flow

A learning guide: how a list of store links becomes data tables, stage by stage, and
which tools each stage uses. For the full technical detail, see
[architecture/overview.md](architecture/overview.md). For the reasons behind each
decision, see [decisions/](decisions/).

> This document follows the code on branch `fix/eu-prices-and-page-kinds` (7 Oct 2026):
> prices are exported only as `price_raw`, with no conversion.

---

## 1. The big picture

```
List of links  ──►  Read & tidy  ──►  Visit each store  ──►  Raw tables  ──►  Export + report
(any format)        (inputs/)         (acquire/, 7 stages)   (JSONL per run)   (xlsx, csv, ...)
```

Principles to keep in mind throughout the flow:

1. **Cheapest and most exact source first.** Platform feed → structured data →
   browser → LLM. The LLM always comes last because it costs money and can be wrong.
2. **Every link is accounted for.** Links in = processed + skipped. Nothing disappears silently.
3. **Raw means raw.** Values are stored exactly as found (a price of `€ 63,95` stays
   `€ 63,95`), with their source and evidence URL. Conversion is the next system's job.
4. **No protection is bypassed.** `robots.txt` is respected, there is a delay per domain,
   no login and no CAPTCHA solving. A site that refuses is recorded as `blocked`.
5. **Tests never touch the network.** Every test uses recorded responses.

---

## 2. Two entry points, one engine

| Entry point | Command | For whom |
|---|---|---|
| **Web** | `make serve` → http://127.0.0.1:8765 | Operators: paste links, preview, test mode, download results |
| **CLI** | `uv run scrapebot run <input> --limit 2` | Developers, automation (n8n, cron) |

Both build the same object, `RunConfig` ([config.py](../src/scrapebot/config.py)),
then call the same pipeline ([pipeline.py](../src/scrapebot/pipeline.py)). The pipeline
never imports API or UI code.

```
Browser (React)  ──HTTP──►  FastAPI (api/app.py)  ──┐
                                                    ├──►  RunConfig  ──►  pipeline.prepare()  ──►  pipeline.execute()
Terminal (cli.py)  ─────────────────────────────────┘
```

- `prepare`: reads the input, creates the run folder `data/runs/<run_id>/`, and writes
  `config.json` and the `inputs` table.
- `execute`: visits the stores, writes the tables, exports, and writes `report.md`
  last. A `report.md` means the run finished.

---

## 3. The flow step by step

### Step 1. Reading the input ([inputs/](../src/scrapebot/inputs/))

| What happens | Tool |
|---|---|
| Reads pasted text, `.txt`, `.csv`, `.tsv`, `.xlsx`, `.json`, `.jsonl`, `.parquet` | `openpyxl`, `pyarrow`, standard library |
| Finds URLs in free text | `urlextract` |
| Groups by domain (`a.myshopify.com` ≠ `b.myshopify.com`) | `tldextract` (bundled Public Suffix List, no network) |
| Marks skipped links: `duplicate`, `invalid_url`, `social_only`, `marketplace`, `no_website`, `over_limit` | [resolve.py](../src/scrapebot/inputs/resolve.py) |

Example: `shopee.co.id/...` is skipped as `marketplace`, and two links to the same store
are merged into one (`duplicate`). A deep link such as `/shop/womens/knitwear` is
remembered and later fetched as a priority page.

### Step 2. Visiting stores in parallel ([pipeline.py](../src/scrapebot/pipeline.py))

Several stores are processed at once (`fetch.concurrency`, 6 by default), but each server
still receives only one request at a time, 1.5 seconds apart.

All network access goes through one door: `HttpFetcher` in [fetch.py](../src/scrapebot/fetch.py).

| Fetcher job | Tool |
|---|---|
| HTTP requests | `requests` |
| Respecting `robots.txt` | `urllib.robotparser` (standard library) |
| Caching successful responses in `data/.cache/` (re-runs are fast; failures are tried again) | a JSON file per URL |
| Detecting challenge pages: Cloudflare, DataDome, PerimeterX, Incapsula, Sucuri, Akamai | `CHALLENGE_MARKERS` |
| No `Accept-Language` header | so Shopify does not convert prices to a local currency |

### Step 3. Seven acquisition stages per store ([acquire/\_\_init\_\_.py](../src/scrapebot/acquire/__init__.py))

This is the core of the system. A store goes through the stages below, and the search
for products stops as soon as one stage succeeds. Every stage tried is recorded in the
`layers_tried` column.

```
 1. Homepage ──── failed/blocked? ──► status error / blocked (done)
      │
      ▼  detect platform + currency
 2. Platform feed ──── products found? ──► skip stage 4
      │
 3. Priority pages (contact, about, wholesale, stockist, links from the input) ← ALWAYS fetched
      │
 4. Discovery: sitemap, or internal links up to 2 levels deep (max. 25 pages)
      │
 5. Structured data on every page
      │
      ▼  still 0 products?
 6. Browser (Camoufox) ──── renders pages that need JavaScript
      │
      ▼  still 0 products?
 7. LLM ──── reads page text, keeps only products that pass the evidence rule
      │
      ▼
   ok (≥1 product)  or  no_products
```

**Stage 1: Homepage.** Fetch the front page. If it answers 401/403/429 or a challenge
page, the store is recorded as `blocked` and is done. Otherwise, detect the platform and
currency from markers in the HTML ([extract/profile.py](../src/scrapebot/extract/profile.py)).
The currency is taken only from explicit sources (`Shopify.currency.active`,
`og:price:currency`, JSON-LD `priceCurrency`), never from a "$" sign alone.

**Stage 2: Platform feed** ([acquire/feeds.py](../src/scrapebot/acquire/feeds.py),
[extract/feeds.py](../src/scrapebot/extract/feeds.py)). Many platforms have an endpoint
that returns the product list directly:

| Platform | Endpoint |
|---|---|
| Shopify | `/products.json` (250 per page, max. 20 pages) |
| Big Cartel | `/products.json` |
| WooCommerce | `/wp-json/wc/store/v1/products` (prices in the smallest unit, e.g. `22900`) |
| Squarespace | `?format=json` |
| Lightspeed | `/collection/?format=json` |
| Magento 2 | `/graphql` |

**Stage 3: Priority pages.** Contact, about, wholesale and stockist pages are always
fetched, feed or no feed, so contacts are never missed.

**Stage 4: Discovery** ([acquire/discovery.py](../src/scrapebot/acquire/discovery.py)).
Finds product and collection pages through `sitemap.xml`, or by following internal links.
Every URL gets a role (`priority`, `product`, `collection`, `other`, `skip`) from its
path pattern, for example `/collections/`, `/shop/`, `/women/` or `/knitwear/`. The same
patterns drive `page_kind` in [extract/pages.py](../src/scrapebot/extract/pages.py),
which labels each stored page.

**Stage 5: Structured data** ([extract/structured.py](../src/scrapebot/extract/structured.py),
[extract/json_products.py](../src/scrapebot/extract/json_products.py)).

| Format | Tool |
|---|---|
| JSON-LD, Microdata, RDFa `Product` | `extruct` |
| OpenGraph (`og:price:amount`) | `extruct` |
| App state (`__NEXT_DATA__`, Wix `wix-warmup-data`, `window.__INITIAL_STATE__`) | `chompjs`, `json` |
| BigCommerce product cards | `beautifulsoup4` + `lxml` |

**Stage 6: Browser** ([render.py](../src/scrapebot/render.py)). Only for stores that
still have 0 products. Camoufox (Firefox driven through Playwright) renders pages whose
content only appears through JavaScript, then captures the JSON the page loads
(XHR/fetch). The rules are the same as for HTTP: `robots.txt` is respected, there is a
delay, and images, media and fonts are not loaded. Camoufox is **not** used to get past
challenges.

**Stage 7: LLM** ([llm/](../src/scrapebot/llm/)). Only for stores that still have 0
products, and only when the LLM is switched on (`--llm openai/gpt-4o-mini`, or
`serve -c data/llm.yaml`). The details are in [section 4](#4-the-llm-stage-up-close).

### Step 4. Contacts ([extract/contacts.py](../src/scrapebot/extract/contacts.py))

From every page that was read:
- Emails come from `mailto:` links and from the text.
- Phone numbers come from `tel:` links, and from numbers written in the visible text
  (not from the markup, because numbers in an SVG path can look like phone numbers).
- Instagram, Facebook, TikTok, LinkedIn and Pinterest come from profile links.

Every contact keeps its `source_url`: the page it was found on.

### Step 5. Raw tables ([tables.py](../src/scrapebot/tables.py), [store.py](../src/scrapebot/store.py))

As soon as a store is done, its rows are appended to one JSONL file per table in
`data/runs/<run_id>/tables/`. If a run is interrupted, the finished stores are not lost.

| Table | One row = | Key columns |
|---|---|---|
| `runs` | one run | config, version, mode |
| `inputs` | one input link | the original link, status or skip reason, the whole input row |
| `stores` | one store | `status`, `platform`, `currency`, `source_used`, `layers_tried`, `llm_used` |
| `products` | one product | `title`, `price_raw`, `currency`, `vendor`, `url`, `source`, `evidence_url`, `needs_review`, `raw` |
| `pages` | one page | `page_kind`, `http_status`, `via` (http/browser), `text` (no HTML) |
| `contacts` | one contact | `type`, `value`, `source_url` |
| `llm_calls` | one LLM call | model, prompt version, tokens, cost |
| `changes` | a change between runs | not filled yet (planned for M5) |

Every table joins on `run_id` and `domain`. HTML is never stored; only the page text
is (ADR 0006).

### Step 6. Export and report ([outputs/](../src/scrapebot/outputs/), [report.py](../src/scrapebot/report.py))

| Format | Tool |
|---|---|
| JSON, JSONL, CSV, TSV | standard library |
| Excel | `openpyxl` (one sheet per table) |
| Parquet | `pyarrow` |
| SQLite, DuckDB | `sqlite3`, `duckdb` |

What a run folder holds:

```
data/runs/20261007T012357237Z-1eb499/
├── config.json      ← run settings (no API keys)
├── tables/*.jsonl   ← raw tables (the source of truth)
├── export/          ← the files you picked: xlsx, csv, ...
├── summary.csv      ← one row per link: knit_share, example products, contacts
├── manifest.json    ← package versions, duration, row counts
└── report.md        ← summary: store statuses, product sources, LLM section (cost, tokens)
```

---

## 4. The LLM stage up close

This is the stage discussed most today, so its flow is written out in full:

```
Pages already read
   │  sorted: collection → product → home → other   (max. 6 pages)
   ▼
condensed_text()  ── max. 6,000 characters per page
   │  trafilatura (main content) when the prices survive it,
   │  otherwise: the stretch of text with the most prices
   ▼
Prompt extract_v3.md  ── "copy titles & prices exactly, do not translate"
   ▼
LiteLLM ── sends to the provider (OpenAI, Gemini, Anthropic, Ollama, ...)
   │  passing failure? retry after 3 s & 10 s, then the fallback model
   │  budget used up? stop calling
   ▼
instructor + Pydantic ── forces the answer into a StoreExtraction (llm/schemas.py)
   ▼
Evidence rule (llm/evidence.py) ── a product is DROPPED unless:
   │   • its source_url is one of the pages sent
   │   • its title appears in that page's text
   │   • its price appears on that page (compared as numbers: 41.95 = € 41,95)
   ▼
Products that pass → source = "llm", needs_review = true
```

| Part | Tool | File |
|---|---|---|
| One interface for every provider | `litellm` | [gateway.py](../src/scrapebot/llm/gateway.py) |
| Structured, validated output | `instructor` + `pydantic` | [schemas.py](../src/scrapebot/llm/schemas.py) |
| Extracting a page's main content | `trafilatura` | [gateway.py](../src/scrapebot/llm/gateway.py) |
| Reading API keys from `.env` | `python-dotenv` | [keys.py](../src/scrapebot/keys.py) |
| Masking keys in logs | `RedactingFilter` | [keys.py](../src/scrapebot/keys.py) |

**A real example (knitfactory.com, 7 Oct 2026).** At first the LLM found nothing. There
were three causes in a chain:
1. The category page was not recognised as a `collection`, so the customer service
   page was sent instead.
2. trafilatura dropped the product grid.
3. The price `€ 41,95` was read as 4195.

Once all three were fixed, the result was 21–25 products. The lesson: when the LLM
"finds nothing", first check **what was sent** to the LLM, and only then suspect the
model.

---

## 5. Final store status

| Status | Meaning |
|---|---|
| `ok` | At least one product found |
| `no_products` | The site was read, but no stage found a catalogue |
| `js_required` | Needs JavaScript, and the browser is unavailable or failed |
| `blocked` | 401/403/429 or a challenge page; not bypassed |
| `error` | Network failure, another HTTP error, or disallowed by `robots.txt` |

Columns that help read the results:
- `source_used`: the stage that found the products.
- `layers_tried`: every stage that was tried.
- `failed_page_count`: how many pages failed. For example next.co.uk: 23 of 27
  pages answered 403.

---

## 6. Tool map (short)

**Bot (Python 3.11+, managed with `uv`)**

| Tool | Used for |
|---|---|
| `pydantic` | Data models: config, products, table rows |
| `pyyaml` | Reading `.yaml` config files |
| `requests` | HTTP |
| `beautifulsoup4`, `lxml` | Parsing HTML, links, page text |
| `extruct` | JSON-LD, Microdata, RDFa, OpenGraph |
| `chompjs` | Reading JavaScript objects in a page |
| `urlextract`, `tldextract` | Finding URLs and domains in the input |
| `camoufox` | The browser for pages that need JavaScript |
| `openpyxl`, `pyarrow`, `duckdb` | Excel, Parquet and DuckDB export |
| `litellm`, `instructor`, `trafilatura`, `python-dotenv` | The LLM stage (`llm` extra) |
| `fastapi`, `uvicorn`, `python-multipart` | The local API for the web app (`ui` extra) |

**Web (`web/`, managed with `pnpm`)**

| Tool | Used for |
|---|---|
| React + TypeScript | The interface |
| Vite | Dev server and build |
| `openapi-typescript` | TypeScript types generated from the API (`make api-types`) |
| `lucide-react` | Icons |
| Vitest + Testing Library | UI unit tests |
| Playwright | End-to-end tests, offline, desktop and mobile (`make e2e`) |

**Code quality**

| Tool | Used for |
|---|---|
| `pytest` | Python tests (offline; HTTP from recorded fixtures) |
| `ruff` | Lint and format |
| `pyright` | Type checking |
| `pre-commit` | Runs every check before a commit |
| `make check` | All the checks above at once; must pass before a commit |

---

## 7. Learning by doing

1. **Run something small and read the result:**
   ```bash
   uv run scrapebot run data/llm-test.txt --limit 2
   ```
   Open `report.md` in the run folder, then `tables/stores.jsonl`. Look at
   `layers_tried` for each store.
2. **Follow one store through the code.** Start at the `acquire()` function in
   [acquire/\_\_init\_\_.py](../src/scrapebot/acquire/__init__.py). The docstring at the
   top of the file lists the stages in order.
3. **Switch the LLM on and compare:**
   ```bash
   uv run scrapebot run data/llm-test.txt --llm openai/gpt-4o-mini --llm-budget 0.2
   ```
   A store that was `no_products` may now be `ok` with `source_used = llm`.
   Look at `llm_calls.jsonl` for the cost.
4. **Read the tests.** The tests in [tests/unit/](../tests/unit/) are the shortest
   examples of how each module is used. For example `test_llm.py` for the evidence rule
   and `test_acquire.py` for the stage order.
5. **Read the decisions.** [decisions/0001](decisions/0001-layered-acquisition-llm-last.md)
   (why the LLM comes last) and [0002](decisions/0002-camoufox-for-rendering-only.md)
   (why the browser does not get past protection).

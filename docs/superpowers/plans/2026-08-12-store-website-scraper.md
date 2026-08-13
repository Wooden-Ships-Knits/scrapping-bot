# Store Website Scraper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a bot that visits each prospect store's website from `data/fl-prospects.csv` and collects evidence of what they sell (especially knitwear, with prices) plus contact details, emitting an enriched CSV and per-store raw JSON.

**Architecture:** A four-stage pipeline — resolve (dedupe domains) → acquire (Shopify feed, else sitemap, else crawl) → extract (pure functions over HTML/JSON) → emit (CSV + JSON + report). All network access is confined to one injectable `Fetcher` class, so every other module is tested offline against real saved fixtures. The bot collects evidence only; it never judges whether a store is a good prospect.

**Tech Stack:** Python 3.11, `requests`, `beautifulsoup4`, `lxml`, `pytest`. Standard library `dataclasses`, `csv`, `re`, `urllib`.

**Spec:** `docs/superpowers/specs/2026-08-12-store-website-scraper-design.md`

---

## File Structure

| File | Responsibility |
|---|---|
| `src/scrapebot/models.py` | Dataclasses shared across stages. No logic. |
| `src/scrapebot/resolve.py` | CSV rows → deduplicated `Target` list. URL normalisation. |
| `src/scrapebot/extract.py` | Pure functions over HTML/JSON text. No network, no I/O. |
| `src/scrapebot/fetch.py` | The only module that touches the network. Cache, robots, rate limit, retry. |
| `src/scrapebot/sources.py` | Three acquisition strategies, tried in order. |
| `src/scrapebot/aggregate.py` | One `Acquired` → one flat CSV row dict. |
| `src/scrapebot/cli.py` | Orchestration, CSV read/write, run report. |
| `tests/fixtures/` | Real HTML/JSON saved from actual prospect sites. |

`extract.py` is the largest module but stays cohesive: every function has the same shape (text in, structured data out) and none of them touch anything else. Split it only if it passes ~400 lines.

---

## Task 0: Project scaffolding

**Files:**
- Create: `requirements.txt`, `pytest.ini`, `src/scrapebot/__init__.py`, `tests/__init__.py`

- [ ] **Step 1: Create the virtualenv and install dependencies**

```bash
cd /Users/webadmin/Automation/scrapping-bot
python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q requests beautifulsoup4 lxml pytest
.venv/bin/pip freeze > requirements.txt
cat requirements.txt
```

Expected: a list of pinned versions including `requests==`, `beautifulsoup4==`, `lxml==`, `pytest==`.

- [ ] **Step 2: Create the package skeleton**

```bash
mkdir -p src/scrapebot tests/fixtures data/out data/raw
touch src/scrapebot/__init__.py tests/__init__.py
```

- [ ] **Step 3: Create `pytest.ini`**

```ini
[pytest]
pythonpath = src
testpaths = tests
addopts = -q
```

- [ ] **Step 4: Verify pytest runs and collects nothing**

Run: `.venv/bin/pytest`
Expected: `no tests ran` (exit code 5). This confirms config is valid.

- [ ] **Step 5: Commit**

```bash
git add requirements.txt pytest.ini src tests
git commit -m "chore: scaffold scrapebot package and pytest config"
```

---

## Task 1: Data models

**Files:**
- Create: `src/scrapebot/models.py`
- Test: `tests/test_models.py`

These types are used by every later task. Names here are binding — do not rename them later.

- [ ] **Step 1: Write the failing test**

Create `tests/test_models.py`:

```python
from scrapebot.models import FetchResult, Product, Page, Target, Acquired


def test_fetch_result_ok_requires_200_and_no_error():
    assert FetchResult(url="u", status_code=200, body="hi", final_url="u").ok is True
    assert FetchResult(url="u", status_code=404, body="", final_url="u").ok is False
    assert FetchResult(url="u", status_code=200, body="", final_url="u", error="boom").ok is False


def test_product_defaults():
    p = Product(title="Cher Sweater in Eggnog", price=139.0)
    assert p.product_type == ""
    assert p.tags == []
    assert p.description == ""


def test_target_and_acquired_defaults():
    t = Target(domain="monkeesofnaples.com", url="https://www.monkeesofnaples.com", rows=[{"a": 1}])
    assert t.rows[0]["a"] == 1
    a = Acquired(domain=t.domain)
    assert a.source_used == "none"
    assert a.products == [] and a.pages == []
    assert a.status == "ok"


def test_page_holds_url_and_text():
    pg = Page(url="https://x.com/about", html="<p>Hi</p>", text="Hi")
    assert pg.text == "Hi"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scrapebot.models'`

- [ ] **Step 3: Write the implementation**

Create `src/scrapebot/models.py`:

```python
"""Shared data structures. No logic beyond trivial derived properties."""
from dataclasses import dataclass, field


@dataclass
class FetchResult:
    """One HTTP response, or the record of why there wasn't one."""
    url: str
    status_code: int | None
    body: str
    final_url: str
    error: str = ""
    ssl_bypassed: bool = False
    from_cache: bool = False

    @property
    def ok(self) -> bool:
        return self.status_code == 200 and not self.error


@dataclass
class Product:
    title: str
    price: float | None
    product_type: str = ""
    tags: list[str] = field(default_factory=list)
    description: str = ""


@dataclass
class Page:
    url: str
    html: str
    text: str


@dataclass
class Target:
    """One store to scrape. `rows` are the original CSV rows sharing this domain."""
    domain: str
    url: str
    rows: list[dict] = field(default_factory=list)


@dataclass
class Acquired:
    """Everything gathered for one store."""
    domain: str
    source_used: str = "none"          # shopify_feed | sitemap | crawl | none
    products: list[Product] = field(default_factory=list)
    pages: list[Page] = field(default_factory=list)
    status: str = "ok"                 # ok | blocked | ssl_bypassed | error | js_required
    error: str = ""
    pages_fetched: int = 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_models.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/scrapebot/models.py tests/test_models.py
git commit -m "feat: add shared data models"
```

---

## Task 2: URL resolution and deduplication

**Files:**
- Create: `src/scrapebot/resolve.py`
- Test: `tests/test_resolve.py`

The real input has two `www.`/non-`www.` duplicate pairs (`saracampbell.com`, `backofthebayboutique.com`), 9 rows with no website, and 2 Instagram-only rows. All four cases are tested.

- [ ] **Step 1: Write the failing test**

Create `tests/test_resolve.py`:

```python
from scrapebot.resolve import canonical_domain, normalize_url, classify_row, load_targets


def test_canonical_domain_strips_www_and_lowercases():
    assert canonical_domain("https://www.SaraCampbell.com/shop") == "saracampbell.com"
    assert canonical_domain("https://saracampbell.com/") == "saracampbell.com"
    assert canonical_domain("http://Shop.Example.CO.UK/x") == "shop.example.co.uk"


def test_normalize_url_adds_scheme_and_strips_trailing_slash():
    assert normalize_url("example.com") == "https://example.com"
    assert normalize_url("https://example.com/") == "https://example.com"
    assert normalize_url("  https://example.com/shop/  ") == "https://example.com/shop"


def test_classify_row_detects_blank_and_social():
    assert classify_row({"website": ""}) == "no_website"
    assert classify_row({"website": "   "}) == "no_website"
    assert classify_row({"website": "https://www.instagram.com/somestore/"}) == "social_only"
    assert classify_row({"website": "https://www.facebook.com/somestore"}) == "social_only"
    assert classify_row({"website": "https://monkeesofnaples.com"}) == "ok"


def test_load_targets_collapses_www_duplicates(tmp_path):
    csv_path = tmp_path / "in.csv"
    csv_path.write_text(
        "store_name,website\n"
        "Sara Campbell,https://www.saracampbell.com/\n"
        "Sara Campbell Naples,https://saracampbell.com/pages/naples\n"
        "No Site Store,\n"
        "Insta Store,https://www.instagram.com/insta_store/\n"
        "Monkees,https://www.monkeesofnaples.com\n"
    )
    targets, skipped = load_targets(str(csv_path))

    assert [t.domain for t in targets] == ["saracampbell.com", "monkeesofnaples.com"]
    sara = targets[0]
    assert len(sara.rows) == 2, "both Sara Campbell rows collapse into one target"
    assert sara.url == "https://www.saracampbell.com", "first-seen URL wins"

    assert len(skipped) == 2
    assert {s[1] for s in skipped} == {"no_website", "social_only"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_resolve.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scrapebot.resolve'`

- [ ] **Step 3: Write the implementation**

Create `src/scrapebot/resolve.py`:

```python
"""Turn raw CSV rows into a deduplicated list of scrape targets."""
import csv
import re
from urllib.parse import urlparse

from .models import Target

SOCIAL_HOSTS = ("instagram.com", "facebook.com", "twitter.com", "x.com", "tiktok.com")

_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")


def normalize_url(raw: str) -> str:
    """Add a scheme if missing, strip whitespace and any trailing slash.

    An existing scheme is detected case-insensitively and left alone (so
    "HTTP://..." and "ftp://..." are not mistaken for scheme-less input).
    A protocol-relative value ("//host/path") gets an "https:" prefix rather
    than a full "https://" prepended in front of its own leading slashes.
    """
    u = (raw or "").strip()
    if not u:
        return ""
    if u.startswith("//"):
        u = "https:" + u
    elif not _SCHEME_RE.match(u):
        u = "https://" + u
    return u.rstrip("/")


def _host(raw: str) -> str:
    """Lowercase host with userinfo, port, and any leading 'www.' removed.

    Returns "" when the value has no parseable host (e.g. a bare path).
    Uses .hostname rather than .netloc so credentials and ports never leak
    into the value, which is used downstream as a filename.
    """
    normalized = normalize_url(raw)
    if not normalized:
        return ""
    host = (urlparse(normalized).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def canonical_domain(raw: str) -> str:
    """Lowercase host with any leading 'www.' removed."""
    return _host(raw)


def classify_row(row: dict) -> str:
    """Return 'no_website', 'social_only', or 'ok'."""
    website = (row.get("website") or "").strip()
    if not website:
        return "no_website"
    host = _host(website)
    if not host:
        return "no_website"
    if host in SOCIAL_HOSTS or any(host.endswith("." + s) for s in SOCIAL_HOSTS):
        return "social_only"
    return "ok"


def load_targets(csv_path: str) -> tuple[list[Target], list[tuple[dict, str]]]:
    """Read the input CSV.

    Returns (targets, skipped) where skipped is a list of (row, reason) for
    rows that need no fetching. Every input row appears in exactly one of the two.
    """
    targets: dict[str, Target] = {}
    skipped: list[tuple[dict, str]] = []

    with open(csv_path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            reason = classify_row(row)
            if reason != "ok":
                skipped.append((row, reason))
                continue
            domain = canonical_domain(row["website"])
            if domain in targets:
                targets[domain].rows.append(row)
            else:
                targets[domain] = Target(
                    domain=domain,
                    url=normalize_url(row["website"]),
                    rows=[row],
                )
    return list(targets.values()), skipped
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_resolve.py -v`
Expected: 11 passed

The 4 tests above plus 7 hardening tests added during review, covering: lookalike
domains that must NOT be treated as social (`apex.com`, `onyx.com`, `fedex.com` —
`"x.com"` suffix-matches all of them without a dot boundary), genuine social
subdomains (`m.facebook.com`), case-insensitive scheme detection, protocol-relative
URLs, host-less values, userinfo/port stripping, and the row-conservation invariant
that `load_targets`'s docstring promises.

- [ ] **Step 5: Verify against the real input file**

Run:
```bash
.venv/bin/python -c "
from scrapebot.resolve import load_targets
import sys; sys.path.insert(0, 'src')
t, s = load_targets('data/fl-prospects.csv')
print('targets:', len(t), 'skipped:', len(s))
print('rows accounted for:', sum(len(x.rows) for x in t) + len(s))
"
```

Expected: `targets: 65  skipped: 11` and `rows accounted for: 78`. The 65/11 split and the total of 78 both come from the spec's input table — if they differ, the dedupe logic is wrong.

- [ ] **Step 6: Commit**

```bash
git add src/scrapebot/resolve.py tests/test_resolve.py
git commit -m "feat: resolve and dedupe prospect domains from CSV"
```

---

## Task 3: Knit matching with context

**Files:**
- Create: `src/scrapebot/extract.py`
- Test: `tests/test_extract_knit.py`

The core qualification signal. A bare count is useless — every match must retain the product title it came from.

- [ ] **Step 1: Write the failing test**

Create `tests/test_extract_knit.py`:

```python
from scrapebot.models import Product
from scrapebot.extract import knit_terms_in, product_blob, knit_products


def test_knit_terms_matches_whole_words_case_insensitively():
    assert knit_terms_in("Cher Sweater in Eggnog") == ["sweater"]
    assert knit_terms_in("Pop Posh Cotton CASHMERE Polo") == ["cashmere"]
    assert knit_terms_in("Ribbed Knit Cardigan") == ["knit", "cardigan"]


def test_knit_terms_does_not_match_substrings():
    # 'wool' must not fire on 'woolworths'; 'knit' must not fire on 'knitting needles holder'
    assert knit_terms_in("Woolworths gift card") == []
    assert knit_terms_in("Unknitted") == []


def test_knit_terms_deduplicates_and_preserves_order():
    assert knit_terms_in("Knit sweater, knit cardigan") == ["knit", "sweater", "cardigan"]


def test_knit_terms_handles_empty_and_none():
    assert knit_terms_in("") == []
    assert knit_terms_in(None) == []


def test_product_blob_combines_fields_and_truncates_description():
    p = Product(
        title="Kailyn Dress",
        price=298.0,
        product_type="Dresses",
        tags=["spring", "knitwear"],
        description="x" * 900,
    )
    blob = product_blob(p)
    assert "Kailyn Dress" in blob and "Dresses" in blob and "knitwear" in blob
    assert len(blob) < 700, "description is truncated to 400 chars"


def test_product_blob_survives_none_fields():
    # Shopify feeds return null body_html — this crashed during reconnaissance.
    p = Product(title="Tee", price=20.0, description=None, tags=None, product_type=None)
    assert product_blob(p) == "Tee"


def test_knit_products_filters_and_keeps_the_product():
    items = [
        Product(title="Cher Sweater in Eggnog", price=139.0),
        Product(title="Leather Handbag", price=450.0),
        Product(title="Plain Tee", price=20.0, description="A soft merino blend."),
    ]
    hits = knit_products(items)
    assert [p.title for p in hits] == ["Cher Sweater in Eggnog", "Plain Tee"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_extract_knit.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scrapebot.extract'`

- [ ] **Step 3: Write the implementation**

Create `src/scrapebot/extract.py`:

```python
"""Pure extraction functions. No network, no file I/O, no global state."""
import html
import re

from .models import Product

KNIT_TERMS = (
    "knit", "knitwear", "sweater", "cardigan", "pullover", "jumper",
    "cashmere", "merino", "wool", "crewneck", "turtleneck", "sweatshirt",
    "poncho", "shawl",
)
# Trailing "s" is optional because Shopify stores categorise knitwear in the plural
# ("Sweaters", "Sweaters & Sweatshirts", "Clothing/Sweaters" are all real product_type
# values observed on the prospect list). The capture group stays on the BASE term so
# knit_terms_in("Sweaters") returns ["sweater"] and plurals dedupe with singulars.
# The leading \b must stay: it is what stops "wool" firing on "Woolworths".
KNIT_RE = re.compile(r"\b(" + "|".join(KNIT_TERMS) + r")s?\b", re.I)


def knit_terms_in(text: str | None) -> list[str]:
    """Distinct knit terms present in text, lowercased, in first-seen order."""
    if not text:
        return []
    seen: list[str] = []
    for m in KNIT_RE.finditer(text):
        term = m.group(1).lower()
        if term not in seen:
            seen.append(term)
    return seen


# Terms too generic to qualify a product on their own: "wool" and "shawl" also
# appear routinely on woven (non-knit) goods — coats, trousers, vests.
WEAK_KNIT_TERMS = frozenset({"wool", "shawl"})

# Deliberately excludes hat/glove/sock: those garments are frequently KNIT, and
# measured across 4,759 real products they suppressed nothing useful. "vest" IS
# included — it correctly catches quilted-nylon and down vests.
WOVEN_GARMENT_TERMS = (
    "coat", "jacket", "blazer", "trouser", "trousers", "pant", "pants",
    "bag", "blanket", "rug", "skirt", "short", "shorts", "jean", "jeans",
    "denim", "vest",
)
WOVEN_GARMENT_RE = re.compile(r"\b(" + "|".join(WOVEN_GARMENT_TERMS) + r")\b", re.I)

_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def _clean_html(text: str) -> str:
    """Plain text from raw HTML: drop script/style blocks (incl. contents), strip
    remaining tags, unescape entities, collapse whitespace."""
    text = _SCRIPT_STYLE_RE.sub(" ", text)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    return _WHITESPACE_RE.sub(" ", text).strip()


def product_blob(p: Product) -> str:
    """Searchable text for one product. Tolerates null fields from Shopify feeds.

    `description` is raw body_html straight from the Shopify feed, so it is
    cleaned to plain text BEFORE truncation — otherwise markup can consume the
    whole 400-char budget and hide the fabric line that follows it.
    `Product.description` itself is left untouched; only this copy is cleaned.
    """
    tags = p.tags or []
    parts = [
        p.title or "",
        p.product_type or "",
        " ".join(tags) if isinstance(tags, list) else str(tags),
        _clean_html(p.description or "")[:400],
    ]
    return " ".join(part for part in parts if part).strip()


def knit_products(products: list[Product]) -> list[Product]:
    """The subset of products whose searchable text mentions a knit term.

    A product is suppressed when every matched term is "weak" (wool, shawl) AND
    the title names a clearly woven garment. Any strong term present keeps the
    product regardless of title.
    """
    hits = []
    for p in products:
        terms = knit_terms_in(product_blob(p))
        if not terms:
            continue
        if all(t in WEAK_KNIT_TERMS for t in terms) and WOVEN_GARMENT_RE.search(p.title or ""):
            continue
        hits.append(p)
    return hits
```

`_clean_html` (regex) and `html_to_text` (BeautifulSoup, added in Task 8) are
deliberately separate and must both exist. `_clean_html` runs once per product across
thousands of products where regex is the right speed tradeoff; `html_to_text` parses
whole pages where correctness matters more.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_extract_knit.py -v`
Expected: 29 passed

The 7 tests above plus 3 plural-handling tests added during review: plural product
categories resolve to the singular base term (`"Sweaters"` -> `["sweater"]`), a real
observed `product_type` string (`"Shop All;Clothing/Tops; Clothing/Sweaters"`) matches,
and substring rejection still holds after the change.

- [ ] **Step 5: Commit**

```bash
git add src/scrapebot/extract.py tests/test_extract_knit.py
git commit -m "feat: knit term matching that retains product context"
```

---

## Task 4: Price parsing

**Files:**
- Modify: `src/scrapebot/extract.py`
- Test: `tests/test_extract_price.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_extract_price.py`:

```python
from scrapebot.models import Product
from scrapebot.extract import parse_price, price_stats


def test_parse_price_handles_common_formats():
    assert parse_price("139.00") == 139.0
    assert parse_price("$1,395.00") == 1395.0
    assert parse_price("USD 45") == 45.0
    assert parse_price(139) == 139.0
    assert parse_price(" $38.50 ") == 38.5


def test_parse_price_rejects_junk():
    assert parse_price("") is None
    assert parse_price(None) is None
    assert parse_price("Sold out") is None
    assert parse_price("0") is None, "zero price is not a real price"
    assert parse_price("0.00") is None


def test_parse_price_takes_first_number_in_a_range():
    assert parse_price("$120.00 - $180.00") == 120.0


def test_price_stats_returns_min_max_median():
    items = [
        Product(title="a", price=10.0),
        Product(title="b", price=30.0),
        Product(title="c", price=20.0),
        Product(title="d", price=None),
    ]
    assert price_stats(items) == (10.0, 30.0, 20.0)


def test_price_stats_on_empty_input():
    assert price_stats([]) == (None, None, None)
    assert price_stats([Product(title="a", price=None)]) == (None, None, None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_extract_price.py -v`
Expected: FAIL — `ImportError: cannot import name 'parse_price'`

- [ ] **Step 3: Write the implementation**

Append to `src/scrapebot/extract.py`:

```python
import statistics

PRICE_RE = re.compile(r"(\d[\d,]*(?:\.\d{1,2})?)")


def parse_price(raw) -> float | None:
    """First positive number in the input, or None. Handles '$1,395.00' and ranges."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw) or None
    m = PRICE_RE.search(str(raw))
    if not m:
        return None
    try:
        value = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    return value if value > 0 else None


def price_stats(products: list[Product]) -> tuple[float | None, float | None, float | None]:
    """(min, max, median) over products that have a price. All None if none do."""
    prices = [p.price for p in products if p.price]
    if not prices:
        return (None, None, None)
    return (min(prices), max(prices), statistics.median(prices))
```

Move the `import statistics` line up to sit beside `import re` at the top of the file.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_extract_price.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/scrapebot/extract.py tests/test_extract_price.py
git commit -m "feat: price parsing and per-store price statistics"
```

---

## Task 5: Contact extraction

**Files:**
- Modify: `src/scrapebot/extract.py`
- Test: `tests/test_extract_contacts.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_extract_contacts.py`:

```python
from scrapebot.extract import extract_emails, extract_phones, extract_socials

HTML = """
<html><body>
  <a href="mailto:hello@monkeesofnaples.com">Email us</a>
  <a href="mailto:buyer@monkeesofnaples.com?subject=Wholesale">Wholesale</a>
  <p>Or reach us at info@monkeesofnaples.com or call (239) 555-0142.</p>
  <a href="tel:+12395550142">Call</a>
  <a href="https://www.instagram.com/monkeesofnaples/">IG</a>
  <a href="https://www.facebook.com/monkeesofnaples">FB</a>
  <img src="https://cdn.shopify.com/logo@2x.png">
</body></html>
"""


def test_extract_emails_finds_mailto_and_text_and_dedupes():
    emails = extract_emails(HTML)
    assert emails == [
        "hello@monkeesofnaples.com",
        "buyer@monkeesofnaples.com",
        "info@monkeesofnaples.com",
    ]


def test_extract_emails_ignores_image_and_asset_filenames():
    assert extract_emails('<img src="logo@2x.png"> sprite@3x.jpg') == []


def test_extract_emails_strips_mailto_query_params():
    assert extract_emails('<a href="mailto:a@b.com?subject=Hi&body=x">m</a>') == ["a@b.com"]


def test_extract_phones_finds_tel_links_and_text():
    phones = extract_phones(HTML)
    assert "+12395550142" in phones
    assert any("239" in p and "555" in p for p in phones)


def test_extract_socials_returns_profile_urls():
    s = extract_socials(HTML)
    assert s["instagram"] == "https://www.instagram.com/monkeesofnaples/"
    assert s["facebook"] == "https://www.facebook.com/monkeesofnaples"


def test_extract_socials_missing_returns_empty_strings():
    s = extract_socials("<html><body>nothing here</body></html>")
    assert s == {"instagram": "", "facebook": ""}


def test_extract_socials_ignores_share_intent_links():
    html = '<a href="https://www.facebook.com/sharer/sharer.php?u=x">Share</a>'
    assert extract_socials(html)["facebook"] == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_extract_contacts.py -v`
Expected: FAIL — `ImportError: cannot import name 'extract_emails'`

- [ ] **Step 3: Write the implementation**

Append to `src/scrapebot/extract.py`:

```python
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
MAILTO_RE = re.compile(r'mailto:([^"\'?>\s]+)', re.I)
TEL_RE = re.compile(r'tel:([+\d][\d\-().\s]{6,})', re.I)
PHONE_TEXT_RE = re.compile(r"\(?\b\d{3}\)?[\s.\-]\d{3}[\s.\-]\d{4}\b")
ASSET_SUFFIX_RE = re.compile(r"\.(png|jpe?g|gif|svg|webp|css|js)$", re.I)

_IG_RE = re.compile(r'https?://(?:www\.)?instagram\.com/[^"\'\s>]+', re.I)
_FB_RE = re.compile(r'https?://(?:www\.)?facebook\.com/[^"\'\s>]+', re.I)
_SOCIAL_JUNK = ("sharer", "/share", "intent", "plugins/", "/tr?", "dialog/")


def _dedupe(items: list[str]) -> list[str]:
    seen: list[str] = []
    for i in items:
        if i and i not in seen:
            seen.append(i)
    return seen


def extract_emails(html: str) -> list[str]:
    """Emails from mailto: links first, then from page text. Deduplicated, order preserved."""
    found = [m.split("?")[0].strip() for m in MAILTO_RE.findall(html or "")]
    found += EMAIL_RE.findall(html or "")
    return _dedupe([e for e in found if not ASSET_SUFFIX_RE.search(e)])


def extract_phones(html: str) -> list[str]:
    """Phone numbers from tel: links and page text."""
    found = [m.strip() for m in TEL_RE.findall(html or "")]
    found += [m.strip() for m in PHONE_TEXT_RE.findall(html or "")]
    return _dedupe(found)


def extract_socials(html: str) -> dict:
    """First real Instagram and Facebook profile URL. Share/tracking links ignored."""
    out = {"instagram": "", "facebook": ""}
    for key, rx in (("instagram", _IG_RE), ("facebook", _FB_RE)):
        for url in rx.findall(html or ""):
            if any(j in url.lower() for j in _SOCIAL_JUNK):
                continue
            out[key] = url
            break
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_extract_contacts.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/scrapebot/extract.py tests/test_extract_contacts.py
git commit -m "feat: extract emails, phones and social profiles"
```

---

## Task 6: Platform fingerprint and chain detection

**Files:**
- Modify: `src/scrapebot/extract.py`
- Test: `tests/test_extract_platform.py`

Chain names come from the real prospect list — these stores are in `data/fl-prospects.csv` and are not wholesale prospects.

- [ ] **Step 1: Write the failing test**

Create `tests/test_extract_platform.py`:

```python
from scrapebot.extract import detect_platform, is_chain


def test_detect_platform_recognises_each_stack():
    assert detect_platform('<script src="https://cdn.shopify.com/s/x.js">') == "shopify"
    assert detect_platform('<div id="siteWrapper" data-squarespace>') == "squarespace"
    assert detect_platform('<img src="https://static.wixstatic.com/a.png">') == "wix"
    assert detect_platform('<link href="/wp-content/plugins/woocommerce/x.css">') == "woocommerce"
    assert detect_platform('<script>var BCData={};</script> bigcommerce') == "bigcommerce"


def test_detect_platform_prefers_shopify_over_generic_wordpress():
    html = '<link href="/wp-content/x.css"><script src="https://cdn.shopify.com/y.js">'
    assert detect_platform(html) == "shopify"


def test_detect_platform_falls_back_to_unknown():
    assert detect_platform("<html><body>plain</body></html>") == "custom/unknown"
    assert detect_platform("") == "custom/unknown"


def test_is_chain_matches_known_national_retailers():
    assert is_chain("H&M", "") is True
    assert is_chain("Macy's", "") is True
    assert is_chain("Charlotte Russe", "") is True
    assert is_chain("Windsor", "") is True
    assert is_chain("Bealls Florida", "") is True
    assert is_chain("Brandy Melville", "") is True


def test_is_chain_is_case_and_punctuation_insensitive():
    assert is_chain("MACYS", "") is True
    assert is_chain("macy s", "") is True


def test_is_chain_false_for_independent_boutiques():
    assert is_chain("Monkee's of Naples", "") is False
    assert is_chain("Purple Poppy", "") is False


def test_is_chain_heuristic_on_many_store_locations():
    html = "Find a store near you" + "".join(f"<li>Store {i}</li>" for i in range(40))
    assert is_chain("Some Boutique", html) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_extract_platform.py -v`
Expected: FAIL — `ImportError: cannot import name 'detect_platform'`

- [ ] **Step 3: Write the implementation**

Append to `src/scrapebot/extract.py`:

```python
# Ordered: the first match wins, so specific e-commerce platforms beat generic CMS markers.
PLATFORM_MARKERS = (
    ("shopify", ("cdn.shopify.com", "shopify.theme", "myshopify.com")),
    ("squarespace", ("squarespace.com", "static1.squarespace", "data-squarespace")),
    ("wix", ("wixstatic.com", "wix.com", "_wixcssimportrule")),
    ("bigcommerce", ("bigcommerce.com", "bcdata", "var bcdata")),
    ("woocommerce", ("woocommerce", "wp-content/plugins/woocommerce")),
    ("other-ecom", ("ecwid", "lightspeed", "shoplightspeed")),
    ("wordpress", ("wp-content", "wp-includes")),
)

KNOWN_CHAINS = (
    "h m", "macys", "charlotte russe", "windsor", "bealls",
    "brandy melville", "four seasons", "nordstrom", "dillards",
    "talbots", "chicos", "anthropologie", "j crew",
)
_STORE_LOCATOR_RE = re.compile(r"find a store|store locator|all locations|our stores", re.I)


def detect_platform(html: str) -> str:
    """Best-guess e-commerce platform from HTML markers."""
    h = (html or "").lower()
    for name, markers in PLATFORM_MARKERS:
        if any(m in h for m in markers):
            return name
    return "custom/unknown"


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


def is_chain(store_name: str, html: str) -> bool:
    """True for national chains, which are not wholesale prospects.

    Two signals: a known-chain name list, and a store-locator page listing many
    locations. Deliberately simple — it will miss chains not on the list.

    Names are compared with punctuation and spaces removed, so "Macy's",
    "MACYS" and "macy s" all collapse to "macys". Prefix matching is only
    allowed for chain names of 6+ characters, so short names like "h m"
    (H&M) cannot swallow unrelated boutiques.
    """
    slug = _slug(store_name)
    compact = slug.replace(" ", "")
    for chain in KNOWN_CHAINS:
        chain_compact = chain.replace(" ", "")
        if compact == chain_compact:
            return True
        if len(chain_compact) >= 6 and compact.startswith(chain_compact):
            return True
    if _STORE_LOCATOR_RE.search(html or "") and (html or "").lower().count("<li") > 30:
        return True
    return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_extract_platform.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/scrapebot/extract.py tests/test_extract_platform.py
git commit -m "feat: platform fingerprinting and chain detection"
```

---

## Task 7: Product extraction from Shopify feeds, JSON-LD, and HTML

**Files:**
- Modify: `src/scrapebot/extract.py`
- Test: `tests/test_extract_products.py`
- Create: `tests/fixtures/shopify_products.json`, `tests/fixtures/jsonld_product.html`

- [ ] **Step 1: Save real fixtures from an actual prospect site**

```bash
curl -s -A "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/125.0 Safari/537.36" \
  "https://www.monkeesofnaples.com/products.json?limit=5" -o tests/fixtures/shopify_products.json
.venv/bin/python -c "import json;d=json.load(open('tests/fixtures/shopify_products.json'));print(len(d['products']),'products'); print(d['products'][0]['title'])"
```

Expected: `5 products` and a real product title. If this site is unreachable, substitute any Shopify domain from `data/fl-prospects.csv` — `www.purplepoppy.com` and `www.keepboutique.com` both work.

Create `tests/fixtures/jsonld_product.html` by hand:

```html
<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Product","name":"Ribbed Wool Cardigan",
 "description":"A soft ribbed cardigan.",
 "offers":{"@type":"Offer","price":"248.00","priceCurrency":"USD"}}
</script>
</head><body>
<script type="application/ld+json">{"@type":"BreadcrumbList","itemListElement":[]}</script>
<h1>Ribbed Wool Cardigan</h1>
</body></html>
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_extract_products.py`:

```python
import json
from pathlib import Path

from scrapebot.extract import products_from_shopify_feed, products_from_jsonld

FIXTURES = Path(__file__).parent / "fixtures"


def test_products_from_shopify_feed_parses_real_response():
    data = json.loads((FIXTURES / "shopify_products.json").read_text())
    products = products_from_shopify_feed(data)

    assert len(products) == len(data["products"])
    first = products[0]
    assert first.title == data["products"][0]["title"]
    assert first.price is not None and first.price > 0
    assert isinstance(first.tags, list)


def test_products_from_shopify_feed_uses_lowest_variant_price():
    data = {"products": [{
        "title": "Sweater", "product_type": "Knitwear", "tags": ["fall"],
        "body_html": "<p>Warm</p>",
        "variants": [{"price": "180.00"}, {"price": "120.00"}],
    }]}
    p = products_from_shopify_feed(data)[0]
    assert p.price == 120.0
    assert p.description == "<p>Warm</p>"


def test_products_from_shopify_feed_tolerates_nulls_and_no_variants():
    data = {"products": [
        {"title": "No body", "body_html": None, "tags": None, "variants": []},
        {"title": None, "variants": [{"price": "10.00"}]},
    ]}
    products = products_from_shopify_feed(data)
    assert products[0].title == "No body" and products[0].price is None
    assert products[1].title == ""


def test_products_from_shopify_feed_handles_empty_payload():
    assert products_from_shopify_feed({}) == []
    assert products_from_shopify_feed({"products": []}) == []


def test_products_from_jsonld_picks_product_blocks_only():
    html = (FIXTURES / "jsonld_product.html").read_text()
    products = products_from_jsonld(html)
    assert len(products) == 1
    assert products[0].title == "Ribbed Wool Cardigan"
    assert products[0].price == 248.0


def test_products_from_jsonld_survives_malformed_json():
    html = '<script type="application/ld+json">{not valid json</script>'
    assert products_from_jsonld(html) == []
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_extract_products.py -v`
Expected: FAIL — `ImportError: cannot import name 'products_from_shopify_feed'`

- [ ] **Step 4: Write the implementation**

Append to `src/scrapebot/extract.py` (add `import json` at the top of the file):

```python
def products_from_shopify_feed(data: dict) -> list[Product]:
    """Parse a Shopify /products.json payload. Tolerates null fields throughout."""
    out = []
    for raw in (data or {}).get("products") or []:
        variant_prices = [
            parse_price(v.get("price")) for v in (raw.get("variants") or [])
        ]
        prices = [p for p in variant_prices if p]
        tags = raw.get("tags")
        out.append(Product(
            title=raw.get("title") or "",
            price=min(prices) if prices else None,
            product_type=raw.get("product_type") or "",
            tags=tags if isinstance(tags, list) else [],
            description=raw.get("body_html") or "",
        ))
    return out


def _jsonld_blocks(html: str) -> list:
    """Every parseable JSON-LD block in the page, flattened out of @graph wrappers."""
    blocks = []
    for raw in re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html or "", re.S | re.I,
    ):
        try:
            parsed = json.loads(raw.strip())
        except (ValueError, TypeError):
            continue
        items = parsed if isinstance(parsed, list) else [parsed]
        for item in items:
            if isinstance(item, dict):
                blocks.extend(item.get("@graph", [item]))
    return [b for b in blocks if isinstance(b, dict)]


def products_from_jsonld(html: str) -> list[Product]:
    """Products declared via schema.org JSON-LD."""
    out = []
    for block in _jsonld_blocks(html):
        types = block.get("@type", "")
        types = types if isinstance(types, list) else [types]
        if "Product" not in types:
            continue
        offers = block.get("offers") or {}
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        out.append(Product(
            title=block.get("name") or "",
            price=parse_price(offers.get("price") if isinstance(offers, dict) else None),
            description=block.get("description") or "",
        ))
    return out
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_extract_products.py -v`
Expected: 6 passed

- [ ] **Step 6: Commit**

```bash
git add src/scrapebot/extract.py tests/test_extract_products.py tests/fixtures/
git commit -m "feat: parse products from Shopify feeds and JSON-LD"
```

---

## Task 8: Page text, about snippet, and wholesale page

**Files:**
- Modify: `src/scrapebot/extract.py`
- Test: `tests/test_extract_pages.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_extract_pages.py`:

```python
from scrapebot.models import Page
from scrapebot.extract import html_to_text, about_snippet, find_wholesale_page, internal_links


def test_html_to_text_strips_tags_scripts_and_styles():
    html = """
      <html><head><style>.a{color:red}</style><script>var x=1;</script></head>
      <body><h1>Hello</h1><p>World  of   knits</p></body></html>
    """
    text = html_to_text(html)
    assert "Hello World of knits" == text
    assert "var x" not in text and "color:red" not in text


def test_about_snippet_prefers_an_about_page():
    pages = [
        Page(url="https://x.com", html="", text="Home page text"),
        Page(url="https://x.com/pages/about-us", html="", text="We are a family boutique in Naples."),
    ]
    assert about_snippet(pages).startswith("We are a family boutique")


def test_about_snippet_falls_back_to_meta_description():
    pages = [Page(
        url="https://x.com",
        html='<meta name="description" content="Curated womenswear since 1998.">',
        text="nav home shop",
    )]
    assert about_snippet(pages) == "Curated womenswear since 1998."


def test_about_snippet_truncates_to_300_chars():
    pages = [Page(url="https://x.com/about", html="", text="y" * 900)]
    assert len(about_snippet(pages)) <= 303


def test_about_snippet_empty_when_nothing_found():
    assert about_snippet([]) == ""


def test_find_wholesale_page_matches_path_or_link_text():
    pages = [
        Page(url="https://x.com", html='<a href="/pages/stockists">Our Stockists</a>', text=""),
        Page(url="https://x.com/pages/wholesale", html="", text=""),
    ]
    assert find_wholesale_page(pages) == "https://x.com/pages/wholesale"


def test_find_wholesale_page_returns_empty_when_absent():
    assert find_wholesale_page([Page(url="https://x.com", html="<a href='/cart'>Cart</a>", text="")]) == ""


def test_internal_links_are_absolute_same_domain_and_deduped():
    html = """
      <a href="/shop">Shop</a><a href="/shop">Shop again</a>
      <a href="https://x.com/about">About</a>
      <a href="https://other.com/x">Other</a>
      <a href="mailto:a@b.com">Mail</a><a href="#top">Top</a>
    """
    links = internal_links(html, base_url="https://x.com", domain="x.com")
    assert links == ["https://x.com/shop", "https://x.com/about"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_extract_pages.py -v`
Expected: FAIL — `ImportError: cannot import name 'html_to_text'`

- [ ] **Step 3: Write the implementation**

Append to `src/scrapebot/extract.py`. Three changes at the top of the file first:

1. Add `from urllib.parse import urljoin, urlparse`
2. Add `from bs4 import BeautifulSoup`
3. Change `from .models import Product` to `from .models import Page, Product` — the
   functions below annotate `list[Page]`, so `Page` must be imported.

Then append:

```python
WHOLESALE_RE = re.compile(r"wholesale|stockist|trade[\-_ ]?account|retailer|become[\-_ ]a", re.I)
ABOUT_RE = re.compile(r"/about|/our-story|/pages/about", re.I)
META_DESC_RE = re.compile(
    r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)["\']', re.I
)


def html_to_text(html: str) -> str:
    """Visible text with scripts, styles and whitespace runs removed."""
    soup = BeautifulSoup(html or "", "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" ")).strip()


def about_snippet(pages: list[Page], limit: int = 300) -> str:
    """Text from an About page, else the meta description. Truncated."""
    for page in pages:
        if ABOUT_RE.search(page.url) and page.text:
            return page.text[:limit].strip()
    for page in pages:
        m = META_DESC_RE.search(page.html or "")
        if m and m.group(1).strip():
            return m.group(1).strip()[:limit]
    return ""


def find_wholesale_page(pages: list[Page]) -> str:
    """URL of a wholesale/stockist/trade page, if one was visited."""
    for page in pages:
        if WHOLESALE_RE.search(page.url):
            return page.url
    return ""


def internal_links(html: str, base_url: str, domain: str) -> list[str]:
    """Absolute, deduplicated, same-domain http(s) links from a page."""
    soup = BeautifulSoup(html or "", "lxml")
    out: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        url = urljoin(base_url, href).split("#")[0].rstrip("/")
        host = urlparse(url).netloc.lower()
        host = host[4:] if host.startswith("www.") else host
        if host != domain or not url.startswith("http"):
            continue
        if url not in out:
            out.append(url)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_extract_pages.py -v`
Expected: 8 passed

- [ ] **Step 5: Run the whole extract suite**

Run: `.venv/bin/pytest tests/ -v`
Expected: all tests pass, 77 total (4 models + 11 resolve + 29 knit + 5 price + 7 contacts
+ 7 platform + 6 products + 8 pages).

- [ ] **Step 6: Commit**

```bash
git add src/scrapebot/extract.py tests/test_extract_pages.py
git commit -m "feat: page text, about snippet, wholesale page and link extraction"
```

---

## Task 9: The Fetcher — cache, robots, rate limit, retry

**Files:**
- Create: `src/scrapebot/fetch.py`
- Test: `tests/test_fetch.py`

The `transport` parameter makes this testable with zero network calls. Never bypass it.

- [ ] **Step 1: Write the failing test**

Create `tests/test_fetch.py`:

```python
import pytest

from scrapebot.fetch import Fetcher


def make_transport(responses, calls=None):
    """responses: {url: (status, body)} or an Exception to raise."""
    def transport(url, headers, verify, timeout):
        if calls is not None:
            calls.append((url, verify))
        r = responses.get(url, (404, ""))
        if isinstance(r, Exception):
            raise r
        return (r[0], r[1], url)
    return transport


def test_get_returns_body_on_success(tmp_path):
    f = Fetcher(cache_dir=tmp_path, delay=0,
                transport=make_transport({"https://x.com": (200, "<html>hi</html>")}))
    res = f.get("https://x.com")
    assert res.ok and res.body == "<html>hi</html>" and res.status_code == 200


def test_get_caches_and_does_not_refetch(tmp_path):
    calls = []
    f = Fetcher(cache_dir=tmp_path, delay=0,
                transport=make_transport({"https://x.com": (200, "body")}, calls))
    f.get("https://x.com")
    second = f.get("https://x.com")
    assert len(calls) == 1, "second call must be served from cache"
    assert second.from_cache is True and second.body == "body"


def test_get_records_403_without_raising(tmp_path):
    f = Fetcher(cache_dir=tmp_path, delay=0,
                transport=make_transport({"https://x.com": (403, "")}))
    res = f.get("https://x.com")
    assert res.ok is False and res.status_code == 403


def test_get_retries_then_records_error(tmp_path):
    calls = []
    f = Fetcher(cache_dir=tmp_path, delay=0, retries=2,
                transport=make_transport({"https://x.com": TimeoutError("timed out")}, calls))
    res = f.get("https://x.com")
    assert res.ok is False
    assert "TimeoutError" in res.error
    assert len(calls) == 3, "initial attempt plus 2 retries"


def test_ssl_failure_retries_with_verification_disabled(tmp_path):
    calls = []

    def transport(url, headers, verify, timeout):
        calls.append((url, verify))
        if verify:
            raise Exception("SSLV3_ALERT_HANDSHAKE_FAILURE")
        return (200, "insecure body", url)

    f = Fetcher(cache_dir=tmp_path, delay=0, retries=0, transport=transport)
    res = f.get("https://badssl.com")
    assert res.ok and res.body == "insecure body"
    assert res.ssl_bypassed is True, "the weakened check must be visible in the result"
    assert calls[-1][1] is False


def test_robots_disallow_blocks_the_request(tmp_path):
    responses = {
        "https://x.com/robots.txt": (200, "User-agent: *\nDisallow: /private"),
        "https://x.com/private/page": (200, "secret"),
    }
    f = Fetcher(cache_dir=tmp_path, delay=0, transport=make_transport(responses))
    res = f.get("https://x.com/private/page")
    assert res.ok is False and res.error == "robots_disallowed"


def test_robots_allows_when_file_is_missing(tmp_path):
    f = Fetcher(cache_dir=tmp_path, delay=0,
                transport=make_transport({"https://x.com/page": (200, "fine")}))
    assert f.get("https://x.com/page").ok is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_fetch.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scrapebot.fetch'`

- [ ] **Step 3: Write the implementation**

Create `src/scrapebot/fetch.py`:

```python
"""The only module that touches the network."""
import hashlib
import json
import time
import urllib.robotparser
from pathlib import Path
from urllib.parse import urlparse

from .models import FetchResult

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)
SSL_MARKERS = ("SSL", "CERTIFICATE_VERIFY_FAILED", "HANDSHAKE")


def _requests_transport(url, headers, verify, timeout):
    import requests
    r = requests.get(url, headers=headers, verify=verify, timeout=timeout,
                     allow_redirects=True)
    return (r.status_code, r.text, r.url)


class Fetcher:
    """Polite, cached HTTP. Never raises for network conditions."""

    def __init__(self, cache_dir, delay: float = 1.5, timeout: int = 20,
                 retries: int = 2, transport=None, respect_robots: bool = True):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.delay = delay
        self.timeout = timeout
        self.retries = retries
        self.respect_robots = respect_robots
        self._transport = transport or _requests_transport
        self._last_request: dict[str, float] = {}
        self._robots: dict[str, object] = {}

    # -- cache -------------------------------------------------------------
    def _cache_path(self, url: str) -> Path:
        host = urlparse(url).netloc or "_"
        digest = hashlib.sha256(url.encode()).hexdigest()[:20]
        d = self.cache_dir / host
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{digest}.json"

    def _read_cache(self, url: str) -> FetchResult | None:
        path = self._cache_path(url)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
        except ValueError:
            return None
        return FetchResult(**data, from_cache=True)

    def _write_cache(self, res: FetchResult) -> None:
        self._cache_path(res.url).write_text(json.dumps({
            "url": res.url, "status_code": res.status_code, "body": res.body,
            "final_url": res.final_url, "error": res.error,
            "ssl_bypassed": res.ssl_bypassed,
        }))

    # -- politeness --------------------------------------------------------
    def _throttle(self, url: str) -> None:
        host = urlparse(url).netloc
        last = self._last_request.get(host)
        if last is not None:
            wait = self.delay - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
        self._last_request[host] = time.monotonic()

    def _allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        parts = urlparse(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            parser = urllib.robotparser.RobotFileParser()
            try:
                status, body, _ = self._transport(
                    origin + "/robots.txt", {"User-Agent": USER_AGENT}, True, self.timeout
                )
                parser.parse(body.splitlines() if status == 200 else [])
            except Exception:
                parser.parse([])          # unreachable robots.txt means allow
            self._robots[origin] = parser
        return self._robots[origin].can_fetch(USER_AGENT, url)

    # -- public ------------------------------------------------------------
    def get(self, url: str) -> FetchResult:
        cached = self._read_cache(url)
        if cached is not None:
            return cached

        if not self._allowed(url):
            return FetchResult(url=url, status_code=None, body="",
                               final_url=url, error="robots_disallowed")

        headers = {"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}
        last_error = ""
        for attempt in range(self.retries + 1):
            self._throttle(url)
            try:
                status, body, final = self._transport(url, headers, True, self.timeout)
                res = FetchResult(url=url, status_code=status, body=body, final_url=final)
                self._write_cache(res)
                return res
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"[:200]
                if any(m in str(exc).upper() for m in SSL_MARKERS):
                    break
                if attempt < self.retries:
                    time.sleep(0.5 * (2 ** attempt))

        if any(m in last_error.upper() for m in SSL_MARKERS):
            try:
                self._throttle(url)
                status, body, final = self._transport(url, headers, False, self.timeout)
                res = FetchResult(url=url, status_code=status, body=body,
                                  final_url=final, ssl_bypassed=True)
                self._write_cache(res)
                return res
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"[:200]

        res = FetchResult(url=url, status_code=None, body="", final_url=url, error=last_error)
        self._write_cache(res)
        return res
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_fetch.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/scrapebot/fetch.py tests/test_fetch.py
git commit -m "feat: polite cached fetcher with robots, retry and SSL fallback"
```

---

## Task 10: Acquisition strategies

**Files:**
- Create: `src/scrapebot/sources.py`
- Test: `tests/test_sources.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_sources.py`:

```python
import json

from scrapebot.models import FetchResult, Target
from scrapebot.sources import shopify_products, sitemap_urls, crawl_pages, acquire


class FakeFetcher:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        entry = self.responses.get(url)
        if entry is None:
            return FetchResult(url=url, status_code=404, body="", final_url=url)
        status, body = entry
        return FetchResult(url=url, status_code=status, body=body, final_url=url)


def feed_page(n, start=0):
    return json.dumps({"products": [
        {"title": f"Item {start+i}", "variants": [{"price": "10.00"}]} for i in range(n)
    ]})


def test_shopify_products_paginates_until_empty():
    f = FakeFetcher({
        "https://x.com/products.json?limit=250&page=1": (200, feed_page(250)),
        "https://x.com/products.json?limit=250&page=2": (200, feed_page(40, 250)),
        "https://x.com/products.json?limit=250&page=3": (200, json.dumps({"products": []})),
    })
    products = shopify_products("x.com", f)
    assert len(products) == 290
    assert products[0].title == "Item 0"


def test_shopify_products_stops_at_page_cap():
    responses = {
        f"https://x.com/products.json?limit=250&page={p}": (200, feed_page(250, 250 * (p - 1)))
        for p in range(1, 12)
    }
    products = shopify_products("x.com", FakeFetcher(responses))
    assert len(products) == 2000, "8 pages x 250 is the cap"


def test_shopify_products_returns_empty_for_non_shopify():
    assert shopify_products("x.com", FakeFetcher({})) == []


def test_shopify_products_ignores_html_served_at_the_feed_url():
    f = FakeFetcher({"https://x.com/products.json?limit=250&page=1": (200, "<html>404</html>")})
    assert shopify_products("x.com", f) == []


def test_sitemap_urls_follows_a_sitemap_index_one_level():
    index = """<?xml version="1.0"?><sitemapindex>
      <sitemap><loc>https://x.com/sitemap_products_1.xml</loc></sitemap>
    </sitemapindex>"""
    child = """<?xml version="1.0"?><urlset>
      <url><loc>https://x.com/products/knit-top</loc></url>
      <url><loc>https://x.com/pages/about</loc></url>
      <url><loc>https://x.com/blogs/news/post</loc></url>
    </urlset>"""
    f = FakeFetcher({
        "https://x.com/sitemap.xml": (200, index),
        "https://x.com/sitemap_products_1.xml": (200, child),
    })
    urls = sitemap_urls("x.com", f)
    assert "https://x.com/products/knit-top" in urls
    assert "https://x.com/pages/about" in urls
    assert "https://x.com/blogs/news/post" not in urls, "blog posts are not relevant"


def test_sitemap_urls_caps_the_result():
    body = "<urlset>" + "".join(
        f"<url><loc>https://x.com/products/p{i}</loc></url>" for i in range(200)
    ) + "</urlset>"
    urls = sitemap_urls("x.com", FakeFetcher({"https://x.com/sitemap.xml": (200, body)}))
    assert len(urls) <= 25


def test_crawl_pages_prioritises_relevant_links_and_caps_pages():
    home = """<html><body>
      <a href="/pages/about">About</a>
      <a href="/collections/sweaters">Shop Sweaters</a>
      <a href="/blogs/news/hello">Blog</a>
      <a href="/pages/contact">Contact</a>
    </body></html>"""
    f = FakeFetcher({
        "https://x.com": (200, home),
        "https://x.com/pages/about": (200, "<p>About us</p>"),
        "https://x.com/collections/sweaters": (200, "<p>Sweaters</p>"),
        "https://x.com/pages/contact": (200, "<p>Contact</p>"),
        "https://x.com/blogs/news/hello": (200, "<p>Blog</p>"),
    })
    pages = crawl_pages("x.com", "https://x.com", f, max_pages=4)
    urls = [p.url for p in pages]
    assert len(pages) == 4
    assert "https://x.com" in urls
    assert "https://x.com/pages/about" in urls
    assert "https://x.com/blogs/news/hello" not in urls, "blogs are deprioritised"


def test_acquire_prefers_the_shopify_feed_and_skips_crawling():
    f = FakeFetcher({
        "https://x.com": (200, "<html>cdn.shopify.com</html>"),
        "https://x.com/products.json?limit=250&page=1": (200, feed_page(3)),
        "https://x.com/products.json?limit=250&page=2": (200, json.dumps({"products": []})),
    })
    got = acquire(Target(domain="x.com", url="https://x.com"), f)
    assert got.source_used == "shopify_feed"
    assert len(got.products) == 3
    assert got.status == "ok"


def test_acquire_marks_blocked_when_homepage_is_403():
    f = FakeFetcher({"https://x.com": (403, "")})
    got = acquire(Target(domain="x.com", url="https://x.com"), f)
    assert got.status == "blocked"


def test_acquire_marks_js_required_when_pages_load_but_no_products_found():
    f = FakeFetcher({"https://x.com": (200, "<html><body><div id='root'></div></body></html>")})
    got = acquire(Target(domain="x.com", url="https://x.com"), f)
    assert got.status == "js_required"
    assert got.pages_fetched >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_sources.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scrapebot.sources'`

- [ ] **Step 3: Write the implementation**

Create `src/scrapebot/sources.py`:

```python
"""Three acquisition strategies, tried in order until one yields products."""
import json
import re

from .extract import (
    detect_platform, html_to_text, internal_links,
    products_from_jsonld, products_from_shopify_feed,
)
from .models import Acquired, Page, Product, Target

FEED_PAGE_CAP = 8
FEED_PAGE_SIZE = 250
MAX_PAGES = 25

RELEVANT_RE = re.compile(
    r"/(product|collection|shop|catalog|pages?/about|about|contact|"
    r"brands?|designers?|wholesale|stockist)", re.I
)
IRRELEVANT_RE = re.compile(
    r"/(blog|news|policies|privacy|terms|refund|shipping|cart|account|login|search)", re.I
)
LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)


def shopify_products(domain: str, fetcher) -> list[Product]:
    """Paginate a Shopify /products.json feed. Empty list if the site isn't Shopify."""
    out: list[Product] = []
    for page in range(1, FEED_PAGE_CAP + 1):
        url = f"https://{domain}/products.json?limit={FEED_PAGE_SIZE}&page={page}"
        res = fetcher.get(url)
        if not res.ok or not res.body.strip().startswith("{"):
            break
        try:
            data = json.loads(res.body)
        except ValueError:
            break
        batch = products_from_shopify_feed(data)
        if not batch:
            break
        out.extend(batch)
    return out


def sitemap_urls(domain: str, fetcher) -> list[str]:
    """Relevant URLs from sitemap.xml, following a sitemap index one level down."""
    res = fetcher.get(f"https://{domain}/sitemap.xml")
    if not res.ok:
        return []
    locs = LOC_RE.findall(res.body)

    if "<sitemapindex" in res.body.lower():
        child_locs: list[str] = []
        for child in locs[:5]:
            child_res = fetcher.get(child)
            if child_res.ok:
                child_locs.extend(LOC_RE.findall(child_res.body))
        locs = child_locs

    keep = [u for u in locs if RELEVANT_RE.search(u) and not IRRELEVANT_RE.search(u)]
    seen: list[str] = []
    for u in keep:
        if u not in seen:
            seen.append(u)
    return seen[:MAX_PAGES]


def _fetch_pages(urls: list[str], fetcher, max_pages: int) -> list[Page]:
    pages: list[Page] = []
    for url in urls[:max_pages]:
        res = fetcher.get(url)
        if res.ok and res.body:
            pages.append(Page(url=url, html=res.body, text=html_to_text(res.body)))
    return pages


def crawl_pages(domain: str, start_url: str, fetcher, max_pages: int = MAX_PAGES) -> list[Page]:
    """Homepage plus prioritised internal links, one level deep."""
    home = fetcher.get(start_url)
    if not home.ok or not home.body:
        return []
    pages = [Page(url=start_url, html=home.body, text=html_to_text(home.body))]

    links = internal_links(home.body, start_url, domain)
    relevant = [u for u in links if RELEVANT_RE.search(u) and not IRRELEVANT_RE.search(u)]
    other = [u for u in links if u not in relevant and not IRRELEVANT_RE.search(u)]
    pages.extend(_fetch_pages(relevant + other, fetcher, max_pages - 1))
    return pages[:max_pages]


def acquire(target: Target, fetcher) -> Acquired:
    """Gather everything available for one store."""
    got = Acquired(domain=target.domain)

    home = fetcher.get(target.url)
    if home.ssl_bypassed:
        got.status = "ssl_bypassed"
    if not home.ok:
        if home.status_code in (401, 403, 429):
            got.status = "blocked"
        elif home.status_code is None:
            got.status = "error"
            got.error = home.error
        else:
            got.status = "error"
            got.error = f"HTTP {home.status_code}"
        return got

    got.pages = [Page(url=target.url, html=home.body, text=html_to_text(home.body))]

    products = shopify_products(target.domain, fetcher)
    if products:
        got.source_used = "shopify_feed"
        got.products = products
        got.pages_fetched = len(got.pages)
        return got

    urls = sitemap_urls(target.domain, fetcher)
    if urls:
        got.source_used = "sitemap"
        got.pages.extend(_fetch_pages(urls, fetcher, MAX_PAGES - 1))
    else:
        got.source_used = "crawl"
        got.pages = crawl_pages(target.domain, target.url, fetcher) or got.pages

    for page in got.pages:
        got.products.extend(products_from_jsonld(page.html))

    got.pages_fetched = len(got.pages)
    if not got.products:
        platform = detect_platform(home.body)
        got.status = "js_required" if platform in ("wix", "custom/unknown") else "ok"
    return got
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_sources.py -v`
Expected: 29 passed

- [ ] **Step 5: Commit**

```bash
git add src/scrapebot/sources.py tests/test_sources.py
git commit -m "feat: Shopify feed, sitemap and crawl acquisition strategies"
```

---

## Task 11: Aggregation into a CSV row

**Files:**
- Create: `src/scrapebot/aggregate.py`
- Test: `tests/test_aggregate.py`

Column names here must exactly match the spec's output table.

- [ ] **Step 1: Write the failing test**

Create `tests/test_aggregate.py`:

```python
from scrapebot.aggregate import OUTPUT_COLUMNS, build_record, build_skipped_record
from scrapebot.models import Acquired, Page, Product, Target


def sample_acquired():
    return Acquired(
        domain="monkeesofnaples.com",
        source_used="shopify_feed",
        status="ok",
        pages_fetched=1,
        products=[
            Product(title="Cher Sweater in Eggnog", price=139.0),
            Product(title="Quinn Cardigan in Chocolate", price=698.0),
            Product(title="Leather Handbag", price=450.0),
            Product(title="Silk Scarf", price=39.0),
        ],
        pages=[Page(
            url="https://monkeesofnaples.com",
            html='<a href="mailto:hi@monkeesofnaples.com">Mail</a>'
                 '<a href="https://www.instagram.com/monkeesofnaples/">IG</a>'
                 '<script src="https://cdn.shopify.com/x.js"></script>',
            text="Boutique in Naples",
        )],
    )


def test_build_record_computes_knit_signals():
    target = Target(domain="monkeesofnaples.com", url="https://monkeesofnaples.com",
                    rows=[{"store_name": "Monkee's of Naples", "website": "https://monkeesofnaples.com"}])
    rec = build_record(target, sample_acquired())

    assert rec["knit_count"] == 2
    assert rec["product_count"] == 4
    assert rec["knit_share"] == "50%"
    assert "Cher Sweater in Eggnog" in rec["knit_examples"]
    assert rec["knit_price_min"] == 139.0
    assert rec["knit_price_max"] == 698.0
    assert rec["price_min"] == 39.0 and rec["price_max"] == 698.0


def test_build_record_carries_original_columns_and_contacts():
    target = Target(domain="monkeesofnaples.com", url="https://monkeesofnaples.com",
                    rows=[{"store_name": "Monkee's of Naples", "address": "Naples FL",
                           "website": "https://monkeesofnaples.com"}])
    rec = build_record(target, sample_acquired())

    assert rec["store_name"] == "Monkee's of Naples"
    assert rec["address"] == "Naples FL"
    assert rec["emails"] == "hi@monkeesofnaples.com"
    assert rec["instagram"] == "https://www.instagram.com/monkeesofnaples/"
    assert rec["platform"] == "shopify"
    assert rec["is_chain"] is False
    assert rec["scrape_status"] == "ok"
    assert rec["source_used"] == "shopify_feed"
    assert rec["fetched_at"]


def test_build_record_handles_a_store_with_no_products():
    target = Target(domain="x.com", url="https://x.com", rows=[{"store_name": "X"}])
    rec = build_record(target, Acquired(domain="x.com", status="js_required"))
    assert rec["product_count"] == 0
    assert rec["knit_count"] == 0
    assert rec["knit_share"] == ""
    assert rec["knit_examples"] == ""
    assert rec["price_min"] == "" and rec["knit_price_min"] == ""


def test_build_record_flags_chains():
    target = Target(domain="macys.com", url="https://macys.com", rows=[{"store_name": "Macy's"}])
    rec = build_record(target, Acquired(domain="macys.com", status="blocked"))
    assert rec["is_chain"] is True
    assert rec["scrape_status"] == "blocked"


def test_build_record_caps_knit_examples_at_five():
    target = Target(domain="x.com", url="https://x.com", rows=[{"store_name": "X"}])
    acq = Acquired(domain="x.com", products=[
        Product(title=f"Sweater {i}", price=10.0) for i in range(9)
    ])
    rec = build_record(target, acq)
    assert rec["knit_count"] == 9
    assert len(rec["knit_examples"].split("; ")) == 5


def test_build_skipped_record_produces_a_full_row():
    rec = build_skipped_record({"store_name": "No Site", "website": ""}, "no_website")
    assert rec["scrape_status"] == "no_website"
    assert rec["store_name"] == "No Site"
    assert set(rec) == set(OUTPUT_COLUMNS), "skipped rows have every output column"


def test_every_record_has_exactly_the_output_columns():
    target = Target(domain="x.com", url="https://x.com", rows=[{"store_name": "X"}])
    rec = build_record(target, Acquired(domain="x.com"))
    assert set(rec) == set(OUTPUT_COLUMNS)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_aggregate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scrapebot.aggregate'`

- [ ] **Step 3: Write the implementation**

Create `src/scrapebot/aggregate.py`:

```python
"""Roll one store's acquired data into a single flat CSV row."""
from datetime import datetime, timezone

from . import extract
from .models import Acquired, Target

ORIGINAL_COLUMNS = [
    "store_name", "latitude", "longitude", "website", "potential_conflict",
    "nearest_stockist", "drive_minutes", "distance_miles", "address",
    "found_near", "types", "place_id",
]

SCRAPED_COLUMNS = [
    "domain", "scrape_status", "source_used", "platform", "is_chain",
    "pages_fetched", "product_count", "knit_count", "knit_share", "knit_examples",
    "knit_price_min", "knit_price_max", "price_min", "price_max", "price_median",
    "emails", "phone", "instagram", "facebook", "wholesale_page",
    "about_snippet", "fetched_at",
]

OUTPUT_COLUMNS = ORIGINAL_COLUMNS + SCRAPED_COLUMNS

MAX_KNIT_EXAMPLES = 5


def _blank_record() -> dict:
    return {col: "" for col in OUTPUT_COLUMNS}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def build_skipped_record(row: dict, reason: str) -> dict:
    """A full-width row for a store that was never fetched."""
    rec = _blank_record()
    for col in ORIGINAL_COLUMNS:
        rec[col] = row.get(col, "")
    rec["domain"] = ""
    rec["scrape_status"] = reason
    rec["is_chain"] = False
    rec["pages_fetched"] = 0
    rec["product_count"] = 0
    rec["knit_count"] = 0
    rec["fetched_at"] = _now()
    return rec


def build_record(target: Target, acquired: Acquired) -> dict:
    """One output row per store."""
    rec = _blank_record()
    primary = target.rows[0] if target.rows else {}
    for col in ORIGINAL_COLUMNS:
        rec[col] = primary.get(col, "")

    all_html = " ".join(p.html for p in acquired.pages)
    knits = extract.knit_products(acquired.products)
    p_min, p_max, p_med = extract.price_stats(acquired.products)
    k_min, k_max, _ = extract.price_stats(knits)

    rec["domain"] = target.domain
    rec["scrape_status"] = acquired.status
    rec["source_used"] = acquired.source_used
    rec["platform"] = extract.detect_platform(all_html)
    rec["is_chain"] = extract.is_chain(primary.get("store_name", ""), all_html)
    rec["pages_fetched"] = acquired.pages_fetched
    rec["product_count"] = len(acquired.products)
    rec["knit_count"] = len(knits)
    rec["knit_share"] = (
        f"{round(100 * len(knits) / len(acquired.products))}%" if acquired.products else ""
    )
    rec["knit_examples"] = "; ".join(p.title for p in knits[:MAX_KNIT_EXAMPLES])
    rec["knit_price_min"] = k_min if k_min is not None else ""
    rec["knit_price_max"] = k_max if k_max is not None else ""
    rec["price_min"] = p_min if p_min is not None else ""
    rec["price_max"] = p_max if p_max is not None else ""
    rec["price_median"] = p_med if p_med is not None else ""
    rec["emails"] = "; ".join(extract.extract_emails(all_html)[:5])
    rec["phone"] = "; ".join(extract.extract_phones(all_html)[:3])

    socials = extract.extract_socials(all_html)
    rec["instagram"] = socials["instagram"]
    rec["facebook"] = socials["facebook"]
    rec["wholesale_page"] = extract.find_wholesale_page(acquired.pages)
    rec["about_snippet"] = extract.about_snippet(acquired.pages)
    rec["fetched_at"] = _now()
    return rec
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_aggregate.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/scrapebot/aggregate.py tests/test_aggregate.py
git commit -m "feat: aggregate acquired data into enriched CSV rows"
```

---

## Task 12: CLI orchestration and run report

**Files:**
- Create: `src/scrapebot/cli.py`, `src/scrapebot/__main__.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli.py`:

```python
import csv
import json

from scrapebot.cli import run
from scrapebot.models import FetchResult


class FakeFetcher:
    def __init__(self, responses):
        self.responses = responses

    def get(self, url):
        entry = self.responses.get(url)
        if entry is None:
            return FetchResult(url=url, status_code=404, body="", final_url=url)
        status, body = entry
        return FetchResult(url=url, status_code=status, body=body, final_url=url)


def test_run_writes_csv_json_and_report(tmp_path):
    src = tmp_path / "in.csv"
    src.write_text(
        "store_name,website,address\n"
        "Monkees,https://monkees.com,Naples FL\n"
        "No Site,,Naples FL\n"
        "Insta Only,https://www.instagram.com/x/,Naples FL\n"
    )
    out_dir = tmp_path / "out"
    raw_dir = tmp_path / "raw"

    fetcher = FakeFetcher({
        "https://monkees.com": (200, "<html>cdn.shopify.com</html>"),
        "https://monkees.com/products.json?limit=250&page=1": (200, json.dumps({"products": [
            {"title": "Cher Sweater in Eggnog", "variants": [{"price": "139.00"}]},
            {"title": "Leather Bag", "variants": [{"price": "450.00"}]},
        ]})),
        "https://monkees.com/products.json?limit=250&page=2": (200, json.dumps({"products": []})),
    })

    run(str(src), str(out_dir), str(raw_dir), fetcher=fetcher)

    rows = list(csv.DictReader(open(out_dir / "in-enriched.csv")))
    assert len(rows) == 3, "every input row appears in the output, including skipped ones"

    by_name = {r["store_name"]: r for r in rows}
    assert by_name["Monkees"]["knit_count"] == "1"
    assert by_name["Monkees"]["knit_examples"] == "Cher Sweater in Eggnog"
    assert by_name["No Site"]["scrape_status"] == "no_website"
    assert by_name["Insta Only"]["scrape_status"] == "social_only"

    raw = json.loads((raw_dir / "monkees.com.json").read_text())
    assert len(raw["products"]) == 2
    assert raw["domain"] == "monkees.com"

    report = (out_dir / "run-report.md").read_text()
    assert "no_website" in report and "Total input rows" in report


def test_run_never_aborts_when_one_site_fails(tmp_path):
    src = tmp_path / "in.csv"
    src.write_text(
        "store_name,website\n"
        "Broken,https://broken.com\n"
        "Working,https://working.com\n"
    )
    fetcher = FakeFetcher({
        "https://broken.com": (403, ""),
        "https://working.com": (200, "<html><p>Hello</p></html>"),
    })
    run(str(src), str(tmp_path / "out"), str(tmp_path / "raw"), fetcher=fetcher)

    rows = list(csv.DictReader(open(tmp_path / "out" / "in-enriched.csv")))
    statuses = {r["store_name"]: r["scrape_status"] for r in rows}
    assert statuses["Broken"] == "blocked"
    assert statuses["Working"] in ("ok", "js_required")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scrapebot.cli'`

- [ ] **Step 3: Write the implementation**

Create `src/scrapebot/cli.py`:

```python
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
        "pages": [{"url": p.url, "text": p.text[:5000]} for p in acquired.pages],
        "source_rows": target.rows,
    }
    (raw_dir / f"{target.domain}.json").write_text(json.dumps(payload, indent=1))


def _write_report(out_dir: Path, records: list[dict], target_count: int) -> None:
    statuses = Counter(r["scrape_status"] for r in records)
    js_required = [r["domain"] for r in records if r["scrape_status"] == "js_required"]
    errors = [(r["domain"], r["scrape_status"]) for r in records
              if r["scrape_status"] in ("error", "blocked")]
    with_knits = sum(1 for r in records if r["knit_count"] > 0)  # always an int here

    lines = [
        "# Scrape Run Report", "",
        f"- Total input rows: {len(records)}",
        f"- Stores fetched: {target_count}",
        f"- Stores showing knitwear: {with_knits}", "",
        "## Status counts", "",
    ]
    lines += [f"- `{status}`: {count}" for status, count in statuses.most_common()]
    lines += ["", "## Needs a headless browser (js_required)", ""]
    lines += [f"- {d}" for d in js_required] or ["- none"]
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
```

Create `src/scrapebot/__main__.py`:

```python
from .cli import main

main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: 2 passed

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/pytest`
Expected: all tests pass, 103 total (77 from Task 8, plus 7 fetch + 10 sources
+ 7 aggregate + 2 cli). No network was used by any test.

- [ ] **Step 6: Commit**

```bash
git add src/scrapebot/cli.py src/scrapebot/__main__.py tests/test_cli.py
git commit -m "feat: CLI orchestration with enriched CSV, raw JSON and run report"
```

---

## Task 13: First real run and README

**Files:**
- Create: `README.md`
- Produces: `data/out/fl-prospects-enriched.csv`, `data/out/run-report.md`, `data/raw/*.json`

- [ ] **Step 1: Run against the real prospect list**

```bash
cd /Users/webadmin/Automation/scrapping-bot
PYTHONPATH=src .venv/bin/python -m scrapebot data/fl-prospects.csv
```

Expected: progress lines for 65 domains, ending with `Wrote 78 rows to data/out/fl-prospects-enriched.csv`. Takes several minutes on the first run because of the 1.5s per-domain delay; subsequent runs are near-instant from cache.

- [ ] **Step 2: Verify the output row count matches the input**

```bash
.venv/bin/python -c "
import csv
rows = list(csv.DictReader(open('data/out/fl-prospects-enriched.csv')))
print('output rows:', len(rows))
assert len(rows) == 78, f'expected 78 rows, got {len(rows)}'
print('rows with knit hits:', sum(1 for r in rows if (r['knit_count'] or '0') not in ('', '0')))
"
```

Expected: `output rows: 78` and roughly 24+ stores with knit hits, matching the reconnaissance figure in the spec.

- [ ] **Step 3: Read the run report**

Run: `cat data/out/run-report.md`

Expected: status counts, and a named list of `js_required` domains. **This list is the deliverable that decides whether a Playwright pass is worth building** — if it is more than a handful of stores, that becomes a follow-up plan.

- [ ] **Step 4: Spot-check a known store against reconnaissance**

```bash
.venv/bin/python -c "
import csv
rows = {r['domain']: r for r in csv.DictReader(open('data/out/fl-prospects-enriched.csv'))}
r = rows['monkeesofnaples.com']
print(r['knit_count'], r['knit_examples'], r['knit_price_min'], r['knit_price_max'])
"
```

Expected: a knit count of about 3 and titles including `Cher Sweater in Eggnog`, matching what reconnaissance found. A wildly different number means extraction regressed.

- [ ] **Step 5: Write the README**

Create `README.md`:

````markdown
# Store Website Scraper

Collects evidence about retail prospects from their websites: what they sell
(especially knitwear, with prices) and how to contact them. Built for qualifying
wholesale accounts for a knit sweater brand.

The bot **collects evidence only**. It does not judge whether a store is a good
prospect — that is a human decision made against the collected data.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Run

```bash
PYTHONPATH=src .venv/bin/python -m scrapebot data/fl-prospects.csv
```

The input CSV needs a `website` column. Any other columns are passed through
to the output.

Options: `--out` (default `data/out`), `--raw` (default `data/raw`).

## Output

- `data/out/<input>-enriched.csv` — one row per input store, original columns
  plus knitwear signals, prices, and contacts.
- `data/raw/<domain>.json` — everything captured, so re-judging later never
  requires re-scraping.
- `data/out/run-report.md` — status counts and the list of sites that need a
  headless browser.

Key columns: `knit_count`, `knit_examples`, `knit_price_min`/`max` (the price
band of their sweaters specifically), `emails`, `wholesale_page`, `is_chain`.

## Behaviour

Responses are cached in `data/.cache`, so re-runs are instant. Delete that
directory to force a fresh fetch.

The bot respects `robots.txt`, waits 1.5s between requests to the same domain,
reads only public pages, and logs in nowhere.

## Tests

```bash
.venv/bin/pytest
```

All tests run offline against fixtures saved from real prospect sites.
````

- [ ] **Step 6: Commit**

```bash
git add README.md
git commit -m "docs: add README with setup, usage and output reference"
```

- [ ] **Step 7: Review the results with the user**

Report back: how many stores were successfully scraped, how many show knitwear,
how many need a headless browser, and the price bands found. Ask whether a
Playwright follow-up pass is worth building based on the `js_required` count.

---

## Self-Review Notes

**Spec coverage check:**

| Spec section | Task |
|---|---|
| Input partitioning (blank / social / duplicates) | Task 2 |
| Shopify feed with pagination | Task 10 |
| Sitemap strategy | Task 10 |
| Crawl strategy with link prioritisation | Task 10 |
| Knit matching retaining context | Task 3 |
| Price parsing, `knit_price_min`/`max` | Tasks 4, 11 |
| Contacts (email, phone, socials) | Task 5 |
| Wholesale page, about snippet | Task 8 |
| Platform fingerprint, chain detection | Task 6 |
| JSON-LD product extraction | Task 7 |
| Enriched CSV with all spec columns | Task 11 |
| Raw JSON per store | Task 12 |
| Run report naming `js_required` domains | Task 12 |
| Every store produces a row | Tasks 11, 12 (asserted in tests) |
| robots.txt, rate limit, retry, cache | Task 9 |
| `ssl_bypassed` visible in output | Task 9 |
| Null `body_html` tolerance | Task 3, Task 7 (both tested) |

No spec requirement is unimplemented. Headless-browser rendering is explicitly
out of scope per the spec; Task 13 Step 3 produces the data needed to decide
whether to plan it as follow-up work.

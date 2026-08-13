"""Pure extraction functions. No network, no file I/O, no global state."""
import html
import json
import re
import statistics

from .models import Product

KNIT_TERMS = (
    "knit", "knitwear", "sweater", "cardigan", "pullover", "jumper",
    "cashmere", "merino", "wool", "crewneck", "turtleneck", "sweatshirt",
    "poncho", "shawl",
)
KNIT_RE = re.compile(r"\b(" + "|".join(KNIT_TERMS) + r")s?\b", re.I)

# Terms too generic to qualify a product on their own: "wool" and "shawl" also
# appear routinely on woven (non-knit) goods — coats, trousers, vests.
WEAK_KNIT_TERMS = frozenset({"wool", "shawl"})

WOVEN_GARMENT_TERMS = (
    "coat", "jacket", "blazer", "trouser", "trousers", "pant", "pants",
    "vest", "hat", "glove", "gloves", "sock", "socks", "bag", "blanket",
    "rug", "skirt", "short", "shorts", "jean", "jeans", "denim",
)
WOVEN_GARMENT_RE = re.compile(r"\b(" + "|".join(WOVEN_GARMENT_TERMS) + r")\b", re.I)

_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def _clean_html(text: str) -> str:
    """Plain text from raw HTML: strip tags, unescape entities, collapse whitespace."""
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    return _WHITESPACE_RE.sub(" ", text).strip()


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


def product_blob(p: Product) -> str:
    """Searchable text for one product. Tolerates null fields from Shopify feeds.

    `description` is raw body_html straight from the Shopify feed, so it is
    cleaned to plain text (tags stripped, entities unescaped, whitespace
    collapsed) BEFORE truncation — otherwise markup can consume the whole
    400-char budget and hide the fabric line that follows it. `Product.description`
    itself is left untouched; only this searchable copy is cleaned.
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

    A product is suppressed when every matched term is "weak" (wool, shawl —
    terms that also appear routinely on woven, non-knit goods) AND the title
    names a clearly woven garment (coat, pant, vest, ...). Any strong term
    present is enough to keep the product regardless of title.
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
    locations. Deliberately simple - it will miss chains not on the list.

    Names are compared with punctuation and spaces removed, so "Macy's", "MACYS"
    and "macy s" all collapse to "macys". Prefix matching is only allowed for
    chain names of 6+ characters, so short names like "h m" (H&M) cannot swallow
    unrelated boutiques.
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

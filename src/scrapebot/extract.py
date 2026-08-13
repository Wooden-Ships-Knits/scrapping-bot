"""Pure extraction functions. No network, no file I/O, no global state."""
import html
import re

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

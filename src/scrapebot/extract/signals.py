"""Prospect signals for the summary: knitwear and national chains.

These judge the data rather than collect it. They stay simple and conservative,
and will move into the analysis phase (see roadmap, "Next phase").
"""

import re

from ..models import Product
from .text import clean_html

KNIT_TERMS = (
    "knit", "knitwear", "sweater", "cardigan", "pullover", "jumper",
    "cashmere", "merino", "wool", "crewneck", "turtleneck", "sweatshirt",
    "poncho", "shawl",
)  # fmt: skip
KNIT_RE = re.compile(r"\b(" + "|".join(KNIT_TERMS) + r")s?\b", re.I)

# Terms too generic to qualify a product on their own: "wool" and "shawl" also
# appear routinely on woven (non-knit) goods — coats, trousers, vests.
WEAK_KNIT_TERMS = frozenset({"wool", "shawl"})

WOVEN_GARMENT_TERMS = (
    "coat", "jacket", "blazer", "trouser", "trousers", "pant", "pants",
    "bag", "blanket", "rug", "skirt", "short", "shorts", "jean", "jeans",
    "denim", "vest",
)  # fmt: skip
WOVEN_GARMENT_RE = re.compile(r"\b(" + "|".join(WOVEN_GARMENT_TERMS) + r")\b", re.I)

KNOWN_CHAINS = (
    "h m", "macys", "charlotte russe", "windsor", "bealls",
    "brandy melville", "four seasons", "nordstrom", "dillards",
    "talbots", "chicos", "anthropologie", "j crew",
)  # fmt: skip
_STORE_LOCATOR_RE = re.compile(r"find a store|store locator|all locations|our stores", re.I)


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
    """Searchable text for one product.

    The description is cleaned to plain text (tags stripped, entities unescaped,
    whitespace collapsed) BEFORE truncation — otherwise markup can consume the
    whole 400-char budget and hide the fabric line that follows it.
    """
    parts = [
        p.title,
        p.product_type,
        " ".join(p.tags),
        clean_html(p.description)[:400],
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
        if all(t in WEAK_KNIT_TERMS for t in terms) and WOVEN_GARMENT_RE.search(p.title):
            continue
        hits.append(p)
    return hits


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
    compact = _slug(store_name).replace(" ", "")
    for chain in KNOWN_CHAINS:
        chain_compact = chain.replace(" ", "")
        if compact == chain_compact:
            return True
        if len(chain_compact) >= 6 and compact.startswith(chain_compact):
            return True
    return bool(_STORE_LOCATOR_RE.search(html or "") and (html or "").lower().count("<li") > 30)

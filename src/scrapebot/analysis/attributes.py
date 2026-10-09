"""What one product is: material, gender, category, price as a number, sale, stock, launch.

Read from the product's own words (title, type, tags, the start of the description) and
from what its source declared in `raw` (Shopify variants, WooCommerce prices, JSON-LD
offers...). "" or None means the source did not say; nothing is guessed.
"""

import re
from dataclasses import dataclass, field
from typing import Any

from ..extract.prices import parse_price
from ..extract.text import clean_html

# Fibres knitwear is sold by, and the words that name them.
FIBRES: dict[str, tuple[str, ...]] = {
    "cashmere": ("cashmere",),
    "merino": ("merino",),
    "wool": ("wool", "lambswool", "lamb's wool", "shetland", "shetland wool"),
    "alpaca": ("alpaca", "baby alpaca"),
    "mohair": ("mohair",),
    "yak": ("yak",),
    "camel": ("camel hair", "camelhair"),
    "silk": ("silk",),
    "cotton": ("cotton", "pima", "supima"),
    "linen": ("linen",),
    "viscose": ("viscose", "rayon", "modal", "lyocell", "tencel"),
    "synthetic": ("acrylic", "polyester", "nylon", "polyamide", "spandex", "elastane"),
}
_FIBRE_WORD = {word: fibre for fibre, words in FIBRES.items() for word in words}
# ASCII-only case folding: a Turkish dotted or dotless i (U+0130, U+0131) in "viscose" would
# otherwise match and then miss the lookup. Seen on a real product, 2026-10-09.
_FIBRE_RE = re.compile(
    r"\b(" + "|".join(sorted(map(re.escape, _FIBRE_WORD), key=len, reverse=True)) + r")\b",
    re.I | re.A,
)
# "70% merino, 30% nylon" and "merino 70%"
_SHARE_RE = re.compile(
    r"(\d{1,3})\s?%\s*(?:of\s+)?("
    + _FIBRE_RE.pattern[3:-3]
    + r")|("
    + _FIBRE_RE.pattern[3:-3]
    + r")\s*(\d{1,3})\s?%",
    re.I | re.A,
)

_GENDER = (
    (
        "kids",
        re.compile(r"\b(kids?|child(ren)?|girls?|boys?|baby|babies|toddler|infant|youth)\b", re.I),
    ),
    ("women", re.compile(r"\b(women'?s?|womens|ladies|lady|female)\b", re.I)),
    ("men", re.compile(r"\b(men'?s?|mens|male|gentlemen)\b", re.I)),
    ("unisex", re.compile(r"\bunisex\b", re.I)),
)

# Finer kinds of knitwear, first match wins.
_CATEGORY = (
    ("cardigan", r"cardigans?|cardis?"),
    ("vest", r"(sweater|knit)\s?vests?|vests?|tanks?"),
    ("poncho_wrap", r"ponchos?|capes?|shawls?|wraps?|shrugs?|ruanas?"),
    ("dress_skirt", r"dress(es)?|skirts?"),
    ("hat", r"beanies?|toques?|tuques?|hats?|caps?|headbands?|ear\s?warmers?"),
    ("scarf", r"scar(f|ves)|snoods?|cowls?"),
    ("gloves", r"gloves?|mittens?"),
    ("socks", r"socks?"),
    (
        "sweater",
        r"sweaters?|pullovers?|jumpers?|crew(neck)?s?|turtlenecks?|mock\s?necks?|hood(ie|y)s?|tops?",
    ),
)
_CATEGORY_RE = [(name, re.compile(rf"\b({words})\b", re.I)) for name, words in _CATEGORY]


@dataclass
class Attributes:
    materials: list[str] = field(default_factory=list)  # fibres named, largest share first
    main_material: str = ""
    gender: str = ""  # women | men | kids | unisex | ""
    category: str = ""  # sweater | cardigan | vest | poncho_wrap | hat | scarf | ...
    price: float | None = None  # read from price_raw; in the product's own currency
    compare_at: float | None = None  # the "was" price, when the source gave one
    on_sale: bool | None = None
    in_stock: bool | None = None
    launched: str = ""  # ISO date the source published the product, when it said


def words_of(product: dict[str, Any]) -> str:
    tags = product.get("tags") or []
    description = clean_html(product.get("description") or "")[:1500]
    return " ".join(
        [product.get("title") or "", product.get("product_type") or "", " ".join(tags), description]
    )


def price_of(product: dict[str, Any]) -> float | None:
    """The price as a number, read the way the source wrote it. Runs made before
    `price_minor_unit` existed: WooCommerce says its minor unit in `raw`; a bare integer
    from browser-captured JSON may be cents or not, so it is left unknown, never guessed."""
    raw_price = str(product.get("price_raw") or "").strip()
    minor = product.get("price_minor_unit")
    if minor is None and product.get("source") == "woocommerce_feed":
        minor = ((product.get("raw") or {}).get("prices") or {}).get("currency_minor_unit")
    if minor:
        try:
            return int(raw_price) / 10 ** int(minor)
        except ValueError:
            return None
    if (
        minor is None
        and product.get("source") in ("render_json", "app_state")
        and raw_price.isdigit()
        and int(raw_price) >= 1000
    ):
        return None
    return parse_price(raw_price)


def materials_of(text: str) -> list[str]:
    """Fibres in the text, the largest stated share first, then in order of mention."""
    shares: dict[str, int] = {}
    for m in _SHARE_RE.finditer(text):
        pct, word = (m.group(1), m.group(2)) if m.group(1) else (m.group(4), m.group(3))
        fibre = _FIBRE_WORD[word.lower()]
        shares[fibre] = max(shares.get(fibre, 0), int(pct))
    named = list(dict.fromkeys(_FIBRE_WORD[w.lower()] for w in _FIBRE_RE.findall(text)))
    if "merino" in named and "wool" in named and "wool" not in shares:
        named.remove("wool")  # "merino wool" is one fibre
    return sorted(named, key=lambda f: (-shares.get(f, 0), named.index(f)))


def gender_of(text: str, declared: str = "") -> str:
    text = re.sub(r"baby\s+(alpaca|cashmere|camel)", r"\1", text, flags=re.I)  # a fibre, not a baby
    for gender, pattern in _GENDER:
        if pattern.search(declared):
            return gender
    found = [gender for gender, pattern in _GENDER if pattern.search(text)]
    if len(found) == 1:
        return found[0]
    return "unisex" if {"women", "men"} <= set(found) else ""


def category_of(title: str, product_type: str) -> str:
    for text in (title, product_type):
        for name, pattern in _CATEGORY_RE:
            if pattern.search(text):
                return name
    return ""


def attributes(product: dict[str, Any]) -> Attributes:
    raw = product.get("raw") or {}
    text = words_of(product)
    out = Attributes(
        materials=materials_of(text),
        gender=gender_of(text, str(raw.get("gender") or "")),
        category=category_of(product.get("title") or "", product.get("product_type") or ""),
        price=price_of(product),
    )
    out.main_material = out.materials[0] if out.materials else ""
    _from_source(product.get("source") or "", raw, out)
    if out.compare_at is not None and out.price is not None and out.on_sale is None:
        out.on_sale = out.compare_at > out.price
    return out


def flag(value: Any) -> bool | None:
    """A yes/no as sources write it: true, 1, "true", "yes", "instock"; None when absent."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return value > 0
    text = str(value).strip().lower()
    if text in ("true", "yes", "y", "1", "instock", "in_stock", "available"):
        return True
    if text in ("false", "no", "n", "0", "outofstock", "out_of_stock", "soldout", "sold_out"):
        return False
    return None


def _from_source(source: str, raw: dict[str, Any], out: Attributes) -> None:
    """Sale, stock and launch as each source declares them."""
    _declared(source, raw, out)
    out.on_sale = flag(out.on_sale)
    out.in_stock = flag(out.in_stock)


def _declared(source: str, raw: dict[str, Any], out: Attributes) -> None:
    if source == "shopify_feed":
        variants = raw.get("variants") or []
        stock = [v.get("available") for v in variants if v.get("available") is not None]
        out.in_stock = any(stock) if stock else None
        was = [parse_price(v.get("compare_at_price")) for v in variants]
        was = [w for w in was if w]
        out.compare_at = max(was) if was else None
        out.on_sale = bool(was) and out.price is not None and max(was) > out.price
        out.launched = str(raw.get("published_at") or raw.get("created_at") or "")[:10]
    elif source == "woocommerce_feed":
        out.in_stock = raw.get("is_in_stock")
        out.on_sale = raw.get("on_sale")
    elif source == "squarespace_feed":
        out.on_sale = raw.get("onSale")
        added = raw.get("addedOn")
        if isinstance(added, int | float) and added > 0:
            from datetime import UTC, datetime

            out.launched = datetime.fromtimestamp(added / 1000, UTC).date().isoformat()
    elif source in ("lightspeed_feed",):
        out.in_stock = raw.get("available")
    elif source in ("bigcartel_feed",):
        out.on_sale = raw.get("on_sale")
        out.launched = str(raw.get("created_at") or "")[:10]
    elif source in ("app_state", "render_json"):
        out.on_sale = raw.get("onSale", raw.get("on_sale"))
        stock = raw.get("onHand", raw.get("in_stock"))
        out.in_stock = bool(stock) if stock is not None else None
    elif source in ("jsonld", "microdata", "opengraph"):
        offers = raw.get("offers")
        offer = offers[0] if isinstance(offers, list) and offers else offers
        availability = str(
            (offer or {}).get("availability", "") if isinstance(offer, dict) else ""
        ) or str(raw.get("og:availability") or "")
        if availability:
            out.in_stock = "instock" in availability.lower().replace(" ", "")

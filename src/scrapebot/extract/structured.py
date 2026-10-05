"""Products declared in a page's structured data (PRD AQ-08).

Read in order of trust: JSON-LD, Microdata, RDFa (schema.org via extruct), then
OpenGraph product tags, then the JSON state a JavaScript app embeds in the page.
Values are kept as found; each product records which syntax it came from.
"""

import json
import re
from collections.abc import Iterator
from typing import Any

from ..models import Product
from .prices import parse_price
from .text import clean_html
from .values import as_text, currency_code

SCHEMA_SYNTAXES = ("json-ld", "microdata", "rdfa")
SOURCE_NAMES = {"json-ld": "jsonld", "microdata": "microdata", "rdfa": "rdfa"}

# Embedded app state: <script id="__NEXT_DATA__" type="application/json">{...}</script>
# or an assignment such as window.__INITIAL_STATE__ = {...};
_NEXT_DATA_RE = re.compile(
    r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', re.S | re.I
)
_STATE_ASSIGN_RE = re.compile(
    r"window\.(__INITIAL_STATE__|__PRELOADED_STATE__|__APOLLO_STATE__|__NUXT__)\s*=\s*", re.I
)
APP_STATE_MAX_PRODUCTS = 200
_TITLE_KEYS = ("name", "title", "productName", "product_name")
_PRICE_KEYS = ("price", "salePrice", "sale_price", "currentPrice", "priceValue", "amount")
_ID_KEYS = ("url", "href", "slug", "handle", "sku", "id", "productId", "product_id")


def _types(item: dict[str, Any]) -> list[str]:
    t = item.get("@type", [])
    types = t if isinstance(t, list) else [t]
    # RDFa and Microdata may give full IRIs: http://schema.org/Product
    return [str(x).rsplit("/", 1)[-1] for x in types]


def _offer(item: dict[str, Any]) -> dict[str, Any]:
    offers = item.get("offers") or {}
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    return offers if isinstance(offers, dict) else {}


def _offer_price(offer: dict[str, Any]) -> Any:
    for key in ("price", "lowPrice", "highPrice"):
        if offer.get(key) not in (None, ""):
            return offer[key]
    spec = offer.get("priceSpecification")
    if isinstance(spec, list):
        spec = spec[0] if spec else {}
    return spec.get("price") if isinstance(spec, dict) else None


def _walk_products(item: Any) -> Iterator[dict[str, Any]]:
    """Product nodes anywhere in a schema.org tree (inside @graph, ItemList, ...)."""
    if isinstance(item, list):
        for x in item:
            yield from _walk_products(x)
    elif isinstance(item, dict):
        if "Product" in _types(item) or "ProductGroup" in _types(item):
            yield item
            return
        for value in item.values():
            if isinstance(value, dict | list):
                yield from _walk_products(value)


def _local(name: str) -> str:
    """https://schema.org/price -> price"""
    return name.rstrip("/").rsplit("/", 1)[-1].rsplit("#", 1)[-1]


def compact_rdfa(nodes: list[Any]) -> list[dict[str, Any]]:
    """extruct gives RDFa as an expanded graph: full IRIs, values wrapped in @value,
    and nested objects as @id references. Rebuild plain schema.org-shaped objects."""
    by_id = {n["@id"]: n for n in nodes if isinstance(n, dict) and "@id" in n}

    def value(v: Any, depth: int) -> Any:
        if isinstance(v, list):
            vals = [value(x, depth) for x in v]
            return vals[0] if len(vals) == 1 else vals
        if isinstance(v, dict):
            if "@value" in v:
                return v["@value"]
            if set(v) == {"@id"} and v["@id"] in by_id and depth < 5:
                return node(by_id[v["@id"]], depth + 1)
        return v

    def node(n: dict[str, Any], depth: int = 0) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, v in n.items():
            if key == "@type":
                out["@type"] = [_local(t) for t in (v if isinstance(v, list) else [v])]
            elif key != "@id":
                out[_local(key)] = value(v, depth)
        return out

    return [node(n) for n in nodes if isinstance(n, dict) and "@type" in n]


def _schema_product(node: dict[str, Any], source: str, page_url: str) -> Product:
    offer = _offer(node)
    price_raw = _offer_price(offer)
    return Product(
        title=as_text(node.get("name")),
        price=parse_price(price_raw),
        price_raw=as_text(price_raw),
        currency=currency_code(offer.get("priceCurrency")),
        vendor=as_text(node.get("brand")),
        product_type=as_text(node.get("category")),
        description=clean_html(as_text(node.get("description"))),
        url=as_text(node.get("url") or offer.get("url")) or page_url,
        source=source,
        evidence_url=page_url,
        raw=node,
    )


def schema_products(html: str, page_url: str) -> list[Product]:
    """Products from JSON-LD, Microdata and RDFa."""
    import extruct

    try:
        data = extruct.extract(
            html or "",
            base_url=page_url,
            syntaxes=list(SCHEMA_SYNTAXES),
            uniform=True,
            errors="ignore",
        )
    except Exception:  # extruct raises on some malformed markup; a page is never fatal
        return []
    out = []
    data["rdfa"] = compact_rdfa(data.get("rdfa", []))
    for syntax in SCHEMA_SYNTAXES:
        for node in _walk_products(data.get(syntax, [])):
            product = _schema_product(node, SOURCE_NAMES[syntax], page_url)
            if product.title:
                out.append(product)
    return out


def opengraph_product(html: str, page_url: str) -> Product | None:
    """A product page's OpenGraph tags: og:type product with a price amount."""
    import extruct

    try:
        data = extruct.extract(
            html or "", base_url=page_url, syntaxes=["opengraph"], uniform=True, errors="ignore"
        )
    except Exception:
        return None
    for og in data.get("opengraph", []):
        props = {k.lower(): v for k, v in og.items() if isinstance(k, str)}
        # extruct's uniform output moves og:type to @type
        if "product" not in as_text(props.get("og:type") or props.get("@type")).lower():
            continue
        price_raw = props.get("product:price:amount") or props.get("og:price:amount")
        title = as_text(props.get("og:title"))
        if not title or price_raw in (None, ""):
            continue
        currency = props.get("product:price:currency") or props.get("og:price:currency")
        return Product(
            title=title,
            price=parse_price(price_raw),
            price_raw=as_text(price_raw),
            currency=currency_code(currency),
            vendor=as_text(props.get("product:brand")),
            description=clean_html(as_text(props.get("og:description"))),
            url=as_text(props.get("og:url")) or page_url,
            source="opengraph",
            evidence_url=page_url,
            raw=og,
        )
    return None


def _app_states(html: str) -> Iterator[Any]:
    import chompjs

    for m in _NEXT_DATA_RE.finditer(html or ""):
        try:
            yield json.loads(m.group(1))
        except ValueError:
            continue
    for m in _STATE_ASSIGN_RE.finditer(html or ""):
        try:
            # parse_js_object reads one JS object literal from where the assignment starts
            yield chompjs.parse_js_object(html[m.end() :])
        except (ValueError, TypeError, RecursionError):
            continue


def _first(obj: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if obj.get(key) not in (None, "", [], {}):
            return obj[key]
    return None


def _looks_like_product(obj: dict[str, Any]) -> bool:
    title, price = _first(obj, _TITLE_KEYS), _first(obj, _PRICE_KEYS)
    if not isinstance(title, str) or not title.strip() or _first(obj, _ID_KEYS) is None:
        return False
    if isinstance(price, dict):  # {"amount": "98.00", "currencyCode": "USD"}
        price = _first(price, ("amount", "value", "price"))
    return parse_price(price) is not None


def _state_products(node: Any, found: list[dict[str, Any]], depth: int = 0) -> None:
    if len(found) >= APP_STATE_MAX_PRODUCTS or depth > 40:
        return
    if isinstance(node, dict):
        if _looks_like_product(node):
            found.append(node)
            return
        for value in node.values():
            _state_products(value, found, depth + 1)
    elif isinstance(node, list):
        for value in node:
            _state_products(value, found, depth + 1)


def app_state_products(html: str, page_url: str) -> list[Product]:
    """Product-shaped objects in embedded app state. Heuristic, so flagged for review."""
    found: list[dict[str, Any]] = []
    for state in _app_states(html):
        _state_products(state, found)
    out = []
    for obj in found[:APP_STATE_MAX_PRODUCTS]:
        price = _first(obj, _PRICE_KEYS)
        currency = obj.get("currency") or obj.get("currencyCode")
        if isinstance(price, dict):
            currency = currency or price.get("currencyCode") or price.get("currency")
            price = _first(price, ("amount", "value", "price"))
        url = _first(obj, ("url", "href"))
        out.append(
            Product(
                title=as_text(_first(obj, _TITLE_KEYS)),
                price=parse_price(price),
                price_raw=as_text(price),
                currency=currency_code(currency),
                vendor=as_text(obj.get("brand") or obj.get("vendor")),
                url=as_text(url) if isinstance(url, str) and url.startswith("http") else page_url,
                source="app_state",
                evidence_url=page_url,
                needs_review=True,
                raw=obj,
            )
        )
    return out


def page_products(html: str, page_url: str) -> list[Product]:
    """Every product a page declares, from the most trusted syntax that has any.

    Within a page the syntaxes usually repeat each other, so the first that yields
    products wins; OpenGraph and app state are only consulted when schema.org
    data has nothing.
    """
    products = schema_products(html, page_url)
    if products:
        return products
    og = opengraph_product(html, page_url)
    if og:
        return [og]
    return app_state_products(html, page_url)

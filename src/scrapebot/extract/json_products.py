"""Products in the JSON a rendered page loaded (its XHR and fetch responses). Pure functions.

A known feed shape (Shopify, Magento GraphQL) is read with its own parser. Anything
else is searched for a list of objects that each carry a name and a price; such
products are a heuristic reading, so they are marked `needs_review`.
"""

from typing import Any
from urllib.parse import urljoin, urlparse

from ..models import Product
from .feeds import magento_products, shopify_products
from .prices import parse_price
from .values import as_text, currency_code

TITLE_KEYS = ("name", "title", "productName", "product_name", "displayName", "display_name")
PRICE_KEYS = (
    "price", "salePrice", "sale_price", "finalPrice", "final_price", "currentPrice",
    "current_price", "minPrice", "min_price", "price_range", "priceRange", "prices",
    "regularPrice", "regular_price", "amount",
)  # fmt: skip
# Prices some APIs give in minor units: 4600 means 46.00. `price_raw` keeps "4600".
CENTS_KEYS = (
    "priceCents", "price_cents", "priceInCents", "price_in_cents", "amountCents",
    "amount_cents", "salePriceCents", "sale_price_cents",
)  # fmt: skip
URL_KEYS = ("url", "href", "link", "permalink", "productUrl", "product_url", "canonical_url")
CURRENCY_KEYS = ("currency", "currencyCode", "currency_code", "priceCurrency")
NESTED_PRICE_KEYS = ("value", "amount", "price", "final_price", "minimum_price", "min", "raw")
MAX_DEPTH = 8
MIN_ITEMS = 2  # one priced object is as likely a cart line or a banner as a catalogue
MIN_SHARE = 0.6  # of a list's objects that must look like products


def captured_products(data: Any, evidence_url: str, page_url: str) -> list[Product]:
    """Products in one captured JSON response."""
    parts = urlparse(page_url)
    origin = f"{parts.scheme}://{parts.netloc}"
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        found = magento_products(data, origin, evidence_url=evidence_url)
        if found:
            return found
    if isinstance(data, dict) and isinstance(data.get("products"), list):
        found = [p for p in shopify_products(data, origin, evidence_url) if p.price is not None]
        if found:
            return found
    out: list[Product] = []
    _walk(data, evidence_url, page_url, out, 0)
    return out


def _walk(node: Any, evidence_url: str, page_url: str, out: list[Product], depth: int) -> None:
    if depth > MAX_DEPTH:
        return
    if isinstance(node, list):
        items = [n for n in node if isinstance(n, dict)]
        products = [p for p in (_product(i, evidence_url, page_url) for i in items) if p]
        if len(products) >= MIN_ITEMS and len(products) >= MIN_SHARE * len(items):
            out.extend(products)
            return
        for child in node:
            _walk(child, evidence_url, page_url, out, depth + 1)
    elif isinstance(node, dict):
        for child in node.values():
            if isinstance(child, dict | list):
                _walk(child, evidence_url, page_url, out, depth + 1)


def _product(item: dict[str, Any], evidence_url: str, page_url: str) -> Product | None:
    title = next((item[k] for k in TITLE_KEYS if isinstance(item.get(k), str)), "")
    title = title.strip()
    if not 2 <= len(title) <= 300:
        return None
    money = _money(item)
    if money is None:  # a product priced per variant
        variants = [v for v in item.get("variants") or [] if isinstance(v, dict)]
        priced = [m for m in (_money(v) for v in variants) if m is not None]
        money = min(priced, key=lambda m: m[0]) if priced else None
    if money is None:
        return None
    price, price_raw, currency = money
    currency = currency or next(
        (currency_code(item[k]) for k in CURRENCY_KEYS if currency_code(item.get(k))), ""
    )
    link = next((item[k] for k in URL_KEYS if isinstance(item.get(k), str) and item[k]), "")
    return Product(
        title=title,
        price=price,
        price_raw=price_raw,
        currency=currency,
        url=urljoin(page_url, link) if link else "",
        source="render_json",
        evidence_url=evidence_url,
        needs_review=True,
        raw=item,
    )


def _money(obj: dict[str, Any]) -> tuple[float, str, str] | None:
    """(price, price as written, currency) of an object, or None when it has no price."""
    raw, currency = _price(next((obj[k] for k in PRICE_KEYS if k in obj), None), 0)
    price = parse_price(raw) if raw else None
    if price:
        return price, raw, currency
    cents = next((obj[k] for k in CENTS_KEYS if isinstance(obj.get(k), int | float)), None)
    if cents and not isinstance(cents, bool) and cents > 0:
        return cents / 100, as_text(cents), ""
    return None


def _price(value: Any, depth: int) -> tuple[str, str]:
    """(price as the source wrote it, currency stated next to it)."""
    if depth > 3 or value is None or isinstance(value, bool):
        return "", ""
    if isinstance(value, int | float | str):
        return as_text(value), ""
    if isinstance(value, list):
        return _price(value[0], depth + 1) if value else ("", "")
    if isinstance(value, dict):
        currency = next(
            (currency_code(value[k]) for k in CURRENCY_KEYS if currency_code(value.get(k))), ""
        )
        for key in NESTED_PRICE_KEYS:
            if key in value:
                raw, inner = _price(value[key], depth + 1)
                if raw:
                    return raw, inner or currency
    return "", ""

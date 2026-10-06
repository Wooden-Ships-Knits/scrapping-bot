"""Parsers for the product feeds platforms publish (PRD AQ-05, AQ-06). Pure functions.

Each returns products exactly as the feed states them; `raw` keeps the feed object.
"""

import html as html_lib
from typing import Any

from ..models import Product
from .prices import parse_price
from .text import clean_html
from .values import as_text, currency_code


def shopify_products(data: Any, base_url: str = "", evidence_url: str = "") -> list[Product]:
    """Parse a Shopify /products.json payload. Tolerates null fields throughout.

    The price is the lowest variant price. The feed carries no currency: the caller
    stamps the store currency on the products. Anything that is not a Shopify payload
    (Big Cartel answers the same path with a list) yields no products.
    """
    out = []
    for raw in (data.get("products") if isinstance(data, dict) else None) or []:
        if not isinstance(raw, dict):
            continue
        variants = [v for v in raw.get("variants") or [] if isinstance(v, dict)]
        priced = [(parse_price(v.get("price")), v.get("price")) for v in variants]
        priced = [(value, text) for value, text in priced if value]
        price, price_raw = min(priced, key=lambda pair: pair[0]) if priced else (None, "")
        tags = raw.get("tags")
        handle = as_text(raw.get("handle"))
        out.append(
            Product(
                title=as_text(raw.get("title")),
                price=price,
                price_raw=as_text(price_raw),
                vendor=as_text(raw.get("vendor")),
                product_type=as_text(raw.get("product_type")),
                tags=[as_text(t) for t in tags] if isinstance(tags, list) else [],
                description=clean_html(raw.get("body_html") or ""),
                url=f"{base_url}/products/{handle}" if base_url and handle else "",
                source="shopify_feed",
                evidence_url=evidence_url,
                raw=raw,
            )
        )
    return out


def bigcartel_products(data: Any, origin: str, evidence_url: str = "") -> list[Product]:
    """Big Cartel storefront feed (`/products.json`): a list of every product, unpaged.

    `price` is the lowest option price. The feed carries no currency: the caller stamps
    the store currency on the products.
    """
    out = []
    for raw in data if isinstance(data, list) else []:
        if not isinstance(raw, dict) or not raw.get("name"):
            continue
        price = parse_price(raw.get("price"))
        categories = [
            as_text(c.get("name")) for c in raw.get("categories") or [] if isinstance(c, dict)
        ]
        artists = [as_text(a.get("name")) for a in raw.get("artists") or [] if isinstance(a, dict)]
        path = as_text(raw.get("url"))
        out.append(
            Product(
                title=as_text(raw.get("name")),
                price=price or None,
                price_raw=as_text(raw.get("price")),
                vendor=", ".join(artists),
                product_type=categories[0] if categories else "",
                tags=categories,
                description=clean_html(as_text(raw.get("description"))),
                url=origin + path if path.startswith("/") else path,
                source="bigcartel_feed",
                evidence_url=evidence_url,
                raw=raw,
            )
        )
    return out


def woocommerce_products(data: Any, evidence_url: str = "") -> list[Product]:
    """WooCommerce Store API (/wp-json/wc/store/v1/products).

    Prices come in minor units ("22900" with currency_minor_unit 2). `price_raw`
    keeps that string; `price` is the amount in major units.
    """
    out = []
    for raw in data if isinstance(data, list) else []:
        if not isinstance(raw, dict):
            continue
        prices = raw.get("prices") or {}
        minor = prices.get("price")
        try:
            price = int(str(minor)) / 10 ** int(prices.get("currency_minor_unit") or 0)
        except (TypeError, ValueError):
            price = None
        categories = [
            as_text(c.get("name")) for c in raw.get("categories") or [] if isinstance(c, dict)
        ]
        out.append(
            Product(
                title=html_lib.unescape(as_text(raw.get("name"))),
                price=price or None,
                price_raw=as_text(minor),
                currency=currency_code(prices.get("currency_code")),
                vendor=", ".join(
                    as_text(b.get("name")) for b in raw.get("brands") or [] if isinstance(b, dict)
                ),
                product_type=html_lib.unescape(categories[0]) if categories else "",
                tags=[
                    html_lib.unescape(as_text(t.get("name")))
                    for t in raw.get("tags") or []
                    if isinstance(t, dict)
                ],
                description=clean_html(
                    as_text(raw.get("short_description") or raw.get("description"))
                ),
                url=as_text(raw.get("permalink")),
                source="woocommerce_feed",
                evidence_url=evidence_url,
                raw=raw,
            )
        )
    return out


def _variant_money(item: dict[str, Any]) -> tuple[float | None, str, str]:
    """(price, price_raw, currency) from the cheapest priced variant."""
    content = (
        item.get("structuredContent") if isinstance(item.get("structuredContent"), dict) else item
    )
    best: tuple[float | None, str, str] = (None, "", "")
    for variant in (content or {}).get("variants") or []:
        money = variant.get("priceMoney") if isinstance(variant, dict) else None
        if not isinstance(money, dict):
            continue
        value = parse_price(money.get("value"))
        if value and (best[0] is None or value < best[0]):
            best = (value, as_text(money.get("value")), currency_code(money.get("currency")))
    if best[0] is None:
        money = (content or {}).get("priceMoney") or {}
        value = parse_price(money.get("value")) if isinstance(money, dict) else None
        if value:
            best = (value, as_text(money.get("value")), currency_code(money.get("currency")))
    return best


def is_squarespace_store(data: Any) -> bool:
    collection = data.get("collection") if isinstance(data, dict) else None
    return isinstance(collection, dict) and (
        collection.get("typeName") == "products" or collection.get("type") == 13
    )


def squarespace_products(data: Any, origin: str, evidence_url: str = "") -> list[Product]:
    """A Squarespace products collection (`<collection>?format=json`)."""
    if not is_squarespace_store(data):
        return []
    out = []
    for item in data.get("items") or []:
        if not isinstance(item, dict) or not item.get("title"):
            continue
        price, price_raw, currency = _variant_money(item)
        out.append(
            Product(
                title=as_text(item.get("title")),
                price=price,
                price_raw=price_raw,
                currency=currency,
                product_type=as_text((item.get("categories") or [""])[0]),
                tags=[as_text(t) for t in item.get("tags") or []],
                description=clean_html(as_text(item.get("excerpt"))),
                url=origin + as_text(item.get("fullUrl")) if item.get("fullUrl") else "",
                source="squarespace_feed",
                evidence_url=evidence_url,
                raw=item,
            )
        )
    return out


def squarespace_next_offset(data: Any) -> int | None:
    pagination = data.get("pagination") if isinstance(data, dict) else None
    if isinstance(pagination, dict) and pagination.get("nextPage"):
        offset = pagination.get("nextPageOffset")
        return (
            int(offset) if isinstance(offset, int | float | str) and str(offset).isdigit() else None
        )
    return None


def lightspeed_currency(data: Any) -> str:
    shop = data.get("shop") if isinstance(data, dict) else None
    if not isinstance(shop, dict):
        return ""
    current = shop.get("currency2")
    if isinstance(current, dict):
        return currency_code(current.get("code"))
    return currency_code(shop.get("currency"))


def lightspeed_products(data: Any, origin: str, evidence_url: str = "") -> list[Product]:
    """A Lightspeed eCom collection (`/collection/?format=json`)."""
    collection = data.get("collection") if isinstance(data, dict) else None
    products = collection.get("products") if isinstance(collection, dict) else None
    if isinstance(products, dict):
        products = list(products.values())
    if not isinstance(products, list):
        return []
    currency = lightspeed_currency(data)
    out = []
    for raw in products:
        if not isinstance(raw, dict):
            continue
        money = raw.get("price")
        money = money if isinstance(money, dict) else {}
        amount = money.get("price_incl", money.get("price"))
        brand = raw.get("brand")
        path = as_text(raw.get("url"))
        out.append(
            Product(
                title=as_text(raw.get("fulltitle") or raw.get("title")),
                price=parse_price(amount),
                price_raw=as_text(amount),
                currency=currency,
                vendor=as_text(brand.get("title")) if isinstance(brand, dict) else "",
                description=clean_html(as_text(raw.get("description"))),
                url=f"{origin}/{path.lstrip('/')}" if path else "",
                source="lightspeed_feed",
                evidence_url=evidence_url,
                raw=raw,
            )
        )
    return out


def lightspeed_next_page(data: Any) -> int | None:
    collection = data.get("collection") if isinstance(data, dict) else None
    nxt = collection.get("page_next") if isinstance(collection, dict) else None
    return int(nxt) if isinstance(nxt, int) and nxt > 0 else None

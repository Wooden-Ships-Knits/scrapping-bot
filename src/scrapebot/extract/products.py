"""Products from platform feeds and embedded structured data."""

import json
import re
from typing import Any

from ..models import Product
from .prices import parse_price
from .text import clean_html

_JSONLD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.S | re.I
)
_CURRENCY_CODE_RE = re.compile(r"^[A-Za-z]{3}$")


def as_text(value: Any) -> str:
    """A source value as text. Structured data puts lists and objects where text is expected."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return as_text(value[0]) if value else ""
    if isinstance(value, dict):
        return as_text(value.get("name") or value.get("@value") or "")
    return str(value)


def currency_code(value: Any) -> str:
    """An ISO 4217-shaped code, uppercased, or "" for anything else."""
    text = as_text(value)
    return text.upper() if _CURRENCY_CODE_RE.match(text) else ""


def products_from_shopify_feed(
    data: dict[str, Any] | None, base_url: str = "", evidence_url: str = ""
) -> list[Product]:
    """Parse a Shopify /products.json payload. Tolerates null fields throughout.

    The price is the lowest variant price. The feed carries no currency: the caller
    stamps the store currency on the products.
    """
    out = []
    for raw in (data or {}).get("products") or []:
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


def jsonld_blocks(html: str) -> list[dict[str, Any]]:
    """Every parseable JSON-LD object in the page, flattened out of @graph wrappers."""
    blocks: list[Any] = []
    for raw in _JSONLD_RE.findall(html or ""):
        try:
            parsed = json.loads(raw.strip())
        except (ValueError, TypeError):
            continue
        items = parsed if isinstance(parsed, list) else [parsed]
        for item in items:
            if isinstance(item, dict):
                blocks.extend(item.get("@graph", [item]))
    return [b for b in blocks if isinstance(b, dict)]


def first_offer(block: dict[str, Any]) -> dict[str, Any]:
    offers = block.get("offers") or {}
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    return offers if isinstance(offers, dict) else {}


def _offer_price(offer: dict[str, Any]) -> Any:
    # AggregateOffer carries lowPrice instead of price.
    return offer.get("price") if offer.get("price") is not None else offer.get("lowPrice")


def products_from_jsonld(html: str, evidence_url: str = "") -> list[Product]:
    """Products declared via schema.org JSON-LD, each with its own currency."""
    out = []
    for block in jsonld_blocks(html):
        types = block.get("@type", "")
        types = types if isinstance(types, list) else [types]
        if "Product" not in types:
            continue
        offer = first_offer(block)
        price_raw = _offer_price(offer)
        brand = block.get("brand")
        out.append(
            Product(
                title=as_text(block.get("name")),
                price=parse_price(price_raw),
                price_raw=as_text(price_raw),
                currency=currency_code(offer.get("priceCurrency")),
                vendor=as_text(brand),
                product_type=as_text(block.get("category")),
                description=clean_html(as_text(block.get("description"))),
                url=as_text(block.get("url") or offer.get("url")) or evidence_url,
                source="jsonld",
                evidence_url=evidence_url,
                raw=block,
            )
        )
    return out

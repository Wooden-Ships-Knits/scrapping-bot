"""What a store runs on and which currency it declares."""

import re

from .products import currency_code, first_offer, jsonld_blocks

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

_SHOPIFY_CURRENCY_RE = re.compile(r'Shopify\.currency\s*=\s*\{[^}]*"active"\s*:\s*"([A-Za-z]{3})"')
_META_CURRENCY_RES = (
    re.compile(
        r'<meta[^>]+property=["\'](?:og|product):price:currency["\'][^>]+content=["\']([^"\']+)',
        re.I,
    ),
    re.compile(
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\'](?:og|product):price:currency',
        re.I,
    ),
)


def detect_platform(html: str) -> str:
    """Best-guess e-commerce platform from HTML markers."""
    h = (html or "").lower()
    for name, markers in PLATFORM_MARKERS:
        if any(m in h for m in markers):
            return name
    return "custom/unknown"


def detect_currency(html: str) -> tuple[str, str]:
    """(currency, source) declared by a page, or ("", "") when it declares none.

    Sources, most reliable first: Shopify's theme script (the currency prices are
    shown in), OpenGraph price meta tags, then JSON-LD offers. A currency symbol
    in text is never used: "$" alone does not say which dollar.
    """
    html = html or ""
    m = _SHOPIFY_CURRENCY_RE.search(html)
    if m:
        return m.group(1).upper(), "shopify_js"
    for rx in _META_CURRENCY_RES:
        m = rx.search(html)
        if m and currency_code(m.group(1)):
            return currency_code(m.group(1)), "meta"
    for block in jsonld_blocks(html):
        code = currency_code(first_offer(block).get("priceCurrency"))
        if code:
            return code, "jsonld"
    return "", ""

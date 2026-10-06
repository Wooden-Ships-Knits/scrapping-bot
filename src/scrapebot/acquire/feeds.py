"""Platform feeds: product lists a store publishes as JSON (PRD AQ-05, AQ-06).

Each feed is tried only where the platform makes it plausible, and stops at the
first page that is not a feed, so a store without one costs a single request.
"""

import json
from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode, urlparse

from ..extract import feeds as parse
from ..extract.pages import internal_links
from ..fetch import Fetcher
from ..models import Product

MAX_FEED_PRODUCTS = 2000
SHOPIFY_PAGE_SIZE = 250
WOO_PAGE_SIZE = 100
LIGHTSPEED_PAGE_SIZE = 100
MAGENTO_PAGE_SIZE = 100
# Fields every Magento 2.3+ GraphQL schema has. One unknown field fails the whole query,
# so nothing newer (url_suffix, brand attributes) is asked for; `raw` keeps the answer.
MAGENTO_QUERY = (
    '{products(search:"",pageSize:%d,currentPage:%d){total_count '
    "page_info{current_page total_pages} items{__typename name sku url_key canonical_url "
    "categories{name} description{html} "
    "price_range{minimum_price{final_price{value currency}}}}}}"
)
MAX_FEED_PAGES = 20
SQUARESPACE_COLLECTIONS = ("/shop", "/store", "/shop-all")
MAX_SQUARESPACE_COLLECTIONS = 4


def _json(fetcher: Fetcher, url: str) -> Any:
    res = fetcher.get(url)
    if not res.ok or not res.body.lstrip().startswith(("{", "[")):
        return None
    try:
        return json.loads(res.body)
    except ValueError:
        return None


def shopify_feed(origin: str, fetcher: Fetcher, home_html: str = "") -> list[Product]:
    out: list[Product] = []
    for page in range(1, MAX_FEED_PAGES + 1):
        url = f"{origin}/products.json?limit={SHOPIFY_PAGE_SIZE}&page={page}"
        batch = parse.shopify_products(_json(fetcher, url), base_url=origin, evidence_url=url)
        if not batch:
            break
        out.extend(batch)
        if len(out) >= MAX_FEED_PRODUCTS or len(batch) < SHOPIFY_PAGE_SIZE:
            break
    return out[:MAX_FEED_PRODUCTS]


def bigcartel_feed(origin: str, fetcher: Fetcher, home_html: str = "") -> list[Product]:
    url = f"{origin}/products.json"  # every product in one response; no paging
    return parse.bigcartel_products(_json(fetcher, url), origin, evidence_url=url)[
        :MAX_FEED_PRODUCTS
    ]


def woocommerce_feed(origin: str, fetcher: Fetcher, home_html: str = "") -> list[Product]:
    out: list[Product] = []
    for page in range(1, MAX_FEED_PAGES + 1):
        url = f"{origin}/wp-json/wc/store/v1/products?per_page={WOO_PAGE_SIZE}&page={page}"
        batch = parse.woocommerce_products(_json(fetcher, url), evidence_url=url)
        if not batch:
            break
        out.extend(batch)
        if len(out) >= MAX_FEED_PRODUCTS or len(batch) < WOO_PAGE_SIZE:
            break
    return out[:MAX_FEED_PRODUCTS]


def _squarespace_collections(origin: str, home_html: str) -> list[str]:
    """Likely product collections: `/x` for any `/x/p/<item>` link, then the usual paths."""
    host = (urlparse(origin).hostname or "").removeprefix("www.")
    found = []
    for link in internal_links(home_html, origin, host):
        parts = [p for p in urlparse(link).path.split("/") if p]
        if len(parts) >= 3 and parts[1] == "p":
            found.append(f"/{parts[0]}")
    paths = found + list(SQUARESPACE_COLLECTIONS)
    return list(dict.fromkeys(paths))[:MAX_SQUARESPACE_COLLECTIONS]


def squarespace_feed(origin: str, fetcher: Fetcher, home_html: str = "") -> list[Product]:
    out: list[Product] = []
    for path in _squarespace_collections(origin, home_html):
        url, pages = f"{origin}{path}?format=json", 0
        while url and pages < MAX_FEED_PAGES and len(out) < MAX_FEED_PRODUCTS:
            data = _json(fetcher, url)
            if not parse.is_squarespace_store(data):
                break
            out.extend(parse.squarespace_products(data, origin, evidence_url=url))
            offset = parse.squarespace_next_offset(data)
            url = f"{origin}{path}?format=json&offset={offset}" if offset is not None else ""
            pages += 1
    seen: set[str] = set()
    unique = [p for p in out if not (p.url in seen or seen.add(p.url))]  # collections overlap
    return unique[:MAX_FEED_PRODUCTS]


def magento_feed(origin: str, fetcher: Fetcher, home_html: str = "") -> list[Product]:
    """The storefront's own GraphQL API, the one a Magento PWA reads its catalogue from."""
    out: list[Product] = []
    for page in range(1, MAX_FEED_PAGES + 1):
        query = MAGENTO_QUERY % (MAGENTO_PAGE_SIZE, page)
        url = f"{origin}/graphql?{urlencode({'query': query})}"
        data = _json(fetcher, url)
        batch = parse.magento_products(data, origin, evidence_url=url)
        out.extend(batch)
        if not batch or len(out) >= MAX_FEED_PRODUCTS or page >= parse.magento_total_pages(data):
            break
    return out[:MAX_FEED_PRODUCTS]


def lightspeed_feed(origin: str, fetcher: Fetcher, home_html: str = "") -> list[Product]:
    out: list[Product] = []
    url = f"{origin}/collection/?format=json&limit={LIGHTSPEED_PAGE_SIZE}"
    for _ in range(MAX_FEED_PAGES):
        data = _json(fetcher, url)
        batch = parse.lightspeed_products(data, origin, evidence_url=url)
        if not batch:
            break
        out.extend(batch)
        nxt = parse.lightspeed_next_page(data)
        if nxt is None or len(out) >= MAX_FEED_PRODUCTS:
            break
        url = f"{origin}/collection/page{nxt}.html?format=json&limit={LIGHTSPEED_PAGE_SIZE}"
    return out[:MAX_FEED_PRODUCTS]


Feed = Callable[[str, Fetcher, str], list[Product]]

FEEDS: dict[str, Feed] = {
    "shopify_feed": shopify_feed,
    "bigcartel_feed": bigcartel_feed,
    "woocommerce_feed": woocommerce_feed,
    "squarespace_feed": squarespace_feed,
    "lightspeed_feed": lightspeed_feed,
    "magento_feed": magento_feed,
}

# Which feeds a detected platform makes worth a request, in order.
FEEDS_FOR_PLATFORM: dict[str, tuple[str, ...]] = {
    "shopify": ("shopify_feed",),
    "bigcartel": ("bigcartel_feed",),
    "woocommerce": ("woocommerce_feed",),
    "wordpress": ("woocommerce_feed",),
    "squarespace": ("squarespace_feed",),
    "lightspeed": ("lightspeed_feed",),
    "magento": ("magento_feed",),
    "custom/unknown": ("shopify_feed",),  # headless or rebranded Shopify still answers
}


def feeds_for(platform: str) -> tuple[str, ...]:
    return FEEDS_FOR_PLATFORM.get(platform, ())

"""Platform feeds: product lists a store publishes as JSON."""

import json

from ..extract.products import products_from_shopify_feed
from ..fetch import Fetcher
from ..models import Product

FEED_PAGE_CAP = 8
FEED_PAGE_SIZE = 250


def shopify_products(origin: str, fetcher: Fetcher) -> list[Product]:
    """Paginate a Shopify /products.json feed. Empty list if the site isn't Shopify."""
    out: list[Product] = []
    for page in range(1, FEED_PAGE_CAP + 1):
        url = f"{origin}/products.json?limit={FEED_PAGE_SIZE}&page={page}"
        res = fetcher.get(url)
        if not res.ok or not res.body.strip().startswith("{"):
            break
        try:
            data = json.loads(res.body)
        except ValueError:
            break
        batch = products_from_shopify_feed(data, base_url=origin, evidence_url=url)
        if not batch:
            break
        out.extend(batch)
    return out

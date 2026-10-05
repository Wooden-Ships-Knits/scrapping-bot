"""Acquisition: gather everything a store publishes, cheapest exact source first.

Stage order for one store (ADR 0001):

1. Homepage. A failure here ends the visit as `blocked` or `error`.
2. Deep links from the input, fetched as priority pages.
3. Platform feed (Shopify). When it yields products, discovery is skipped.
4. Discovery: sitemap, else the homepage's links. Then JSON-LD on every page.

Every stage tried is recorded in `layers_tried`.
"""

from ..extract.contacts import find_contacts
from ..extract.products import products_from_jsonld
from ..extract.profile import detect_currency, detect_platform
from ..fetch import Fetcher
from ..models import Acquired, Target
from .discovery import MAX_PAGES, crawl_urls, dedupe, fetch_pages, sitemap_urls, to_page, url_key
from .feeds import shopify_products

# A homepage with less visible text than this is a JavaScript shell: the content
# arrives only after scripts run, so an empty result says nothing about the catalogue.
SHELL_TEXT_CHARS = 200

BLOCKED_STATUSES = (401, 403, 429)

__all__ = ["MAX_PAGES", "acquire"]


def acquire(target: Target, fetcher: Fetcher) -> Acquired:
    """Gather everything available for one store. Never raises for network conditions."""
    got = Acquired(domain=target.domain, url=target.url, layers_tried=["homepage"])

    home = fetcher.get(target.url)
    got.ssl_bypassed = home.ssl_bypassed
    if not home.ok:
        if home.status_code in BLOCKED_STATUSES:
            got.status = "blocked"
            got.error = f"HTTP {home.status_code}"
        else:
            got.status = "error"
            got.error = home.error or f"HTTP {home.status_code}"
        return got

    got.pages = [to_page(target.url, home.body, home.status_code, target.url)]
    got.platform = detect_platform(home.body)
    got.currency, got.currency_source = detect_currency(home.body)

    deep = dedupe(target.deep_links, seen={url_key(target.url)})
    if deep:
        got.layers_tried.append("deep_links")
        got.pages += fetch_pages(deep, fetcher, MAX_PAGES - len(got.pages), target.url)

    got.layers_tried.append("shopify_feed")
    feed = shopify_products(target.url, fetcher)
    if feed:
        # The feed carries no currency; its prices are in the currency the
        # storefront declares, which is the store's base currency because no
        # Accept-Language header is sent (see fetch.py).
        for product in feed:
            product.currency = got.currency
        got.source_used = "shopify_feed"
        got.products = feed
    else:
        _discover(target, home.body, fetcher, got)

    got.contacts = find_contacts(got.pages)
    got.status = _read_status(got)
    return got


def _discover(target: Target, home_html: str, fetcher: Fetcher, got: Acquired) -> None:
    """Find pages through the sitemap or the homepage's links, then read their JSON-LD."""
    seen = {url_key(p.url) for p in got.pages}
    budget = MAX_PAGES - len(got.pages)

    got.layers_tried.append("sitemap")
    urls = sitemap_urls(target.url, fetcher, limit=budget)
    if urls:
        got.source_used = "sitemap"
    else:
        got.layers_tried.append("crawl")
        got.source_used = "crawl"
        urls = crawl_urls(home_html, target.url, target.domain)
    urls = dedupe(urls, seen)
    got.pages += fetch_pages(urls, fetcher, budget, target.url)

    got.layers_tried.append("jsonld")
    for page in got.pages:
        got.products.extend(products_from_jsonld(page.html, evidence_url=page.url))

    if not got.currency:
        for page in got.pages[1:]:
            got.currency, got.currency_source = detect_currency(page.html)
            if got.currency:
                break


def _read_status(got: Acquired) -> str:
    """`ok` only with products; otherwise say why there are none."""
    if got.products:
        return "ok"
    home_text = got.pages[0].text if got.pages else ""
    return "js_required" if len(home_text) < SHELL_TEXT_CHARS else "no_products"

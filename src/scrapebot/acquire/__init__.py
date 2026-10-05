"""Acquisition: gather everything a store publishes, cheapest exact source first.

Stage order for one store (ADR 0001):

1. Homepage. A failure or a challenge page ends the visit as `error` or `blocked`.
2. Platform feed for the detected platform (Shopify, WooCommerce, Squarespace,
   Lightspeed). Exact and cheap; when it yields products, discovery is skipped.
3. Priority pages (contact, about, wholesale, stockist) and deep links from the
   input. Always fetched, feed or not, so contacts are never missed.
4. Discovery: product sitemaps, else the homepage's links two levels deep.
5. Structured data on every page: JSON-LD, Microdata, RDFa, OpenGraph, app state.

Every stage tried is recorded in `layers_tried`. Later milestones add a browser
render and an LLM after stage 5, for stores that still have no products.
"""

from collections import Counter

from ..extract.contacts import find_contacts
from ..extract.profile import detect_currency, detect_platform
from ..extract.structured import page_products
from ..fetch import Fetcher
from ..models import Acquired, Product, Target
from .discovery import (
    MAX_PAGES,
    PRIORITY_CAP,
    RankedLinks,
    dedupe,
    fetch_pages,
    rank_links,
    sitemap_urls,
    to_page,
    url_key,
)
from .feeds import FEEDS, feeds_for

# A homepage with less visible text than this is a JavaScript shell: the content
# arrives only after scripts run, so an empty result says nothing about the catalogue.
SHELL_TEXT_CHARS = 200

BLOCKED_STATUSES = (401, 403, 429)

__all__ = ["MAX_PAGES", "acquire"]


def acquire(target: Target, fetcher: Fetcher, max_pages: int = MAX_PAGES) -> Acquired:
    """Gather everything available for one store. Never raises for network conditions."""
    got = Acquired(domain=target.domain, url=target.url, layers_tried=["homepage"])

    home = fetcher.get(target.url)
    got.ssl_bypassed = home.ssl_bypassed
    if home.challenge:
        got.status, got.error = "blocked", f"challenge page ({home.challenge})"
        return got
    if not home.ok:
        if home.status_code in BLOCKED_STATUSES:
            got.status, got.error = "blocked", f"HTTP {home.status_code}"
        else:
            got.status, got.error = "error", home.error or f"HTTP {home.status_code}"
        return got

    got.pages = [to_page(target.url, home, target.url)]
    got.platform = detect_platform(home.body)
    got.currency, got.currency_source = detect_currency(home.body)
    links = rank_links(home.body, target.url, target.domain)
    seen = {url_key(target.url)}

    for name in feeds_for(got.platform):
        got.layers_tried.append(name)
        products = FEEDS[name](target.url, fetcher, home.body)
        if products:
            got.source_used, got.products = name, products
            break

    first = dedupe(links.priority[:PRIORITY_CAP] + target.deep_links, seen)
    if first:
        got.layers_tried.append("priority_pages")
        got.pages += fetch_pages(first, fetcher, max_pages - len(got.pages), target.url)
        seen |= {url_key(u) for u in first}

    if got.products:
        if not got.currency:  # Shopify's feed carries no currency; the storefront does
            got.currency, got.currency_source = _currency_from_pages(got)
        if not got.currency:
            got.currency, got.currency_source = _currency_from_products(got.products)
        for product in got.products:
            product.currency = product.currency or got.currency
    else:
        _discover(target, links, fetcher, got, seen, max_pages)
        if not got.currency:
            got.currency, got.currency_source = _currency_from_pages(got)
        if not got.currency:
            got.currency, got.currency_source = _currency_from_products(got.products)

    got.contacts = find_contacts(got.read_pages)
    got.status = _read_status(got)
    return got


def _discover(
    target: Target,
    links: RankedLinks,
    fetcher: Fetcher,
    got: Acquired,
    seen: set[str],
    max_pages: int,
) -> None:
    """Product and collection pages from the sitemap, else from links two levels deep,
    then the structured data on every page read."""
    got.layers_tried.append("sitemap")
    sitemap = sitemap_urls(target.url, fetcher, fetcher.sitemaps(target.url))
    if sitemap.found and (sitemap.products or sitemap.pages.product or sitemap.pages.collection):
        got.source_used = "sitemap"
        candidates = (
            sitemap.products
            + sitemap.pages.product
            + links.product
            + sitemap.pages.collection
            + links.collection
        )
    else:
        got.layers_tried.append("crawl")
        got.source_used = "crawl"
        candidates = links.product + links.collection + links.other

    budget = max_pages - len(got.pages)
    batch = dedupe(candidates, seen)[:budget]
    got.pages += fetch_pages(batch, fetcher, budget, target.url)
    seen |= {url_key(u) for u in batch}

    # Level two: product links found on the collection pages just read.
    budget = max_pages - len(got.pages)
    if budget > 0:
        deeper = RankedLinks()
        for page in got.read_pages[1:]:
            for url in rank_links(page.html, page.url, target.domain).product:
                deeper.add(url)
        level_two = dedupe(deeper.product, seen)[:budget]
        if level_two:
            got.layers_tried.append("crawl_depth_2")
            got.pages += fetch_pages(level_two, fetcher, budget, target.url)

    got.layers_tried.append("structured")
    products: list[Product] = []
    for page in got.read_pages:
        products += page_products(page.html, page.url)
    got.products = dedupe_products(products)


def dedupe_products(products: list[Product]) -> list[Product]:
    """Drop exact repeats (same source, title, price and URL), as when a product is
    listed on several pages. Records from different sources are never merged."""
    seen: set[tuple[str, str, str, str]] = set()
    out = []
    for p in products:
        key = (p.source, p.title.strip().lower(), p.price_raw, p.url.rstrip("/"))
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def _currency_from_pages(got: Acquired) -> tuple[str, str]:
    for page in got.read_pages[1:]:
        currency, source = detect_currency(page.html)
        if currency:
            return currency, source
    return "", ""


def _currency_from_products(products: list[Product]) -> tuple[str, str]:
    counts = Counter(p.currency for p in products if p.currency)
    return (counts.most_common(1)[0][0], "products") if counts else ("", "")


def _read_status(got: Acquired) -> str:
    """`ok` only with products; otherwise say why there are none."""
    if got.products:
        return "ok"
    home_text = got.pages[0].text if got.pages else ""
    return "js_required" if len(home_text) < SHELL_TEXT_CHARS else "no_products"

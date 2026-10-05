"""Three acquisition strategies, tried in order until one yields products."""

import json
import re

from .extract import (
    html_to_text,
    internal_links,
    products_from_jsonld,
    products_from_shopify_feed,
)
from .models import Acquired, Page, Product, Target

FEED_PAGE_CAP = 8
FEED_PAGE_SIZE = 250
MAX_PAGES = 25

# A homepage with less visible text than this is a JavaScript shell: the content
# arrives only after scripts run, so an empty result says nothing about the catalogue.
SHELL_TEXT_CHARS = 200

# High-value, low-volume pages. These are collected FIRST so that a store with
# thousands of product URLs cannot crowd its contact page out of the page budget.
PRIORITY_RE = re.compile(
    r"/(pages?/)?(about|our-story|contact|wholesale|stockist|brands?|designers?)", re.I
)
RELEVANT_RE = re.compile(
    r"/(product|collection|shop|catalog|pages?/about|about|contact|"
    r"brands?|designers?|wholesale|stockist)",
    re.I,
)
IRRELEVANT_RE = re.compile(
    r"/(blog|news|policies|privacy|terms|refund|shipping|cart|account|login|search)", re.I
)
LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)


def _dedupe(urls: list[str]) -> list[str]:
    seen: list[str] = []
    for u in urls:
        if u not in seen:
            seen.append(u)
    return seen


def _prioritise(urls: list[str]) -> list[str]:
    """Contact/about/wholesale pages first, then everything else in order."""
    priority = [u for u in urls if PRIORITY_RE.search(u)]
    rest = [u for u in urls if u not in priority]
    return priority + rest


def shopify_products(domain: str, fetcher) -> list[Product]:
    """Paginate a Shopify /products.json feed. Empty list if the site isn't Shopify."""
    out: list[Product] = []
    for page in range(1, FEED_PAGE_CAP + 1):
        url = f"https://{domain}/products.json?limit={FEED_PAGE_SIZE}&page={page}"
        res = fetcher.get(url)
        if not res.ok or not res.body.strip().startswith("{"):
            break
        try:
            data = json.loads(res.body)
        except ValueError:
            break
        batch = products_from_shopify_feed(data)
        if not batch:
            break
        out.extend(batch)
    return out


def sitemap_urls(domain: str, fetcher) -> list[str]:
    """Relevant URLs from sitemap.xml, following a sitemap index one level down."""
    res = fetcher.get(f"https://{domain}/sitemap.xml")
    if not res.ok:
        return []
    locs = LOC_RE.findall(res.body)

    if "<sitemapindex" in res.body.lower():
        child_locs: list[str] = []
        for child in locs[:5]:
            child_res = fetcher.get(child)
            if child_res.ok:
                child_locs.extend(LOC_RE.findall(child_res.body))
        locs = child_locs

    keep = [u for u in locs if RELEVANT_RE.search(u) and not IRRELEVANT_RE.search(u)]
    return _prioritise(_dedupe(keep))[:MAX_PAGES]


def _fetch_pages(urls: list[str], fetcher, max_pages: int) -> list[Page]:
    pages: list[Page] = []
    for url in urls[:max_pages]:
        res = fetcher.get(url)
        if res.ok and res.body:
            pages.append(Page(url=url, html=res.body, text=html_to_text(res.body)))
    return pages


def crawl_pages(domain: str, start_url: str, fetcher, max_pages: int = MAX_PAGES) -> list[Page]:
    """Homepage plus prioritised internal links, one level deep."""
    home = fetcher.get(start_url)
    if not home.ok or not home.body:
        return []
    pages = [Page(url=start_url, html=home.body, text=html_to_text(home.body))]

    links = internal_links(home.body, start_url, domain)
    relevant = [u for u in links if RELEVANT_RE.search(u) and not IRRELEVANT_RE.search(u)]
    other = [u for u in links if u not in relevant and not IRRELEVANT_RE.search(u)]
    pages.extend(_fetch_pages(_prioritise(relevant) + other, fetcher, max_pages - 1))
    return pages[:max_pages]


def acquire(target: Target, fetcher) -> Acquired:
    """Gather everything available for one store."""
    got = Acquired(domain=target.domain)

    home = fetcher.get(target.url)
    got.ssl_bypassed = home.ssl_bypassed
    if not home.ok:
        if home.status_code in (401, 403, 429):
            got.status = "blocked"
        elif home.status_code is None:
            got.status = "error"
            got.error = home.error
        else:
            got.status = "error"
            got.error = f"HTTP {home.status_code}"
        return got

    got.pages = [Page(url=target.url, html=home.body, text=html_to_text(home.body))]

    products = shopify_products(target.domain, fetcher)
    if products:
        got.source_used = "shopify_feed"
        got.products = products
        got.pages_fetched = len(got.pages)
        return got

    urls = sitemap_urls(target.domain, fetcher)
    if urls:
        got.source_used = "sitemap"
        got.pages.extend(_fetch_pages(urls, fetcher, MAX_PAGES - 1))
    else:
        got.source_used = "crawl"
        got.pages = crawl_pages(target.domain, target.url, fetcher) or got.pages

    for page in got.pages:
        got.products.extend(products_from_jsonld(page.html))

    got.pages_fetched = len(got.pages)
    got.status = _read_status(got)
    return got


def _read_status(got: Acquired) -> str:
    """`ok` only with products; otherwise say why there are none."""
    if got.products:
        return "ok"
    home_text = got.pages[0].text if got.pages else ""
    return "js_required" if len(home_text) < SHELL_TEXT_CHARS else "no_products"

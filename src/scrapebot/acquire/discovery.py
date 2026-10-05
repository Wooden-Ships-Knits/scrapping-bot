"""Finding which pages of a store to fetch, within a fixed budget."""

import re
from urllib.parse import urlparse

from ..extract.pages import internal_links, page_kind
from ..extract.text import html_to_text
from ..fetch import Fetcher
from ..models import Page

MAX_PAGES = 25
SITEMAP_INDEX_CHILDREN = 5

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


def url_key(url: str) -> str:
    """The identity of a page: `www.` and a trailing slash do not make a different page."""
    parts = urlparse(url)
    host = (parts.hostname or "").lower().removeprefix("www.")
    query = f"?{parts.query}" if parts.query else ""
    return f"{host}{parts.path.rstrip('/')}{query}"


def dedupe(urls: list[str], seen: set[str] | None = None) -> list[str]:
    """Keep the first of each page, skipping any whose key is already in `seen`."""
    keys = set(seen or ())
    out = []
    for url in urls:
        key = url_key(url)
        if key not in keys:
            keys.add(key)
            out.append(url)
    return out


def prioritise(urls: list[str]) -> list[str]:
    """Contact/about/wholesale pages first, then everything else in order."""
    priority = [u for u in urls if PRIORITY_RE.search(u)]
    rest = [u for u in urls if u not in priority]
    return priority + rest


def sitemap_urls(origin: str, fetcher: Fetcher, limit: int = MAX_PAGES) -> list[str]:
    """Relevant URLs from sitemap.xml, following a sitemap index one level down."""
    res = fetcher.get(f"{origin}/sitemap.xml")
    if not res.ok:
        return []
    locs = LOC_RE.findall(res.body)

    if "<sitemapindex" in res.body.lower():
        child_locs: list[str] = []
        for child in locs[:SITEMAP_INDEX_CHILDREN]:
            child_res = fetcher.get(child)
            if child_res.ok:
                child_locs.extend(LOC_RE.findall(child_res.body))
        locs = child_locs

    keep = [u for u in locs if RELEVANT_RE.search(u) and not IRRELEVANT_RE.search(u)]
    return prioritise(dedupe(keep))[:limit]


def crawl_urls(home_html: str, start_url: str, domain: str) -> list[str]:
    """The homepage's internal links: relevant ones first (prioritised), then the rest."""
    links = [u for u in internal_links(home_html, start_url, domain) if not IRRELEVANT_RE.search(u)]
    relevant = [u for u in links if RELEVANT_RE.search(u)]
    other = [u for u in links if u not in relevant]
    return prioritise(relevant) + other


def to_page(url: str, html: str, status: int | None, home_url: str) -> Page:
    return Page(
        url=url,
        html=html,
        text=html_to_text(html),
        kind=page_kind(url, home_url),
        http_status=status,
    )


def fetch_pages(urls: list[str], fetcher: Fetcher, limit: int, home_url: str) -> list[Page]:
    """Fetch up to `limit` pages; failed or empty responses are skipped."""
    pages: list[Page] = []
    for url in urls[: max(limit, 0)]:
        res = fetcher.get(url)
        if res.ok and res.body:
            pages.append(to_page(url, res.body, res.status_code, home_url))
    return pages

"""Finding which pages of a store to fetch, within a fixed budget (PRD AQ-07).

Order of the budget: contact/about/wholesale/stockist pages first (always, even for
stores with a feed), then deep links from the input, then product pages, then
collection pages. Sitemaps are preferred over crawling; crawling goes two levels.
"""

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from ..extract.pages import COLLECTION_RE, PRODUCT_RE, link_texts, page_kind
from ..extract.text import html_to_text
from ..fetch import Fetcher
from ..models import FetchResult, Page

MAX_PAGES = 25
PRIORITY_CAP = 8
MAX_SITEMAP_DOCUMENTS = 6

# High-value, low-volume pages, found by URL or by link text. Collected FIRST so a
# store with thousands of product URLs cannot crowd its contact page out.
PRIORITY_RE = re.compile(
    r"/(pages?/)?(about|our-story|contact|wholesale|stockist|retailers?|brands?|designers?|trade)",
    re.I,
)
PRIORITY_TEXT_RE = re.compile(
    r"\b(contact|about|our story|wholesale|stockists?|retailers?|trade|brands|designers)\b", re.I
)
IRRELEVANT_RE = re.compile(
    r"/(blogs?|news|journal|policies|privacy|terms|refund|returns|shipping|cart|checkout|"
    r"account|login|register|search|wishlist|tags?|author|feed|wp-admin|wp-login|cdn-cgi)(/|$)"
    r"|\.(jpe?g|png|gif|webp|svg|pdf|zip|mp4)$",
    re.I,
)
LOC_RE = re.compile(r"<loc>\s*(?:<!\[CDATA\[)?\s*([^<\s\]]+)", re.I)
SITEMAP_SKIP_RE = re.compile(r"post|blog|news|article|image|video|author|tag", re.I)


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


def link_role(url: str, text: str = "") -> str:
    """priority | product | collection | other | skip"""
    path = urlparse(url).path
    if IRRELEVANT_RE.search(path):
        return "skip"
    if PRIORITY_RE.search(path) or PRIORITY_TEXT_RE.search(text):
        return "priority"
    if PRODUCT_RE.search(path):
        return "product"
    if COLLECTION_RE.search(path):
        return "collection"
    return "other"


@dataclass
class RankedLinks:
    priority: list[str] = field(default_factory=list)
    product: list[str] = field(default_factory=list)
    collection: list[str] = field(default_factory=list)
    other: list[str] = field(default_factory=list)

    def add(self, url: str, text: str = "") -> None:
        role = link_role(url, text)
        if role != "skip":
            getattr(self, role).append(url)


def rank_links(html: str, base_url: str, domain: str) -> RankedLinks:
    ranked = RankedLinks()
    for url, text in link_texts(html, base_url, domain):
        if url_key(url) != url_key(base_url):
            ranked.add(url, text)
    return ranked


def _looks_like_sitemap(body: str) -> bool:
    head = body.lstrip()[:2000].lower()
    return "<urlset" in head or "<sitemapindex" in head


def _is_sitemap_url(url: str) -> bool:
    return bool(re.search(r"\.xml(\.gz)?($|\?)", url, re.I))


@dataclass
class SitemapUrls:
    products: list[str] = field(default_factory=list)
    pages: RankedLinks = field(default_factory=RankedLinks)
    found: bool = False


def sitemap_urls(origin: str, fetcher: Fetcher, declared: list[str] | None = None) -> SitemapUrls:
    """Page URLs from the store's sitemaps.

    Tolerates what real stores serve: sitemap indexes, plain urlsets that list other
    sitemaps, gzipped sitemaps, and an HTML page with status 200 instead of a sitemap.
    Product sitemaps are read first; blog and image sitemaps are skipped.
    """
    out = SitemapUrls()
    queue: list[str] = list(dict.fromkeys([*(declared or []), f"{origin}/sitemap.xml"]))
    fetched = 0
    while queue and fetched < MAX_SITEMAP_DOCUMENTS:
        url = queue.pop(0)
        fetched += 1
        res = fetcher.get(url)
        if not res.ok or not _looks_like_sitemap(res.body):
            continue
        out.found = True
        locs: list[str] = LOC_RE.findall(res.body)
        children = [loc for loc in locs if _is_sitemap_url(loc)]
        if children and (len(children) == len(locs) or "<sitemapindex" in res.body[:2000].lower()):
            children = [c for c in children if not SITEMAP_SKIP_RE.search(urlparse(c).path)]
            children.sort(key=lambda c: 0 if "product" in c.lower() else 1)
            queue = list(dict.fromkeys([*children, *queue]))
            continue
        product_sitemap = "product" in url.lower()
        for loc in locs:
            if product_sitemap and link_role(loc) not in ("skip", "priority"):
                out.products.append(loc)
            else:
                out.pages.add(loc)
    out.products = dedupe(out.products)
    return out


def failure_reason(res: FetchResult) -> str:
    """Why a response is not a readable page."""
    if res.error:
        return res.error
    if res.challenge:
        return f"challenge page ({res.challenge})"
    if res.status_code != 200:
        return f"HTTP {res.status_code}"
    return "empty page"


def to_page(url: str, res: FetchResult, home_url: str) -> Page:
    kind = page_kind(url, home_url)
    if res.ok and res.body:
        text = html_to_text(res.body)
        return Page(url=url, html=res.body, text=text, kind=kind, http_status=res.status_code)
    return Page(url=url, kind=kind, http_status=res.status_code, error=failure_reason(res))


def fetch_pages(urls: list[str], fetcher: Fetcher, limit: int, home_url: str) -> list[Page]:
    """Fetch up to `limit` pages. Pages that fail are kept, with the reason, so a broken
    contact or deep link is visible in the output."""
    return [to_page(url, fetcher.get(url), home_url) for url in urls[: max(limit, 0)]]

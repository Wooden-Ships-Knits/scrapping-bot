"""Links between pages, and what kind of page each one is."""

import html as html_lib
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..models import Page

WHOLESALE_RE = re.compile(r"wholesale|stockist|trade[\-_ ]?account|retailer|become[\-_ ]a", re.I)
ABOUT_RE = re.compile(r"/about|/our-story|/pages/about", re.I)
META_DESC_RE = re.compile(
    r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)["\']', re.I
)

# Checked in order against the URL path; the first match names the page.
PAGE_KINDS = (
    ("wholesale", re.compile(r"wholesale|trade[\-_ ]?account|become[\-_ ]a", re.I)),
    ("stockist", re.compile(r"stockist|retailer|where[\-_ ]to[\-_ ]buy", re.I)),
    ("contact", re.compile(r"contact", re.I)),
    ("about", re.compile(r"about|our[\-_ ]story", re.I)),
    ("brands", re.compile(r"/(brands?|designers?)(/|$)", re.I)),
    ("product", re.compile(r"/products?/", re.I)),
    ("collection", re.compile(r"/(collections?|shop|catalog|category)(/|$)", re.I)),
)


def page_kind(url: str, home_url: str = "") -> str:
    """home | wholesale | stockist | contact | about | brands | product | collection | other."""
    path = urlparse(url).path.rstrip("/")
    if not path or url.rstrip("/") == home_url.rstrip("/"):
        return "home"
    for kind, rx in PAGE_KINDS:
        if rx.search(path):
            return kind
    return "other"


def about_snippet(pages: list[Page], limit: int = 300) -> str:
    """Text from an About page, else the meta description. Truncated."""
    for page in pages:
        if ABOUT_RE.search(page.url) and page.text:
            return page.text[:limit].strip()
    for page in pages:
        m = META_DESC_RE.search(page.html or "")
        description = html_lib.unescape(m.group(1)).strip() if m else ""
        if description:
            return description[:limit]
    return ""


def find_wholesale_page(pages: list[Page]) -> str:
    """URL of a wholesale/stockist/trade page, if one was visited."""
    for page in pages:
        if WHOLESALE_RE.search(page.url):
            return page.url
    return ""


def _on_domain(host: str, domain: str) -> bool:
    host = host.lower()
    return host == domain or host.endswith("." + domain)


def link_texts(html: str, base_url: str, domain: str) -> list[tuple[str, str]]:
    """(absolute url, link text) for http(s) links to `domain` or its subdomains, first
    occurrence of each url, in page order."""
    soup = BeautifulSoup(html or "", "lxml")
    out: dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        href = str(a["href"]).strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        url = urljoin(base_url, href).split("#")[0].rstrip("/")
        if not url.startswith("http") or not _on_domain(urlparse(url).hostname or "", domain):
            continue
        text = " ".join(a.get_text(" ").split()) or str(a.get("title") or a.get("aria-label") or "")
        out.setdefault(url, text)
    return list(out.items())


def internal_links(html: str, base_url: str, domain: str) -> list[str]:
    """Absolute, deduplicated http(s) links to `domain` or its subdomains."""
    return [url for url, _ in link_texts(html, base_url, domain)]

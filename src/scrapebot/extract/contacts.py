"""Emails, phones and social profiles, as found on each page."""

import re

from ..models import Contact, Page

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
MAILTO_RE = re.compile(r'mailto:([^"\'?>\s]+)', re.I)
TEL_RE = re.compile(r"tel:([+\d][\d\-().\s]{6,})", re.I)
# US formats only; per-region parsing with `phonenumbers` comes in M5 (issue 5).
PHONE_TEXT_RE = re.compile(r"\(?\b\d{3}\)?[\s.\-]\d{3}[\s.\-]\d{4}\b")
ASSET_SUFFIX_RE = re.compile(r"\.(png|jpe?g|gif|svg|webp|css|js)$", re.I)
# Addresses that are never a store's contact: reserved example domains (RFC 2606),
# form placeholders, and error-tracker addresses embedded by site builders.
NOT_A_CONTACT_RE = re.compile(
    r"@(example\.(com|org|net)|(your)?domain\.com|sentry[\w.-]*|[\w.-]*\.wixpress\.com)$", re.I
)

SOCIAL_NETWORKS = {
    "instagram": re.compile(r'https?://(?:www\.)?instagram\.com/[^"\'\s>]+', re.I),
    "facebook": re.compile(r'https?://(?:www\.|m\.)?facebook\.com/[^"\'\s>]+', re.I),
    "tiktok": re.compile(r'https?://(?:www\.)?tiktok\.com/@[^"\'\s>]+', re.I),
    "linkedin": re.compile(
        r'https?://(?:[a-z]{2,3}\.)?linkedin\.com/(?:company|in)/[^"\'\s>]+', re.I
    ),
    "pinterest": re.compile(r'https?://(?:[a-z]{2,3}\.)?pinterest\.[a-z.]+/[^"\'\s>]+', re.I),
}
_SOCIAL_JUNK = ("sharer", "/share", "intent", "plugins/", "/tr?", "dialog/", "pin/create")

MAX_EMAILS_PER_PAGE = 20
MAX_PHONES_PER_PAGE = 10


def _dedupe(items: list[str]) -> list[str]:
    seen: list[str] = []
    for i in items:
        if i and i not in seen:
            seen.append(i)
    return seen


def extract_emails(html: str) -> list[str]:
    """Emails from mailto: links first, then from page text. Deduplicated, order preserved."""
    found = [m.split("?")[0].strip() for m in MAILTO_RE.findall(html or "")]
    found += EMAIL_RE.findall(html or "")
    return _dedupe(
        [e for e in found if not ASSET_SUFFIX_RE.search(e) and not NOT_A_CONTACT_RE.search(e)]
    )


def extract_phones(html: str) -> list[str]:
    """Phone numbers from tel: links and page text."""
    found = [m.strip() for m in TEL_RE.findall(html or "")]
    found += [m.strip() for m in PHONE_TEXT_RE.findall(html or "")]
    return _dedupe(found)


def extract_social_links(html: str) -> dict[str, list[str]]:
    """Every profile URL per network. Share, intent and tracking links are ignored."""
    out: dict[str, list[str]] = {}
    for network, rx in SOCIAL_NETWORKS.items():
        urls = [u for u in rx.findall(html or "") if not any(j in u.lower() for j in _SOCIAL_JUNK)]
        out[network] = _dedupe(urls)
    return out


def extract_socials(html: str) -> dict[str, str]:
    """The first Instagram and Facebook profile URL, "" when absent."""
    links = extract_social_links(html)
    return {network: (links[network] or [""])[0] for network in ("instagram", "facebook")}


def find_contacts(pages: list[Page]) -> list[Contact]:
    """Contacts across a store's pages, each with the first page it was seen on."""
    found: list[Contact] = []
    seen: set[tuple[str, str]] = set()

    def add(kind: str, value: str, source_url: str) -> None:
        key = (kind, value.lower())
        if value and key not in seen:
            seen.add(key)
            found.append(Contact(type=kind, value=value, source_url=source_url))

    for page in pages:
        for email in extract_emails(page.html)[:MAX_EMAILS_PER_PAGE]:
            add("email", email, page.url)
        for phone in extract_phones(page.html)[:MAX_PHONES_PER_PAGE]:
            add("phone", phone, page.url)
        for network, urls in extract_social_links(page.html).items():
            for url in urls:
                add(network, url, page.url)
    return found

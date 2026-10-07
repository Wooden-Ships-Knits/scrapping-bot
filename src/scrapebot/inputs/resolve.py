"""Turn input records into stores to visit, accounting for every link (PRD IN-04 to IN-07).

Every input record ends in exactly one state: `processed` (it starts or joins a
store visit) or a skip reason. Links are grouped by registrable domain, so
`www.a.com` and `a.com/shop` are one store.
"""

import ipaddress
import re
from dataclasses import dataclass, field
from functools import cache
from typing import Any
from urllib.parse import urlparse

from ..models import Target
from .readers import InputRecord

PROCESSED = "processed"
DUPLICATE = "duplicate"
OVER_LIMIT = "over_limit"
NO_WEBSITE = "no_website"
INVALID_URL = "invalid_url"
SOCIAL_ONLY = "social_only"
MARKETPLACE = "marketplace"

# Matched on the registrable domain's name, so every country suffix is covered
# (amazon.com, amazon.co.uk, ...).
SOCIAL_NAMES = frozenset({
    "instagram", "facebook", "twitter", "tiktok", "linkedin", "pinterest", "youtube",
    "threads", "snapchat", "whatsapp",
})  # fmt: skip
SOCIAL_DOMAINS = frozenset({"x.com", "fb.com", "linktr.ee", "wa.me", "youtu.be"})
MARKETPLACE_NAMES = frozenset({
    "amazon", "etsy", "ebay", "walmart", "poshmark", "depop", "faire", "mercari", "grailed",
    "vinted", "aliexpress", "alibaba", "shopee", "lazada", "tokopedia",
})  # fmt: skip

# Hosts where each subdomain is a separate store but that the Public Suffix List does
# not list as private suffixes (myshopify.com, wixsite.com, square.site already are).
HOSTED_STORE_DOMAINS = frozenset({
    "bigcartel.com", "squarespace.com", "mybigcommerce.com", "shoplightspeed.com",
    "webshopapp.com", "storenvy.com", "myshopline.com", "weebly.com", "godaddysites.com",
    "jimdosite.com", "company.site", "business.site", "wordpress.com", "ueniweb.com",
    "mystrikingly.com", "ecwid.com", "shopsettings.com",
})  # fmt: skip

_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")


@dataclass
class ResolvedInput:
    input_id: int  # 1-based position in the input
    raw: str
    url: str
    domain: str
    status: str
    is_deep_link: bool = False
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class Resolution:
    inputs: list[ResolvedInput]
    targets: list[Target]

    @property
    def processed(self) -> list[ResolvedInput]:
        return [i for i in self.inputs if i.status == PROCESSED]

    @property
    def skipped(self) -> list[ResolvedInput]:
        return [i for i in self.inputs if i.status != PROCESSED]


def normalize_url(raw: str) -> str:
    """Add a scheme if missing, strip whitespace and any trailing slash.

    An existing scheme is detected case-insensitively and left alone (so
    "HTTP://..." and "ftp://..." are not mistaken for scheme-less input).
    A protocol-relative value ("//host/path") gets an "https:" prefix rather
    than a full "https://" prepended in front of its own leading slashes.
    """
    u = (raw or "").strip()
    if not u:
        return ""
    if u.startswith("//"):
        u = "https:" + u
    elif not _SCHEME_RE.match(u):
        u = "https://" + u
    return u.rstrip("/")


@cache
def _tld_extractor():
    import tldextract

    # The bundled Public Suffix List snapshot: no network call, same answer every run.
    # Private suffixes on, so brand.wixsite.com and brand.myshopify.com stay separate stores.
    return tldextract.TLDExtract(
        suffix_list_urls=(), cache_dir=None, include_psl_private_domains=True
    )


def registrable_domain(host: str) -> str:
    """The domain a store owns ("shop.example.co.uk" -> "example.co.uk"), or "" if none.

    On a shared store host the store owns its subdomain ("brand.bigcartel.com").
    """
    parts = _tld_extractor()(host)
    if not (parts.suffix and parts.domain):
        return ""
    domain = parts.top_domain_under_public_suffix.lower()
    store = parts.subdomain.lower().split(".")[-1] if parts.subdomain else ""
    if domain in HOSTED_STORE_DOMAINS and store not in ("", "www"):
        return f"{store}.{domain}"
    return domain


def canonical_domain(raw: str) -> str:
    """The registrable domain of a link, or "" when the link has none."""
    host = urlparse(normalize_url(raw)).hostname or ""
    return registrable_domain(host) if host else ""


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def classify(raw: str) -> tuple[str, str, str]:
    """(status, url, domain) for one link. Status is PROCESSED or a skip reason."""
    url = normalize_url(raw)
    if not url:
        return NO_WEBSITE, "", ""
    parts = urlparse(url)
    host = (parts.hostname or "").lower()
    if not host:
        return NO_WEBSITE, url, ""
    if parts.scheme.lower() not in ("http", "https") or _is_ip(host):
        return INVALID_URL, url, ""
    domain = registrable_domain(host)
    if not domain:
        return INVALID_URL, url, ""
    name = _tld_extractor()(domain).domain
    if domain in SOCIAL_DOMAINS or name in SOCIAL_NAMES:
        return SOCIAL_ONLY, url, domain
    if name in MARKETPLACE_NAMES:
        return MARKETPLACE, url, domain
    return PROCESSED, url, domain


def _origin(url: str) -> str:
    parts = urlparse(url)
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme.lower()}://{(parts.hostname or '').lower()}{port}"


def _is_deep_link(url: str) -> bool:
    parts = urlparse(url)
    return parts.path not in ("", "/") or bool(parts.query)


def resolve(records: list[InputRecord], limit: int | None = None) -> Resolution:
    """Group links into stores in input order. `limit` keeps the first N stores (test mode)."""
    inputs: list[ResolvedInput] = []
    targets: dict[str, Target] = {}

    for input_id, record in enumerate(records, start=1):
        status, url, domain = classify(record.value)
        deep = status == PROCESSED and _is_deep_link(url)
        if status == PROCESSED:
            if domain in targets:
                status = DUPLICATE
            else:
                targets[domain] = Target(domain=domain, url=_origin(url))
            target = targets[domain]
            target.input_ids.append(input_id)
            if deep and url not in target.deep_links:
                target.deep_links.append(url)
        inputs.append(
            ResolvedInput(
                input_id=input_id,
                raw=record.value,
                url=url,
                domain=domain,
                status=status,
                is_deep_link=deep,
                meta=record.meta,
            )
        )

    kept = list(targets.values())
    if limit is not None:
        dropped = {t.domain for t in kept[limit:]}
        kept = kept[:limit]
        for item in inputs:
            if item.domain in dropped and item.status in (PROCESSED, DUPLICATE):
                item.status = OVER_LIMIT
    return Resolution(inputs=inputs, targets=kept)

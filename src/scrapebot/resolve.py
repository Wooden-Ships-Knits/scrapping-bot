"""Turn raw CSV rows into a deduplicated list of scrape targets."""

import csv
import re
from urllib.parse import urlparse

from .models import Target

SOCIAL_HOSTS = ("instagram.com", "facebook.com", "twitter.com", "x.com", "tiktok.com")

_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")


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


def _host(raw: str) -> str:
    """Lowercase host with userinfo, port, and any leading 'www.' removed.

    Returns "" when the value has no parseable host (e.g. a bare path).
    """
    normalized = normalize_url(raw)
    if not normalized:
        return ""
    host = (urlparse(normalized).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def canonical_domain(raw: str) -> str:
    """Lowercase host with any leading 'www.' removed."""
    return _host(raw)


def classify_row(row: dict) -> str:
    """Return 'no_website', 'social_only', or 'ok'."""
    website = (row.get("website") or "").strip()
    if not website:
        return "no_website"
    host = _host(website)
    if not host:
        return "no_website"
    if host in SOCIAL_HOSTS or any(host.endswith("." + s) for s in SOCIAL_HOSTS):
        return "social_only"
    return "ok"


def load_targets(csv_path: str) -> tuple[list[Target], list[tuple[dict, str]]]:
    """Read the input CSV.

    Returns (targets, skipped) where skipped is a list of (row, reason) for
    rows that need no fetching. Every input row appears in exactly one of the two.
    """
    targets: dict[str, Target] = {}
    skipped: list[tuple[dict, str]] = []

    with open(csv_path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            reason = classify_row(row)
            if reason != "ok":
                skipped.append((row, reason))
                continue
            domain = canonical_domain(row["website"])
            if domain in targets:
                targets[domain].rows.append(row)
            else:
                targets[domain] = Target(
                    domain=domain,
                    url=normalize_url(row["website"]),
                    rows=[row],
                )
    return list(targets.values()), skipped

"""Who a store says it is, in its own markup: name, phone, email, address, position and
profiles, as found.

Page HTML is never stored (ADR 0006), so this is read while the home, contact and about
pages are still in memory, or it is lost: on the 2026-10-09 run a pasted list had no store
names at all, and only 48% of stores gave an address in their visible text. Sources, most
specific first: schema.org Organization, LocalBusiness and its store types (ClothingStore,
Store, ...) in JSON-LD or Microdata; then `og:site_name`, the page title and the meta
description. Values are kept as the site wrote them (raw means raw).
"""

import re
from typing import Any

from ..models import Page

# schema.org types a shop describes itself with.
SELF_TYPES = re.compile(
    r"^(Organization|Corporation|LocalBusiness|Store|OnlineStore|OnlineBusiness|"
    r"\w*Store|\w*Shop|ShoppingCenter)$"
)
FIELDS = ("name", "legalName", "telephone", "email", "url", "openingHours")
ADDRESS_FIELDS = (
    "streetAddress", "addressLocality", "addressRegion", "postalCode", "addressCountry",
)  # fmt: skip
IDENTITY_PAGES = ("home", "contact", "about")
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
_META_RE = re.compile(
    r"<meta[^>]+(?:property|name)=[\"'](og:site_name|description)[\"'][^>]*>", re.I
)
_CONTENT_RE = re.compile(r"content=[\"']([^\"']*)[\"']", re.I)


def _text(value: Any) -> str:
    if isinstance(value, list):
        value = next((v for v in value if v), "")
    if isinstance(value, dict):
        value = value.get("@value") or value.get("name") or ""
    return " ".join(str(value or "").split())


def _types(node: dict[str, Any]) -> list[str]:
    kind = node.get("@type") or node.get("type") or []
    kinds = kind if isinstance(kind, list) else [kind]
    return [str(k).rsplit("/", 1)[-1] for k in kinds]


def _nodes(data: Any) -> list[dict[str, Any]]:
    """Every object in the structured data, @graph included."""
    out: list[dict[str, Any]] = []
    stack = [data]
    while stack:
        item = stack.pop()
        if isinstance(item, list):
            stack.extend(item)
        elif isinstance(item, dict):
            out.append(item)
            stack.extend(v for k, v in item.items() if k in ("@graph", "properties"))
    return out


def _organization(node: dict[str, Any]) -> dict[str, Any]:
    inner = node.get("properties")
    props: dict[str, Any] = inner if isinstance(inner, dict) else node
    org: dict[str, Any] = {"type": _types(node)[0] if _types(node) else ""}
    for field in FIELDS:
        if value := _text(props.get(field)):
            org[field] = value
    address = props.get("address")
    address = address[0] if isinstance(address, list) and address else address
    if isinstance(address, dict):
        found = {f: _text(address.get(f)) for f in ADDRESS_FIELDS if _text(address.get(f))}
        if found:
            org["address"] = found
    elif _text(address):
        org["address"] = {"streetAddress": _text(address)}
    geo = props.get("geo")
    if isinstance(geo, dict) and _text(geo.get("latitude")) and _text(geo.get("longitude")):
        org["geo"] = {"latitude": _text(geo["latitude"]), "longitude": _text(geo["longitude"])}
    same_as = props.get("sameAs")
    links = same_as if isinstance(same_as, list) else [same_as]
    if profiles := [str(link) for link in links if isinstance(link, str) and link.strip()]:
        org["sameAs"] = profiles
    return org


def organizations(html: str, page_url: str) -> list[dict[str, Any]]:
    import extruct

    try:
        data = extruct.extract(
            html or "", base_url=page_url, syntaxes=["json-ld", "microdata"], errors="ignore"
        )
    except Exception:  # malformed markup is never fatal
        return []
    found = []
    for syntax in ("json-ld", "microdata"):
        for node in _nodes(data.get(syntax, [])):
            if any(SELF_TYPES.match(t) for t in _types(node)):
                org = _organization(node)
                if len(org) > 1 and org not in found:
                    found.append(org)
    return found


def store_identity(pages: list[Page]) -> dict[str, Any]:
    """What the store's home, contact and about pages say about the store; {} when none."""
    identity: dict[str, Any] = {}
    orgs: list[dict[str, Any]] = []
    for page in sorted(
        (p for p in pages if p.kind in IDENTITY_PAGES and p.html),
        key=lambda p: IDENTITY_PAGES.index(p.kind),
    ):
        for org in organizations(page.html, page.url):
            if org not in orgs:
                orgs.append({**org, "page": page.url})
        if page.kind != "home":
            continue
        if (title := _TITLE_RE.search(page.html)) and "title" not in identity:
            identity["title"] = " ".join(title.group(1).split())[:300]
        for meta in _META_RE.finditer(page.html):
            content = _CONTENT_RE.search(meta.group(0))
            key = "site_name" if meta.group(1).lower() == "og:site_name" else "description"
            if content and content.group(1).strip() and key not in identity:
                identity[key] = " ".join(content.group(1).split())[:500]
    if orgs:
        identity["organizations"] = orgs[:5]
    return identity

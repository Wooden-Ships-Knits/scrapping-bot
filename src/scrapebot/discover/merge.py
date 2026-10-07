"""Sightings from every source -> one row per store.

A `Candidate` is one sighting: a place Google Maps returned, a search result, an
Instagram profile, a store the agent named. Two sightings are the same store when
they share a website domain, an Instagram or Facebook profile, or a name plus
postal code or town.
"""

import re
from typing import Any
from urllib.parse import parse_qs, urlsplit

from pydantic import BaseModel, ConfigDict, Field

from ..inputs.resolve import PROCESSED, canonical_domain, classify
from . import geo

_COMPANY_SUFFIX = re.compile(r"(inc|llc|ltd|co|corp|company)$")
# First path segments that are not a profile.
_IG_NOT_PROFILE = frozenset({
    "p", "reel", "reels", "explore", "tags", "stories", "tv", "accounts", "about",
    "developer", "directory", "legal", "web", "challenge", "share",
})  # fmt: skip
_FB_NOT_PROFILE = frozenset({
    "groups", "events", "watch", "marketplace", "sharer", "sharer.php", "share", "login",
    "help", "policies", "hashtag", "photo", "photo.php", "photos", "videos", "story.php",
    "permalink.php", "plugins", "dialog", "l.php", "tr", "business", "gaming", "reel",
    "public", "search", "home.php",
})  # fmt: skip
# Pages about many businesses: a link there is not a store's own website.
DIRECTORY_DOMAINS = frozenset({
    "yelp.com", "yelp.ca", "tripadvisor.com", "mapquest.com", "yellowpages.com",
    "yellowpages.ca", "bbb.org", "nextdoor.com", "foursquare.com", "manta.com", "google.com",
    "goo.gl", "reddit.com", "wikipedia.org", "beacons.ai", "linkin.bio", "taplink.cc",
    "shopmy.us", "ltk.app", "shop.app", "bit.ly", "chamberofcommerce.com", "zoominfo.com",
    "loc8nearme.com", "wanderlog.com", "birdeye.com", "alignable.com", "shopify.com",
})  # fmt: skip


# A Maps listing name is cleaner than a page title or an agent's spelling.
NAME_RANK = {"google_places": 0}


def name_rank(sources: list[str]) -> int:
    return min((NAME_RANK.get(s, 9) for s in sources), default=9)


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Candidate(_Record):
    name: str
    source: str  # google_places | web_search | social_search | ai_agent
    website: str = ""
    instagram: str = ""
    facebook: str = ""
    address: str = ""
    city: str = ""
    state: str = ""
    postal_code: str = ""
    country: str = ""
    phone: str = ""
    place_id: str = ""
    business_status: str = ""
    note: str = ""  # search snippet, profile bio or the agent's note
    query: str = ""  # the search that found it

    def has_place(self) -> bool:
        return bool(self.address or self.city)


class Location(_Record):
    address: str = ""
    city: str = ""
    state: str = ""
    postal_code: str = ""
    country: str = ""
    phone: str = ""
    place_id: str = ""

    def key(self) -> tuple[str, str, str]:
        """Same building: same postal code (or town) and street number."""
        number = re.match(r"\s*(\d+)", self.address)
        street = number.group(1) if number else geo.key(self.address)
        return (self.postal_code[:5] or geo.key(self.city), street, self.state)

    def near(self, other: "Location") -> bool:
        """Same postal code or town."""
        if self.postal_code and other.postal_code:
            return self.postal_code[:5] == other.postal_code[:5]
        same_state = not self.state or not other.state or self.state == other.state
        return bool(self.city) and geo.key(self.city) == geo.key(other.city) and same_state


class FoundStore(_Record):
    store_id: str = ""
    name: str
    website: str = ""
    website_source: str = ""  # source (a search gave it) | lookup (found by name later)
    instagram: str = ""
    facebook: str = ""
    locations: list[Location] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    queries: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    keys: list[str] = Field(default_factory=list)  # every identity it is known by

    @property
    def primary(self) -> Location:
        return self.locations[0] if self.locations else Location()

    def absorb(self, other: "FoundStore") -> None:
        """Fold another record of the same store into this one."""
        if name_rank(other.sources) < name_rank(self.sources):
            self.name = other.name
        self.website = self.website or other.website
        self.website_source = self.website_source or other.website_source
        self.instagram = self.instagram or other.instagram
        self.facebook = self.facebook or other.facebook
        seen = {loc.key() for loc in self.locations}
        self.locations += [loc for loc in other.locations if loc.key() not in seen]
        for attr in ("sources", "queries", "notes", "keys"):
            mine = getattr(self, attr)
            mine += [value for value in getattr(other, attr) if value not in mine]


def store_website(url: str, exclude: frozenset[str] = frozenset()) -> str:
    """The registrable domain of a store's own website, or "" for a social profile,
    marketplace, directory or excluded domain."""
    if not url.strip():
        return ""
    status, _, domain = classify(url)
    if status != PROCESSED or domain in DIRECTORY_DOMAINS or domain in exclude:
        return ""
    return domain


def origin_of(url: str) -> str:
    parts = urlsplit(url if "//" in url else "https://" + url)
    return f"{parts.scheme or 'https'}://{parts.netloc.lower()}"


def social_profile(value: str, network: str = "") -> tuple[str, str, str] | None:
    """An Instagram or Facebook profile link (or bare handle) -> (network, key, URL).

    'https://www.instagram.com/Cedar.Hyde/?hl=en' -> ('instagram', 'cedar.hyde', ...)
    '@cedar.hyde' with network='instagram'        -> the same
    Posts, reels, groups, events and share links are not profiles -> None.
    """
    text = value.strip()
    if not text:
        return None
    if (
        network
        and re.fullmatch(r"@?[\w.\-]{2,60}", text)
        and not re.search(r"\.(com|net|org|co|me)$", text.lower())
    ):
        handle = text.lstrip("@")
        if network == "instagram":
            return network, handle.lower(), f"https://www.instagram.com/{handle.lower()}/"
        return network, handle.lower(), f"https://www.facebook.com/{handle}"
    parts = urlsplit(text if "//" in text else "https://" + text)
    host = re.sub(r"^(www|m|web|l|business)\.", "", (parts.hostname or "").lower())
    segments = [seg for seg in parts.path.split("/") if seg]
    if host in ("instagram.com", "instagr.am"):
        if (
            not segments
            or segments[0].lower() in _IG_NOT_PROFILE
            or not re.fullmatch(r"[\w.]{1,40}", segments[0])
        ):
            return None
        handle = segments[0].lower()
        return "instagram", handle, f"https://www.instagram.com/{handle}/"
    if host in ("facebook.com", "fb.com", "fb.me"):
        if not segments:
            return None
        first = segments[0].lower()
        if first == "profile.php":
            ident = (parse_qs(parts.query).get("id") or [""])[0]
            if not ident:
                return None
            return "facebook", f"id:{ident}", f"https://www.facebook.com/profile.php?id={ident}"
        if first in ("people", "pages", "p") and len(segments) >= 2:
            path = "/".join(segments[: 3 if first != "p" else 2])
            return "facebook", f"id:{segments[-1].lower()}", f"https://www.facebook.com/{path}"
        if first in _FB_NOT_PROFILE:
            return None
        return "facebook", first, f"https://www.facebook.com/{segments[0]}"
    return None


def name_key(name: str) -> str:
    base = geo.key(re.sub(r"^\s*the\s+", "", name, flags=re.I))
    return _COMPANY_SUFFIX.sub("", base) or base


def _identity_keys(cand: Candidate, site: str, profiles: list[tuple[str, str, str]], country: str):
    keys = [f"site:{site}"] if site else []
    keys += [f"{network[:2]}:{handle}" for network, handle, _ in profiles]
    region = geo.state_code(cand.state) or cand.state or country
    # One source may know the postal code and another only the town: register both.
    if cand.postal_code:
        keys.append(f"place:{name_key(cand.name)}|{cand.postal_code[:5]}|{region}")
    if cand.city:
        keys.append(f"place:{name_key(cand.name)}|{geo.key(cand.city)}|{region}")
    return keys


def _add_location(store: FoundStore, loc: Location) -> None:
    """Keep one entry per building; a full address replaces a town-only sighting."""
    if loc.address:
        for position, existing in enumerate(store.locations):
            if not existing.address and loc.near(existing):
                store.locations[position] = loc
                return
    vague = not loc.address and any(loc.near(existing) for existing in store.locations)
    if not vague and loc.key() not in {existing.key() for existing in store.locations}:
        store.locations.append(loc)
        return
    for existing in store.locations:  # seen again: keep detail the first sighting lacked
        if existing.key() == loc.key() or (vague and loc.near(existing)):
            for attr in ("phone", "place_id", "postal_code"):
                if not getattr(existing, attr) and getattr(loc, attr):
                    setattr(existing, attr, getattr(loc, attr))
            return


def merge(
    candidates: list[Candidate], countries: list[str], exclude_domains: list[str]
) -> list[FoundStore]:
    """One store per business. Dropped: places outside `countries`, permanently closed
    places, excluded domains, and bare names with nothing to follow (no website,
    profile or place)."""
    exclude = frozenset(canonical_domain(d) or d for d in exclude_domains)
    stores: list[FoundStore] = []
    index: dict[str, FoundStore] = {}
    for cand in candidates:
        if not cand.name.strip() or cand.business_status == "CLOSED_PERMANENTLY":
            continue
        country = geo.infer_country(cand.country, cand.state, cand.postal_code)
        if country and country not in countries:
            continue
        instagram, facebook = cand.instagram, cand.facebook
        linked = social_profile(cand.website)  # a "website" that is really a profile
        if linked:
            if linked[0] == "instagram":
                instagram = instagram or linked[2]
            else:
                facebook = facebook or linked[2]
        if cand.website and not linked and canonical_domain(cand.website) in exclude:
            continue
        site = store_website(cand.website, exclude)
        profiles = [
            p
            for p in (social_profile(instagram, "instagram"), social_profile(facebook, "facebook"))
            if p
        ]
        keys = _identity_keys(cand, site, profiles, country)
        if not keys:
            continue

        matched: list[FoundStore] = []
        for k in keys:
            hit = index.get(k)
            if hit is not None and hit not in matched:
                matched.append(hit)
        if matched:
            store = matched[0]
            for other in matched[1:]:  # this sighting links two records of one store
                store.absorb(other)
                stores.remove(other)
                for k in other.keys:
                    index[k] = store
        else:
            store = FoundStore(name=cand.name.strip())
            stores.append(store)

        if store.sources and name_rank([cand.source]) < name_rank(store.sources):
            store.name = cand.name.strip()
        if site and not store.website:
            store.website = origin_of(cand.website)
            store.website_source = "source"
        for network, _, url in profiles:
            if network == "instagram":
                store.instagram = store.instagram or url
            else:
                store.facebook = store.facebook or url
        if cand.source not in store.sources:
            store.sources.append(cand.source)
        if cand.query and cand.query not in store.queries and len(store.queries) < 8:
            store.queries.append(cand.query)
        note = cand.note.strip()[:400]
        if note and note not in store.notes and len(store.notes) < 4:
            store.notes.append(note)
        if cand.has_place():
            _add_location(
                store,
                Location(
                    address=cand.address,
                    city=cand.city,
                    state=cand.state,
                    postal_code=cand.postal_code,
                    country=country,
                    phone=cand.phone,
                    place_id=cand.place_id,
                ),
            )
        for k in keys:
            if k not in store.keys:
                store.keys.append(k)
            index[k] = store

    for store in stores:
        store.store_id = store_id(store)
    return sorted(stores, key=lambda s: s.store_id)


def store_id(store: FoundStore) -> str:
    """Stable and readable: the website domain, else the place, else the profile."""
    if store.website:
        return canonical_domain(store.website)
    for prefix in ("place:", "in:", "fa:"):
        for k in store.keys:
            if k.startswith(prefix):
                return k.removeprefix("place:")
    return name_key(store.name)


def export_row(store: FoundStore) -> dict[str, Any]:
    """One row of `stores.csv`, the links file `scrapebot run` reads."""
    loc = store.primary
    return {
        "website": store.website,
        "name": store.name,
        "instagram": store.instagram,
        "facebook": store.facebook,
        "address": loc.address,
        "city": loc.city,
        "state": loc.state,
        "postal_code": loc.postal_code,
        "country": loc.country,
        "phone": loc.phone,
        "location_count": len(store.locations),
        "sources": "; ".join(store.sources),
        "website_source": store.website_source,
        "found_by": " | ".join(store.queries),
        "notes": " | ".join(store.notes),
        "place_id": loc.place_id,
        "store_id": store.store_id,
    }


EXPORT_COLUMNS = list(export_row(FoundStore(name="")).keys())


def fold_by_website(stores: list[FoundStore]) -> list[FoundStore]:
    """Fold stores that share a website domain into one. Needed after the website lookup,
    which can give a store found only by name the site of another row (two sightings in
    different towns, or with and without a state)."""
    by_domain: dict[str, FoundStore] = {}
    kept: list[FoundStore] = []
    for store in stores:
        domain = canonical_domain(store.website) if store.website else ""
        first = by_domain.get(domain) if domain else None
        if first is None:
            if domain:
                by_domain[domain] = store
            kept.append(store)
            continue
        # A website the search gave beats one found by name.
        if first.website_source == "lookup" and store.website_source == "source":
            first.website, first.website_source = store.website, store.website_source
        first.absorb(store)
    for store in kept:
        store.store_id = store_id(store)
    return sorted(kept, key=lambda s: s.store_id)

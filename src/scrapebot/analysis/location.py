"""Where a store is, and how far it is from the nearest Wooden Ships stockist.

The address comes from the input row when the links came from discovery (Google Places
gives one), else from the store's own contact, about or home page text, where US and
Canadian stores write "City, ST 12345". A point comes from geocoding the postal code (or
city), cached on disk, so a rerun costs nothing. Territory conflicts are then distances.
"""

import contextlib
import json
import math
import re
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from ..discover.geo import CA_PROVINCES, US_STATES, normalize_postal, state_code

EARTH_MI = 3958.8
_STATES = "|".join(sorted({*US_STATES, *CA_PROVINCES}))
# "Naples, FL 34102", "Naples FL 34102-1234", "Toronto, ON M5V 2T6"
_ADDRESS_RE = re.compile(
    rf"(?P<street>\d{{1,6}}\s[\w .'#-]{{3,60}}?,\s*)?"
    rf"(?P<city>[A-Z][A-Za-z.' -]{{1,30}}?),?\s+(?P<state>{_STATES})\.?,?\s+"
    rf"(?P<postal>\d{{5}}(?:-\d{{4}})?|[A-Z]\d[A-Z]\s?\d[A-Z]\d)\b"
)
PAGE_ORDER = ("contact", "about", "home", "stockist", "other")
# A street ending caught before the city: "Water Street Eau Claire" is Eau Claire.
_STREET_END_RE = re.compile(
    r"^.*\b(st|street|rd|road|ave|avenue|blvd|boulevard|dr|drive|ln|lane|pkwy|parkway|way|"
    r"hwy|highway|cir|circle|ct|court|pl|place|sq|square|suite|ste|unit|n|s|e|w)\.?\s+",
    re.I,
)
META_KEYS = {
    "address": ("address", "street", "Street Name", "billing_street"),
    "city": ("city", "City", "town"),
    "state": ("state", "State", "province", "prov_state", "region"),
    "postal": ("postal_code", "zip", "Zipcode", "postal_zip", "postcode"),
    "country": ("country", "Country"),
}


@dataclass
class Location:
    address: str = ""
    city: str = ""
    state: str = ""
    postal: str = ""
    country: str = ""
    lat: float | None = None
    lng: float | None = None
    source: str = ""  # input | site_data (its markup) | site (its page text) | ""

    @property
    def known(self) -> bool:
        return bool(self.postal or (self.city and self.state))


def from_meta(meta: dict[str, Any]) -> Location | None:
    def pick(field: str) -> str:
        return next((str(meta[k]).strip() for k in META_KEYS[field] if meta.get(k)), "")

    found = Location(
        address=pick("address"),
        city=pick("city"),
        state=state_code(pick("state")) or pick("state"),
        postal=normalize_postal(pick("postal")),
        country=pick("country"),
        source="input",
    )
    return found if found.known else None


def from_identity(identity: dict[str, Any]) -> Location | None:
    """The address and position a store declares in its own markup (`stores.identity`),
    the first organisation that has one."""
    for org in identity.get("organizations") or []:
        address = org.get("address") or {}
        geo = org.get("geo") or {}
        found = Location(
            address=address.get("streetAddress", ""),
            city=address.get("addressLocality", ""),
            state=state_code(address.get("addressRegion", "")) or address.get("addressRegion", ""),
            postal=normalize_postal(address.get("postalCode", "")),
            country=address.get("addressCountry", ""),
            source="site_data",
        )
        with contextlib.suppress(KeyError, TypeError, ValueError):
            found.lat, found.lng = float(geo["latitude"]), float(geo["longitude"])
        if found.known or found.lat is not None:
            return found
    return None


def from_pages(pages: Iterable[tuple[str, str]]) -> Location | None:
    """The address a store writes most often, contact page first. `pages` holds
    (page_kind, text) pairs."""
    by_kind: dict[str, list[str]] = {}
    for kind, text in pages:
        by_kind.setdefault(kind, []).append(text or "")
    for kind in PAGE_ORDER:
        hits: Counter[tuple[str, str, str, str]] = Counter()
        for text in by_kind.get(kind, []):
            for m in _ADDRESS_RE.finditer(text[:20000]):
                street = (m.group("street") or "").strip(" ,")
                city = _STREET_END_RE.sub("", m.group("city").strip()).strip()
                hits[(street, city, m.group("state"), m.group("postal"))] += 1
        if hits:
            street, city, state, postal = hits.most_common(1)[0][0]
            country = "Canada" if state in CA_PROVINCES else "United States"
            return Location(street, city, state, postal.upper(), country, source="site")
    return None


def miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    a = (
        math.sin(math.radians(lat2 - lat1) / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(math.radians(lng2 - lng1) / 2) ** 2
    )
    return 2 * EARTH_MI * math.asin(min(1.0, math.sqrt(a)))


Point = tuple[float, float]
Lookup = Callable[[str], Point | None]


class Geocoder:
    """Postal code or city to a point, cached in one JSON file. OpenStreetMap Nominatim
    (free, one request a second) unless a Google key is given."""

    def __init__(self, cache_file: Path, google_key: str = "", lookup: Lookup | None = None,
                 contact: str = "https://www.wooden-ships.com"):  # fmt: skip
        self.cache_file = cache_file
        self._cache: dict[str, list[float] | None] = (
            json.loads(cache_file.read_text()) if cache_file.exists() else {}
        )
        self._lookup = lookup or (_google(google_key) if google_key else _nominatim(contact))
        self._lock = threading.Lock()

    def point(self, location: Location) -> Point | None:
        query = ", ".join(
            p for p in (location.postal or location.city, location.state, location.country) if p
        )
        if not query:
            return None
        key = query.lower()
        with self._lock:
            if key not in self._cache:
                found = self._lookup(query)
                self._cache[key] = list(found) if found else None
                self.cache_file.parent.mkdir(parents=True, exist_ok=True)
                self.cache_file.write_text(json.dumps(self._cache))
            cached = self._cache[key]
        return (cached[0], cached[1]) if cached else None


def _nominatim(contact: str) -> Lookup:
    last = [0.0]

    def lookup(query: str) -> Point | None:
        wait = 1.0 - (time.monotonic() - last[0])
        if wait > 0:
            time.sleep(wait)
        last[0] = time.monotonic()
        try:
            answer = requests.get(
                "https://nominatim.openstreetmap.org/search",
                params={"format": "jsonv2", "limit": "1", "countrycodes": "us,ca", "q": query},
                headers={"User-Agent": f"WoodenShipsWholesaleAnalysis/1.0 ({contact})"},
                timeout=15,
            ).json()
        except (requests.RequestException, ValueError):
            return None
        return (float(answer[0]["lat"]), float(answer[0]["lon"])) if answer else None

    return lookup


def _google(key: str) -> Lookup:
    def lookup(query: str) -> Point | None:
        try:
            answer = requests.get(
                "https://maps.googleapis.com/maps/api/geocode/json",
                params={"address": query, "key": key},
                timeout=15,
            ).json()
        except (requests.RequestException, ValueError):
            return None
        results = answer.get("results") or []
        where = results[0]["geometry"]["location"] if results else None
        return (float(where["lat"]), float(where["lng"])) if where else None

    return lookup

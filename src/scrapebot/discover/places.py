"""Google Maps through the official Places API (Text Search, New).

    POST https://places.googleapis.com/v1/places:searchText
    X-Goog-Api-Key: <key>   X-Goog-FieldMask: places.id,places.displayName,...,nextPageToken
    {"textQuery": "sweater boutique in Boulder, CO", "pageSize": 20, "regionCode": "US"}

Each query is searched once per place in `locations`. A page holds up to 20 places and
Google returns at most 60 per search. Best source for physical shops: name, address,
phone and usually the website.

Only the fields needed to find and visit a store are requested (ADR 0008): no ratings,
reviews, coordinates or summaries.
"""

import logging
from typing import Any

from . import geo
from .config import DiscoverConfig
from .merge import Candidate
from .paid import ApiError, PaidApi

log = logging.getLogger(__name__)

FIELDS = (
    "id", "displayName", "formattedAddress", "addressComponents", "websiteUri",
    "nationalPhoneNumber", "businessStatus",
)  # fmt: skip


def _component(place: dict[str, Any], kind: str, short: bool = False) -> str:
    for part in place.get("addressComponents") or []:
        if kind in (part.get("types") or []):
            return part.get("shortText" if short else "longText") or ""
    return ""


def to_candidate(place: dict[str, Any], query: str) -> Candidate | None:
    name = (place.get("displayName") or {}).get("text") or ""
    if not name:
        return None
    street = " ".join(
        p for p in (_component(place, "street_number"), _component(place, "route")) if p
    )
    unit = _component(place, "subpremise")
    address = f"{street} #{unit}" if street and unit else street
    city = (
        _component(place, "locality")
        or _component(place, "postal_town")
        or _component(place, "sublocality")
    )
    return Candidate(
        name=name,
        source="google_places",
        website=place.get("websiteUri") or "",
        address=address or (place.get("formattedAddress") or "").split(",")[0],
        city=city,
        state=_component(place, "administrative_area_level_1", short=True),
        postal_code=geo.normalize_postal(_component(place, "postal_code")),
        country=_component(place, "country", short=True).upper(),
        phone=place.get("nationalPhoneNumber") or "",
        place_id=place.get("id") or "",
        business_status=place.get("businessStatus") or "",
        query=query,
    )


class PlacesSource:
    name = "google_places"

    def __init__(self, config: DiscoverConfig, key: str, api: PaidApi):
        self.config, self.key, self.api = config, key, api
        self.opts = config.google_places
        self.found: list[Candidate] = []
        self.notes: list[str] = []

    def run(self) -> None:
        mask = ",".join(f"places.{f}" for f in FIELDS) + ",nextPageToken"
        headers = {"X-Goog-Api-Key": self.key, "X-Goog-FieldMask": mask}
        url = self.opts.base_url.rstrip("/") + "/v1/places:searchText"
        if not self.config.locations:
            self.notes.append("locations is empty: nothing to search")
            return
        for location in self.config.locations:
            region = geo.region_of(location, self.config.countries[0])
            for query in self.opts.queries:
                text = f"{query} in {location}"
                body: dict[str, Any] = {"textQuery": text, "pageSize": 20, "regionCode": region}
                for _ in range(self.opts.max_pages):
                    try:
                        data = self.api.post(url, body, headers)
                    except ApiError as exc:
                        # A later page refused (an expired token when a discovery resumes
                        # from cache) ends this search only. Anything else stops the
                        # source: Google answers 400 to an invalid key too.
                        if exc.status != 400 or "pageToken" not in body:
                            raise
                        self.notes.append(f"{text}: {exc}")
                        break
                    places = data.get("places") or []
                    self.found += [c for c in (to_candidate(p, text) for p in places) if c]
                    token = data.get("nextPageToken")
                    if not token or not places:
                        break
                    body = {**body, "pageToken": token}
                log.debug("%s: %d places so far", text, len(self.found))

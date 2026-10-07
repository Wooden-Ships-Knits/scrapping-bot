"""US and Canada place names: enough to send a search to the right country and to tell
two sightings of the same shop apart. Region support for other countries is M5."""

import re
import unicodedata

US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
    "PR": "Puerto Rico",
}  # fmt: skip
CA_PROVINCES = {
    "AB": "Alberta", "BC": "British Columbia", "MB": "Manitoba", "NB": "New Brunswick",
    "NL": "Newfoundland and Labrador", "NS": "Nova Scotia", "NT": "Northwest Territories",
    "NU": "Nunavut", "ON": "Ontario", "PE": "Prince Edward Island", "QC": "Quebec",
    "SK": "Saskatchewan", "YT": "Yukon",
}  # fmt: skip
_STATE_BY_NAME = {name.lower(): code for code, name in {**US_STATES, **CA_PROVINCES}.items()}
_STATE_BY_NAME.update({"washington dc": "DC", "d.c.": "DC", "québec": "QC", "pei": "PE"})
COUNTRIES = {
    "united states": "US", "united states of america": "US", "usa": "US", "u.s.a.": "US",
    "u.s.": "US", "canada": "CA", "united kingdom": "GB", "uk": "GB", "australia": "AU",
}  # fmt: skip
_CA_POSTAL = re.compile(r"^[ABCEGHJ-NPRSTVXY]\d[A-Z][ -]?\d[A-Z]\d$", re.I)


def key(value: str | None) -> str:
    """Comparison key: accents, case and punctuation removed."""
    if not value:
        return ""
    text = unicodedata.normalize("NFKD", str(value)).replace("&", " and ")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", text.casefold())


def state_code(value: str | None) -> str:
    """'California', 'ca' or 'CA' -> 'CA'; anything else -> ''."""
    text = str(value or "").strip().rstrip(".").strip()
    if text.upper() in US_STATES or text.upper() in CA_PROVINCES:
        return text.upper()
    return _STATE_BY_NAME.get(text.lower(), "")


def country_of_state(state: str | None) -> str:
    code = state_code(state)
    if code in CA_PROVINCES:
        return "CA"
    return "US" if code in US_STATES else ""


def infer_country(country: str | None, state: str | None, postal: str | None) -> str:
    """The country from whatever is known; '' when it cannot be told."""
    text = str(country or "").strip()
    if text:
        return COUNTRIES.get(text.lower(), text.upper()[:2])
    if _CA_POSTAL.match(str(postal or "").strip()):
        return "CA"
    return country_of_state(state)


def region_of(location: str, default: str) -> str:
    """The country of a configured place: 'Boulder, CO' -> 'US', 'Toronto, ON' -> 'CA'."""
    last = location.rsplit(",", 1)[-1].strip()
    return COUNTRIES.get(last.lower()) or country_of_state(last) or default


def normalize_postal(value: str | None) -> str:
    text = str(value or "").strip().upper()
    if _CA_POSTAL.match(text):
        compact = re.sub(r"[ -]", "", text)
        return f"{compact[:3]} {compact[3:]}"
    return text

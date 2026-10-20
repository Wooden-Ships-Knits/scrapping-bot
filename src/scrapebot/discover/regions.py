"""Regions the interface offers for discovery, and the discovery settings one request
needs: which countries count, which areas the agent searches one by one, and which
cities Google Maps is searched in.

The operator picks a region, the items and how many stores to find; everything else
is derived here, with request and cost caps that grow with the number of stores. In
North America they tick states and provinces instead: the agent then asks about each
one in turn, the ones earlier searches found least in first.
"""

import csv
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from ..extract.focus import ITEMS, OTHER, search_phrase
from .config import DiscoverConfig


@dataclass(frozen=True)
class Region:
    name: str  # in English: it goes into search queries
    countries: tuple[str, ...]
    areas: tuple[str, ...]  # one agent run each, in turn
    cities: tuple[str, ...]  # Google Maps searches "<query> in <city>"


REGIONS: dict[str, Region] = {
    "north_america": Region(
        "the United States and Canada",
        ("US", "CA"),
        (
            "New England, USA", "New York City and the Hudson Valley",
            "the US Mid-Atlantic", "the US Southeast", "the US Midwest",
            "Texas and the US Southwest", "the Rocky Mountain states", "California",
            "the Pacific Northwest", "Ontario and Quebec, Canada", "Western and Atlantic Canada",
        ),
        (
            "New York, NY", "Boston, MA", "Philadelphia, PA", "Washington, DC", "Atlanta, GA",
            "Chicago, IL", "Dallas, TX", "Austin, TX", "Denver, CO", "Los Angeles, CA",
            "San Francisco, CA", "Seattle, WA", "Portland, OR", "Toronto, ON", "Montreal, QC",
            "Vancouver, BC",
        ),
    ),
    "united_states": Region(
        "the United States",
        ("US",),
        (
            "New England, USA", "New York City and the Hudson Valley",
            "the US Mid-Atlantic", "the US Southeast", "the US Midwest",
            "Texas and the US Southwest", "the Rocky Mountain states", "California",
            "the Pacific Northwest",
        ),
        (
            "New York, NY", "Boston, MA", "Philadelphia, PA", "Washington, DC", "Atlanta, GA",
            "Chicago, IL", "Dallas, TX", "Austin, TX", "Denver, CO", "Los Angeles, CA",
            "San Francisco, CA", "Seattle, WA", "Portland, OR",
        ),
    ),
    "canada": Region(
        "Canada",
        ("CA",),
        ("Ontario, Canada", "Quebec, Canada", "British Columbia and Alberta, Canada",
         "Atlantic Canada"),
        ("Toronto, ON", "Ottawa, ON", "Montreal, QC", "Vancouver, BC", "Calgary, AB",
         "Halifax, NS"),
    ),
    "europe": Region(
        "Europe",
        ("GB", "IE", "FR", "BE", "NL", "DE", "AT", "CH", "DK", "SE", "NO", "FI", "IT", "ES",
         "PT"),
        (
            "the United Kingdom and Ireland", "France and Belgium", "the Netherlands",
            "Germany, Austria and Switzerland", "Denmark, Sweden, Norway and Finland",
            "Italy, Spain and Portugal",
        ),
        ("London, UK", "Dublin, Ireland", "Paris, France", "Amsterdam, Netherlands",
         "Berlin, Germany", "Copenhagen, Denmark", "Stockholm, Sweden", "Milan, Italy",
         "Madrid, Spain"),
    ),
    "united_kingdom": Region(
        "the United Kingdom and Ireland",
        ("GB", "IE"),
        ("London", "the South of England", "the North of England", "Scotland",
         "Wales and Northern Ireland", "Ireland"),
        ("London, UK", "Manchester, UK", "Bristol, UK", "Edinburgh, UK", "Dublin, Ireland"),
    ),
    "oceania": Region(
        "Australia and New Zealand",
        ("AU", "NZ"),
        ("Sydney and New South Wales", "Melbourne and Victoria", "Queensland",
         "Western and South Australia", "New Zealand"),
        ("Sydney, Australia", "Melbourne, Australia", "Brisbane, Australia",
         "Auckland, New Zealand"),
    ),
    "asia": Region(
        "East and Southeast Asia",
        ("JP", "KR", "HK", "TW", "SG"),
        ("Japan", "South Korea", "Hong Kong and Taiwan", "Singapore"),
        ("Tokyo, Japan", "Seoul, South Korea", "Hong Kong", "Singapore"),
    ),
}  # fmt: skip
DEFAULT_REGION = "north_america"


@dataclass(frozen=True)
class State:
    name: str
    country: str  # US | CA
    cities: tuple[str, ...]  # where Google Maps and Instagram are searched, main one first


# ISO 3166-2 codes. Cities are where boutiques gather, not always the largest.
STATES: dict[str, State] = {
    "US-AL": State("Alabama", "US", ("Birmingham, AL",)),
    "US-AK": State("Alaska", "US", ("Anchorage, AK",)),
    "US-AZ": State("Arizona", "US", ("Scottsdale, AZ", "Phoenix, AZ")),
    "US-AR": State("Arkansas", "US", ("Little Rock, AR",)),
    "US-CA": State("California", "US", ("Los Angeles, CA", "San Francisco, CA", "San Diego, CA")),
    "US-CO": State("Colorado", "US", ("Denver, CO", "Boulder, CO")),
    "US-CT": State("Connecticut", "US", ("Greenwich, CT", "New Haven, CT")),
    "US-DE": State("Delaware", "US", ("Wilmington, DE",)),
    "US-DC": State("District of Columbia", "US", ("Washington, DC",)),
    "US-FL": State("Florida", "US", ("Miami, FL", "Tampa, FL")),
    "US-GA": State("Georgia", "US", ("Atlanta, GA", "Savannah, GA")),
    "US-HI": State("Hawaii", "US", ("Honolulu, HI",)),
    "US-ID": State("Idaho", "US", ("Boise, ID",)),
    "US-IL": State("Illinois", "US", ("Chicago, IL",)),
    "US-IN": State("Indiana", "US", ("Indianapolis, IN",)),
    "US-IA": State("Iowa", "US", ("Des Moines, IA",)),
    "US-KS": State("Kansas", "US", ("Wichita, KS",)),
    "US-KY": State("Kentucky", "US", ("Louisville, KY", "Lexington, KY")),
    "US-LA": State("Louisiana", "US", ("New Orleans, LA",)),
    "US-ME": State("Maine", "US", ("Portland, ME",)),
    "US-MD": State("Maryland", "US", ("Baltimore, MD", "Annapolis, MD")),
    "US-MA": State("Massachusetts", "US", ("Boston, MA",)),
    "US-MI": State("Michigan", "US", ("Detroit, MI", "Grand Rapids, MI")),
    "US-MN": State("Minnesota", "US", ("Minneapolis, MN",)),
    "US-MS": State("Mississippi", "US", ("Jackson, MS",)),
    "US-MO": State("Missouri", "US", ("St. Louis, MO", "Kansas City, MO")),
    "US-MT": State("Montana", "US", ("Bozeman, MT",)),
    "US-NE": State("Nebraska", "US", ("Omaha, NE",)),
    "US-NV": State("Nevada", "US", ("Las Vegas, NV",)),
    "US-NH": State("New Hampshire", "US", ("Portsmouth, NH",)),
    "US-NJ": State("New Jersey", "US", ("Montclair, NJ", "Princeton, NJ")),
    "US-NM": State("New Mexico", "US", ("Santa Fe, NM",)),
    "US-NY": State("New York", "US", ("New York, NY", "Hudson, NY")),
    "US-NC": State("North Carolina", "US", ("Charlotte, NC", "Asheville, NC")),
    "US-ND": State("North Dakota", "US", ("Fargo, ND",)),
    "US-OH": State("Ohio", "US", ("Columbus, OH", "Cincinnati, OH")),
    "US-OK": State("Oklahoma", "US", ("Oklahoma City, OK",)),
    "US-OR": State("Oregon", "US", ("Portland, OR",)),
    "US-PA": State("Pennsylvania", "US", ("Philadelphia, PA", "Pittsburgh, PA")),
    "US-RI": State("Rhode Island", "US", ("Providence, RI",)),
    "US-SC": State("South Carolina", "US", ("Charleston, SC",)),
    "US-SD": State("South Dakota", "US", ("Sioux Falls, SD",)),
    "US-TN": State("Tennessee", "US", ("Nashville, TN",)),
    "US-TX": State("Texas", "US", ("Dallas, TX", "Austin, TX", "Houston, TX")),
    "US-UT": State("Utah", "US", ("Salt Lake City, UT", "Park City, UT")),
    "US-VT": State("Vermont", "US", ("Burlington, VT",)),
    "US-VA": State("Virginia", "US", ("Richmond, VA", "Alexandria, VA")),
    "US-WA": State("Washington", "US", ("Seattle, WA",)),
    "US-WV": State("West Virginia", "US", ("Charleston, WV",)),
    "US-WI": State("Wisconsin", "US", ("Milwaukee, WI", "Madison, WI")),
    "US-WY": State("Wyoming", "US", ("Jackson, WY",)),
    "CA-AB": State("Alberta", "CA", ("Calgary, AB", "Edmonton, AB")),
    "CA-BC": State("British Columbia", "CA", ("Vancouver, BC", "Victoria, BC")),
    "CA-MB": State("Manitoba", "CA", ("Winnipeg, MB",)),
    "CA-NB": State("New Brunswick", "CA", ("Moncton, NB",)),
    "CA-NL": State("Newfoundland and Labrador", "CA", ("St. John's, NL",)),
    "CA-NS": State("Nova Scotia", "CA", ("Halifax, NS",)),
    "CA-NT": State("Northwest Territories", "CA", ("Yellowknife, NT",)),
    "CA-NU": State("Nunavut", "CA", ("Iqaluit, NU",)),
    "CA-ON": State("Ontario", "CA", ("Toronto, ON", "Ottawa, ON")),
    "CA-PE": State("Prince Edward Island", "CA", ("Charlottetown, PE",)),
    "CA-QC": State("Quebec", "CA", ("Montreal, QC", "Quebec City, QC")),
    "CA-SK": State("Saskatchewan", "CA", ("Saskatoon, SK",)),
    "CA-YT": State("Yukon", "CA", ("Whitehorse, YT",)),
}  # fmt: skip
COUNTRY_NAMES = {"US": "the United States", "CA": "Canada"}
# Regions whose search the operator narrows to states and provinces.
REGION_COUNTRIES: dict[str, tuple[str, ...]] = {
    "north_america": ("US", "CA"),
    "united_states": ("US",),
    "canada": ("CA",),
}


def states_of(region_key: str) -> list[str]:
    countries = REGION_COUNTRIES.get(region_key, ())
    return [code for code, state in STATES.items() if state.country in countries]


def states_region(codes: Sequence[str], found: Mapping[str, int] | None = None) -> Region:
    """The ticked states and provinces as one region. The agent asks about each in turn,
    the ones earlier searches found fewest stores in first (`found`: stores per code), so
    a search spreads over the country instead of asking about the same few places."""
    found = found or {}
    picked = sorted(dict.fromkeys(codes), key=lambda c: found.get(c, 0))  # stable sort
    states = [STATES[c] for c in picked]
    countries = tuple(dict.fromkeys(s.country for s in states))
    if len(states) <= 3:
        name = " and ".join(s.name for s in states)
    else:
        name = " and ".join(COUNTRY_NAMES[c] for c in countries)
    areas = tuple(f"{s.name}, {'USA' if s.country == 'US' else 'Canada'}" for s in states)
    # The main city of every state before any state's second one, so a cap on places
    # still covers them all.
    depth = max(len(s.cities) for s in states)
    cities = tuple(s.cities[i] for i in range(depth) for s in states if i < len(s.cities))
    return Region(name, countries, areas, cities)


def found_per_state(discover_dir: Path) -> Counter[str]:
    """Stores earlier searches found per state or province ("US-TN"), from their lists."""
    counts: Counter[str] = Counter()
    for path in discover_dir.glob("*/stores.csv"):
        try:
            with path.open(encoding="utf-8", newline="") as fh:
                for row in csv.DictReader(fh):
                    code = f"{row.get('country', '')}-{row.get('state', '')}"
                    if code in STATES:
                        counts[code] += 1
        except (OSError, csv.Error, UnicodeDecodeError):
            continue  # an unreadable old list only loses its weight in the order
    return counts


# Caps that scale with the number of stores asked for. An agent run names about 10-12
# stores; measured 2026-10-07: 12 stores and US$0.08 for one gpt-5-search-api run.
# Measured 2026-10-20 on 40 runs: 331 new stores (8.3 a run), US$2.50 (US$0.0625 a run).
# The old cap of 40 runs stopped that search for 500 at 367 stores, with half its budget
# unspent; 200 runs is enough for the most a search may ask for (1,000 new stores).
STORES_PER_AGENT_RUN = 8
MAX_AGENT_RUNS = 200
AGENT_USD_PER_RUN = 0.08
# A search for new stores gets this many times the agent runs: part of every answer is
# stores read before, which do not count.
NEW_ONLY_RUNS = 1.5


def discover_config(
    count: int,
    region_key: str,
    items: list[str],
    terms: list[str],
    agent_model: str,
    base: DiscoverConfig | None = None,
    agent_fallbacks: Sequence[str] = (),
    place: Region | None = None,
    new_only: bool = False,
) -> DiscoverConfig:
    """Discovery settings for 'find `count` stores selling `items` in a region', or in
    `place` when the operator named one that is not in the list. `new_only`: stores read
    before will not count, so the agent may ask more often."""
    region = place or REGIONS[region_key]
    phrase = search_phrase(items, terms)
    runs = math.ceil(count / STORES_PER_AGENT_RUN) + 1
    runs = min(MAX_AGENT_RUNS, math.ceil(runs * NEW_ONLY_RUNS) if new_only else runs)
    store_words = [_store_query(i, terms) for i in items] or ["sweater boutique"]
    store_words = list(dict.fromkeys(w for group in store_words for w in group))
    data = (base or DiscoverConfig()).model_dump()
    data.update(
        countries=list(region.countries),
        locations=list(region.cities),
        items=items,
        terms=terms,
        target_stores=count,
    )
    data["google_places"].update(
        queries=store_words[:3], max_pages=1, max_requests=min(300, max(10, count))
    )
    data["web_search"].update(
        queries=[
            f"independent boutique selling {phrase} online {region.name}",
            f"multi-brand women's boutique {phrase} {region.name}",
        ],
        brand_queries=[],
        max_requests=min(100, max(5, count // 4)),
    )
    data["social_search"].update(
        queries=[f'site:instagram.com boutique {phrase} "{{location}}"'],
        max_locations=min(len(region.cities), max(2, count // 10)),
        max_requests=min(40, max(2, count // 10)),
    )
    data["ai_agent"].update(
        enabled=bool(agent_model),
        model=agent_model,
        fallbacks=list(agent_fallbacks),
        areas=list(region.areas),
        brand_tasks=False,
        max_runs=runs,
        budget_usd=round(runs * AGENT_USD_PER_RUN, 2),
    )
    data["resolve"].update(max_requests=min(300, max(5, count)))
    return DiscoverConfig.model_validate(data)


def _store_query(item: str, terms: list[str]) -> list[str]:
    """What kind of shop Google Maps is asked for, per item."""
    if item == "knitwear":
        return ["sweater boutique", "knitwear store"]
    if item == "cashmere_wool":
        return ["cashmere shop"]
    if item == OTHER:
        return [f"{t} boutique" for t in terms]
    if item in ITEMS:  # a season is not a kind of shop
        return ["women's clothing boutique"]
    return []

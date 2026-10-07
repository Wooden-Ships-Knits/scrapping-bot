"""Regions the interface offers for discovery, and the discovery settings one request
needs: which countries count, which areas the agent searches one by one, and which
cities Google Maps is searched in.

The operator picks a region, the items and how many stores to find; everything else
is derived here, with request and cost caps that grow with the number of stores.
"""

import math
from dataclasses import dataclass

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

# Caps that scale with the number of stores asked for. An agent run names about 10-12
# stores; measured 2026-10-07: 12 stores and US$0.08 for one gpt-5-search-api run.
STORES_PER_AGENT_RUN = 8
MAX_AGENT_RUNS = 40
AGENT_USD_PER_RUN = 0.12


def discover_config(
    count: int,
    region_key: str,
    items: list[str],
    terms: list[str],
    agent_model: str,
    base: DiscoverConfig | None = None,
) -> DiscoverConfig:
    """Discovery settings for 'find `count` stores selling `items` in a region'."""
    region = REGIONS[region_key]
    phrase = search_phrase(items, terms)
    runs = min(MAX_AGENT_RUNS, math.ceil(count / STORES_PER_AGENT_RUN) + 1)
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

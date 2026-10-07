"""Tavily web search: online stores, Instagram and Facebook profiles, and the website of a
store known only by name.

    POST https://api.tavily.com/search      Authorization: Bearer <key>
    {"query": ..., "max_results": 20, "country": "united states"}

Tavily has no paging: one query is one request. A leading `site:domain` in a query is
sent as `include_domains`. Search results are leads: blogs and directories come back
too, and a store's own run shows what it really sells.

Instagram and Facebook are read through search results only. The profiles are never
opened: both forbid automated collection (ADR 0008).
"""

import logging
import re
from typing import Any

from . import geo
from .config import DiscoverConfig
from .merge import Candidate, FoundStore, name_key, origin_of, social_profile, store_website
from .paid import PaidApi

log = logging.getLogger(__name__)

_SITE = re.compile(r"\bsite:(\S+)\s*")
# Tavily takes a country by its lower-case English name: the first full name per code.
_TAVILY_COUNTRY: dict[str, str] = {}
for _name, _code in geo.COUNTRIES.items():
    if len(_name) > 4 and "." not in _name:
        _TAVILY_COUNTRY.setdefault(_code, _name)
_TITLE_SPLIT = re.compile(r"\s+[|\-–—:·•]\s+")
_DOMAIN_IN_TEXT = re.compile(
    r"(?<![\w@/.])(?:https?://)?(?:www\.)?((?:[a-z0-9-]+\.)+"
    r"(?:com|net|co|shop|store|us|ca|org|boutique|clothing|style))(?![\w-])",
    re.I,
)
_PLACE_IN_TEXT = re.compile(r"\b([A-Z][A-Za-z.'’-]+(?: [A-Z][A-Za-z.'’-]+){0,2}),\s*([A-Z]{2})\b")
_PROFILE_TITLE_NOISE = re.compile(
    r"\s*[•·|\-–—]\s*(instagram|facebook|home|about|photos?|videos?|reels?|log ?in|posts?)\b.*$",
    re.I,
)


def tavily_search(
    api: PaidApi, base_url: str, key: str, query: str, country: str = "", max_results: int = 20
) -> list[dict[str, str]]:
    """-> [{"title", "url", "snippet"}]"""
    domains = _SITE.findall(query)
    body: dict[str, Any] = {"query": _SITE.sub("", query).strip(), "max_results": max_results}
    if domains:
        body["include_domains"] = domains
    elif country in _TAVILY_COUNTRY:  # Tavily honours `country` only on unfiltered searches
        body["country"] = _TAVILY_COUNTRY[country]
    data = api.post(base_url.rstrip("/") + "/search", body, {"Authorization": f"Bearer {key}"})
    return [
        {
            "title": r.get("title") or "",
            "url": r.get("url") or "",
            "snippet": r.get("content") or "",
        }
        for r in data.get("results") or []
    ]


def site_name(title: str) -> str:
    """'Sweaters | Cedar & Hyde Mercantile' -> 'Cedar & Hyde Mercantile'."""
    title = re.sub(r"<[^>]+>", "", title).strip()
    parts = [p.strip() for p in _TITLE_SPLIT.split(title) if p.strip()]
    if len(parts) >= 2:
        return parts[-1] if len(parts[-1]) <= 40 else parts[0]
    return title


def profile_name(title: str, handle: str) -> str:
    """'Cedar & Hyde (@cedarandhyde) • Instagram photos and videos' -> 'Cedar & Hyde'."""
    text = re.sub(r"<[^>]+>", "", title).strip()
    text = re.split(r"\s*\(@", text)[0]
    text = _PROFILE_TITLE_NOISE.sub("", text)
    text = re.split(r"\s+\|\s+", text)[0].strip(" -–—|•·")
    if not text or text.startswith("@") or text.lower() in ("instagram", "facebook"):
        return handle
    return text


def website_in(text: str) -> str:
    """The store's own domain if a profile bio shows one."""
    for match in _DOMAIN_IN_TEXT.finditer(text):
        if store_website(match.group(1)):
            return origin_of(match.group(1).lower())
    return ""


def place_in(text: str) -> tuple[str, str]:
    for match in _PLACE_IN_TEXT.finditer(text):
        code = geo.state_code(match.group(2))
        if code:
            return match.group(1), code
    return "", ""


class WebSearchSource:
    name = "web_search"

    def __init__(self, config: DiscoverConfig, key: str, api: PaidApi):
        self.config, self.key, self.api = config, key, api
        self.opts = config.web_search
        self.found: list[Candidate] = []
        self.notes: list[str] = []

    def queries(self) -> list[str]:
        queries = list(self.opts.queries)
        for template in self.opts.brand_queries:
            queries += [template.replace("{brand}", brand) for brand in self.config.brands]
        return queries

    def run(self) -> None:
        seen: set[str] = set()
        exclude = frozenset(self.config.exclude_domains)
        # Many countries (a continent): search once, the region is in the query itself.
        countries = self.config.countries if len(self.config.countries) <= 2 else [""]
        for country in countries:
            for query in self.queries():
                for item in tavily_search(self.api, self.opts.base_url, self.key, query, country):
                    site = store_website(item["url"], exclude)
                    if not site or site in seen:
                        continue
                    seen.add(site)
                    self.found.append(
                        Candidate(
                            name=site_name(item["title"]) or site,
                            source=self.name,
                            website=origin_of(item["url"]),
                            note=item["snippet"],
                            query=query,
                        )
                    )


class SocialSearchSource:
    name = "social_search"

    def __init__(self, config: DiscoverConfig, key: str, api: PaidApi):
        self.config, self.key, self.api = config, key, api
        self.opts = config.social_search
        self.found: list[Candidate] = []
        self.notes: list[str] = []

    def queries(self) -> list[tuple[str, str]]:
        """(query, country) pairs; a query with {location} runs once per place."""
        places = self.config.locations[: self.opts.max_locations]
        out: list[tuple[str, str]] = []
        for template in self.opts.queries:
            if "{location}" in template:
                for place in places:
                    country = geo.region_of(place, self.config.countries[0])
                    out.append((template.replace("{location}", place), country))
            else:
                out += [(template, country) for country in self.config.countries]
        return out

    def run(self) -> None:
        seen: set[tuple[str, str]] = set()
        base = self.config.web_search.base_url
        for query, country in self.queries():
            for item in tavily_search(self.api, base, self.key, query, country):
                profile = social_profile(item["url"])
                if not profile or profile[:2] in seen:
                    continue
                seen.add(profile[:2])
                network, handle, link = profile
                city, state = place_in(f"{item['title']} {item['snippet']}")
                self.found.append(
                    Candidate(
                        name=profile_name(item["title"], handle),
                        source=self.name,
                        website=website_in(item["snippet"]),
                        instagram=link if network == "instagram" else "",
                        facebook=link if network == "facebook" else "",
                        city=city,
                        state=state,
                        note=item["snippet"],
                        query=query,
                    )
                )


def looks_like(store: FoundStore, url: str, title: str) -> bool:
    """Does this search result belong to the store? Its domain or title has to carry
    the store's name or social handle."""
    site = store_website(url)
    if not site:
        return False
    domain = geo.key(site.split(".")[0])
    names = {name_key(store.name)}
    for value in (store.instagram, store.facebook):
        profile = social_profile(value)
        if profile and not profile[1].startswith("id:"):
            names.add(geo.key(profile[1]))
    title_key = geo.key(_TITLE_SPLIT.split(title)[0]) + "|" + geo.key(title)
    return any(
        len(name) >= 4
        and (name in domain or (len(domain) >= 5 and domain in name) or name in title_key)
        for name in names
    )


class WebsiteLookup:
    """Finds the website of a store known only by name, place or profile: one search
    each ('"Cedar & Hyde" Boulder CO official website')."""

    def __init__(self, config: DiscoverConfig, key: str, api: PaidApi):
        self.config, self.key, self.api = config, key, api
        self.exclude = frozenset(config.exclude_domains)

    def find(self, store: FoundStore) -> str:
        loc = store.primary
        place = " ".join(p for p in (loc.city, loc.state) if p)
        query = " ".join(f'"{store.name}" {place} official website'.split())
        country = loc.country if loc.country in self.config.countries else self.config.countries[0]
        base = self.config.web_search.base_url
        for item in tavily_search(self.api, base, self.key, query, country, max_results=10):
            if store_website(item["url"], self.exclude) and looks_like(
                store, item["url"], item["title"]
            ):
                return origin_of(item["url"])
        return ""

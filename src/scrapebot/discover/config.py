"""Settings for one discovery: what to search for, where, and how much to spend.

Read from YAML (see `discover.example.yaml`); unknown keys are rejected. Every paid
source has a hard request cap, and the LLM agent a cost cap. API keys never belong
here: they come from `.env` or the environment (standards, section 4).
"""

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlacesConfig(_Section):
    """Google Maps through the official Places API (Text Search, New)."""

    enabled: bool = True
    # Each query is searched once per place in `locations`: "<query> in <location>".
    queries: list[str] = Field(
        default_factory=lambda: ["sweater boutique", "knitwear store", "cashmere sweater shop"]
    )
    max_pages: int = Field(default=2, ge=1, le=3)  # 20 places a page; Google stops at 60
    max_requests: int = Field(default=200, ge=0)
    base_url: str = "https://places.googleapis.com"


class WebSearchConfig(_Section):
    """Tavily web search: online stores, and retailers of brands with no stockist list."""

    enabled: bool = True
    queries: list[str] = Field(default_factory=list)  # each run once per country
    # Run once per name in `brands`; {brand} is replaced by the name.
    brand_queries: list[str] = Field(default_factory=lambda: ['"{brand}" sweaters boutique'])
    max_requests: int = Field(default=150, ge=0)
    base_url: str = "https://api.tavily.com"


class SocialSearchConfig(_Section):
    """Instagram and Facebook profiles, found through Tavily. The profiles themselves are
    never opened (ADR 0002, ADR 0008)."""

    enabled: bool = True
    # A query with {location} is run once per place, up to `max_locations` places.
    queries: list[str] = Field(default_factory=list)
    max_locations: int = Field(default=20, ge=0)
    max_requests: int = Field(default=60, ge=0)


class AgentConfig(_Section):
    """An LLM that searches the web itself, through LiteLLM (ADR 0004)."""

    enabled: bool = True
    model: str = ""  # provider/model with web search, e.g. gemini/gemini-2.5-flash; "" = skipped
    areas: list[str] = Field(default_factory=list)  # one agent run per area
    brand_tasks: bool = False  # also one run per brand: "who stocks X?"
    max_runs: int = Field(default=11, ge=0)
    max_tokens: int = Field(default=8000, ge=256)
    budget_usd: float = Field(default=2.0, ge=0)  # agent calls stop once this is spent

    @field_validator("model")
    @classmethod
    def _provider_prefix(cls, model: str) -> str:
        model = model.strip()
        if model and "/" not in model:
            raise ValueError("write the model as provider/model, e.g. gemini/gemini-2.5-flash")
        return model


class ResolveConfig(_Section):
    """One web search per store known only by name or profile, to find its website."""

    enabled: bool = True
    max_requests: int = Field(default=300, ge=0)


class DiscoverConfig(_Section):
    countries: list[str] = Field(default_factory=lambda: ["US", "CA"])  # others are dropped
    # What the stores should sell (`extract.focus`): the agent is asked for these.
    items: list[str] = Field(default_factory=lambda: ["knitwear"])
    terms: list[str] = Field(default_factory=list)  # the operator's own words, item "other"
    # Stop asking the agent once this many stores are found; None = run every area once.
    target_stores: int | None = Field(default=None, ge=1, le=1000)
    locations: list[str] = Field(default_factory=list)  # "City, ST" places to search in
    brands: list[str] = Field(default_factory=list)  # search seeds: retailers of these brands
    exclude_domains: list[str] = Field(default_factory=list)  # never stores: media, own site
    google_places: PlacesConfig = Field(default_factory=PlacesConfig)
    web_search: WebSearchConfig = Field(default_factory=WebSearchConfig)
    social_search: SocialSearchConfig = Field(default_factory=SocialSearchConfig)
    ai_agent: AgentConfig = Field(default_factory=AgentConfig)
    resolve: ResolveConfig = Field(default_factory=ResolveConfig)
    out_dir: Path = Path("data/discover")
    # Paid answers are kept here, so repeating a discovery costs nothing.
    cache_dir: Path = Path("data/.cache/discover")

    @field_validator("countries")
    @classmethod
    def _country_codes(cls, codes: list[str]) -> list[str]:
        codes = [c.strip().upper() for c in codes if c.strip()]
        if not codes or any(len(c) != 2 for c in codes):
            raise ValueError("write countries as ISO 3166 two-letter codes, e.g. [US, CA]")
        return codes


def load_discover_config(path: str | Path) -> DiscoverConfig:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return DiscoverConfig.model_validate(data)

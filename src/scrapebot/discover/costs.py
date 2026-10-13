"""What a discovery costs: an estimate before it starts, and what its requests came to.

The search APIs bill per request and do not say what a request cost, so their figures
are the list price times the requests sent. The agent's figure comes from LiteLLM's
price table. Both are estimates: free monthly allowances, a free tier and plan
discounts are not subtracted, so the real bill is this or less.
"""

from collections.abc import Mapping

from pydantic import BaseModel, SecretStr

from ..llm.gateway import is_local, key_for
from .config import DiscoverConfig

# List prices in US$ per request, checked 2026-10-13.
USD_PER_REQUEST = {
    "google_places": 0.035,  # Places API (New), Text Search Enterprise: $35 per 1,000
    "web_search": 0.008,  # Tavily: one credit per basic search
    "social_search": 0.008,
    "resolve": 0.008,
}
# Which key each paid step needs, by the names `keys.load_keys` gives them.
STEP_KEYS = {
    "google_places": "google_places",
    "web_search": "tavily",
    "social_search": "tavily",
    "resolve": "tavily",
}
FREE_TIER_NOTE = "nothing while Gemini's free tier lasts"


def request_cost(step: str, requests: int) -> float:
    """What `requests` paid requests of a search step come to, at list price."""
    return round(requests * USD_PER_REQUEST.get(step, 0.0), 6)


class CostLine(BaseModel):
    name: str  # google_places | web_search | social_search | ai_agent | resolve | llm
    max_usd: float  # the most this step can come to
    note: str = ""


def estimate(config: DiscoverConfig, keys: Mapping[str, SecretStr]) -> list[CostLine]:
    """The most each paid step of this discovery can come to: its request cap at list
    price, the agent's cost cap. Steps without a key cost nothing and are left out."""
    lines = []
    for step, key in STEP_KEYS.items():
        opts = getattr(config, step)
        if opts.enabled and key in keys:
            lines.append(CostLine(name=step, max_usd=request_cost(step, opts.max_requests)))
    agent = config.ai_agent
    models = [m for m in (agent.model, *agent.fallbacks) if m and (is_local(m) or key_for(m, keys))]
    if agent.enabled and models:
        free_first = models[0].startswith("gemini/")
        lines.append(
            CostLine(
                name="ai_agent",
                max_usd=round(agent.budget_usd, 6),
                note=FREE_TIER_NOTE if free_first else "",
            )
        )
    order = ("google_places", "web_search", "social_search", "ai_agent", "resolve")
    return sorted(lines, key=lambda line: order.index(line.name))

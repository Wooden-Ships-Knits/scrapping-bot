"""An LLM that searches the web and names the stores it finds.

One run per area in `ai_agent.areas`, plus, with `brand_tasks`, one per brand. The
model goes through LiteLLM (ADR 0004) with `web_search_options`, which LiteLLM maps to
each provider's own search tool (Google Search for Gemini, the web search tool for
Claude). It is good at what the other sources cannot do: reading "best boutiques
in ..." articles and pulling the store names out.

Its answers are leads, not facts: a store it names is only kept with a website,
profile or town, and the run on that website shows what it really sells. Answers are
cached on disk, so repeating a discovery costs nothing; spending stops at
`budget_usd`.
"""

import hashlib
import json
import logging
import re
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError

from ..llm.gateway import (
    Budget,
    cost_of,
    explain_error,
    is_local,
    is_transient,
    key_for,
    usage_of,
)
from ..models import LLMCall
from . import geo
from .config import DiscoverConfig
from .merge import Candidate
from .paid import ApiError, read_cached, write_cached

log = logging.getLogger(__name__)

PROMPT_VERSION = "discover-v1"
PROMPT = """Find retail stores that sell women's sweaters and knitwear.

Task: {task}

What counts: independent boutiques, multi-brand clothing stores, and online stores that \
sell sweaters, cardigans or other knitwear to consumers, located in or shipping from: \
{countries}.
What does not count: marketplaces (Amazon, Etsy, eBay), department-store chains, yarn or \
knitting-supply shops, wholesalers, and brands' own sites that have no shop.

Search the web several times with different wording, including searches of Instagram and \
Facebook, where many small boutiques only have a profile. Read the results and collect as \
many real stores as you can find (aim for 20 or more). Only report a store you actually \
saw in a search result: do not invent names, websites or profile links. If you are not \
sure of a store's website, leave it empty.

Answer with ONLY a JSON array, no other text. Each element is an object with the keys \
name, website, instagram, facebook, city, state (two-letter code), country (two-letter \
code) and note (one short line: what it sells and where you saw it). Use an empty string \
for anything unknown."""

Completion = Callable[..., Any]


class AgentStore(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    website: str = ""
    instagram: str = ""
    facebook: str = ""
    city: str = ""
    state: str = ""
    country: str = ""
    note: str = ""


def _store_items(value: Any) -> list[Any] | None:
    """The list in a parsed JSON value that can be a store list: one holding objects."""
    items = value.get("stores") if isinstance(value, dict) else value
    if isinstance(items, list) and any(isinstance(item, dict) for item in items):
        return items
    return None


def _salvage(text: str, decoder: json.JSONDecoder) -> list[Any]:
    """The complete objects of an array cut off mid-way (the answer ran out of tokens)."""
    start = re.search(r"\[\s*\{", text)
    if not start:
        return []
    items, pos = [], start.start() + 1
    while True:
        while pos < len(text) and text[pos] in " \t\r\n,":
            pos += 1
        try:
            item, pos = decoder.raw_decode(text, pos)
        except ValueError:
            return items
        if not isinstance(item, dict):
            return items
        items.append(item)


def _to_stores(items: list[Any]) -> list[AgentStore]:
    stores = []
    for item in items:
        if not isinstance(item, dict):
            continue
        cleaned = {k: str(v).strip() for k, v in item.items() if v is not None}
        try:
            stores.append(AgentStore.model_validate(cleaned))
        except ValidationError:
            continue
    return [s for s in stores if s.name]


def stores_in_text(text: str) -> list[AgentStore] | None:
    """The store list in a model's answer: the first JSON array of objects (or an object
    with a `stores` array), else the complete objects of a cut-off array. [] when the
    answer is an empty list; None when it holds no list at all."""
    text = re.sub(r"```(?:json)?", "", text)
    decoder = json.JSONDecoder()
    empty = False
    for match in re.finditer(r"[\[{]", text):
        try:
            value, _ = decoder.raw_decode(text, match.start())
        except ValueError:
            continue
        items = _store_items(value)
        if items is not None:
            return _to_stores(items)
        empty = empty or value == [] or value == {"stores": []}
    salvaged = _salvage(text, decoder)
    if salvaged:
        return _to_stores(salvaged)
    return [] if empty else None


class AgentSource:
    name = "ai_agent"

    def __init__(
        self,
        config: DiscoverConfig,
        keys: Mapping[str, SecretStr],
        cache_dir: Path,
        completion: Completion | None = None,
    ):
        self.config = config
        self.opts = config.ai_agent
        self.model = self.opts.model
        self.key = key_for(self.model, keys)
        self.cache_dir = Path(cache_dir) / self.name
        self.budget = Budget(self.opts.budget_usd)
        self._completion = completion
        self.found: list[Candidate] = []
        self.notes: list[str] = []
        self.calls: list[LLMCall] = []
        self.sent = 0
        self.cached = 0

    @property
    def needs_key(self) -> bool:
        return not is_local(self.model)

    def tasks(self) -> list[str]:
        tasks = [f"Stores in {area}." for area in self.opts.areas]
        if self.opts.brand_tasks:
            tasks += [
                f'Stores that stock the knitwear brand "{brand}" (its stockists and retailers).'
                for brand in self.config.brands
            ]
        return tasks[: self.opts.max_runs]

    def run(self) -> None:
        tasks = self.tasks()
        if not tasks:
            self.notes.append("ai_agent.areas is empty and brand_tasks is off: nothing to do")
        countries = " / ".join(self.config.countries)
        for task in tasks:
            stores = self._ask(PROMPT.format(task=task, countries=countries))
            if stores is None:
                self.notes.append(f"no store list for: {task}")
                continue
            log.info("ai_agent: %d stores for %r", len(stores), task)
            self.found += [
                Candidate(
                    name=s.name,
                    source=self.name,
                    website=s.website,
                    instagram=s.instagram,
                    facebook=s.facebook,
                    city=s.city,
                    state=geo.state_code(s.state) or s.state,
                    country=geo.infer_country(s.country, s.state, ""),
                    note=s.note,
                    query=task,
                )
                for s in stores
            ]

    def _ask(self, prompt: str) -> list[AgentStore] | None:
        digest = hashlib.sha256(f"{self.model}\n{PROMPT_VERSION}\n{prompt}".encode()).hexdigest()
        cache_file = self.cache_dir / f"{digest[:32]}.json"
        cached = read_cached(cache_file)
        if isinstance(cached, list):
            self.cached += 1
            return _to_stores(cached)
        if self.budget.exhausted():
            self.calls.append(
                LLMCall(model=self.model, prompt_version=PROMPT_VERSION, status="skipped_budget")
            )
            return None
        text = self._call(prompt)
        if text is None:
            return None
        stores = stores_in_text(text)
        if stores:  # an empty or unreadable answer is asked again next time
            write_cached(cache_file, [s.model_dump() for s in stores])
        return stores

    def _call(self, prompt: str) -> str | None:
        import litellm

        litellm.suppress_debug_info = True
        complete: Completion = self._completion or litellm.completion
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": self.opts.max_tokens,
            "web_search_options": {"search_context_size": "medium"},
        }
        if self.key:
            kwargs["api_key"] = self.key
        started = time.monotonic()
        self.sent += 1
        try:
            completion: Any = complete(**kwargs)
        except Exception as exc:
            message = explain_error(exc)
            self.calls.append(
                LLMCall(
                    model=self.model,
                    prompt_version=PROMPT_VERSION,
                    status="error",
                    duration_seconds=round(time.monotonic() - started, 2),
                    error=message,
                )
            )
            if not is_transient(exc):
                raise ApiError(f"ai_agent: {message}") from None
            self.notes.append(message)
            return None
        tokens_in, tokens_out = usage_of(completion)
        cost, estimated = cost_of(completion, self.model, tokens_in, tokens_out)
        self.budget.add(cost)
        self.calls.append(
            LLMCall(
                model=self.model,
                prompt_version=PROMPT_VERSION,
                status="ok",
                input_tokens=tokens_in,
                output_tokens=tokens_out,
                cost_usd=round(cost, 6),
                cost_estimated=estimated,
                duration_seconds=round(time.monotonic() - started, 2),
            )
        )
        try:
            return completion.choices[0].message.content or ""
        except (AttributeError, IndexError):
            return ""

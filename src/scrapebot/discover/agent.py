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

When the model fails, the next one in `ai_agent.fallbacks` takes over for the rest of
the search, and a note says so. Only models whose key is set are used.
"""

import hashlib
import json
import logging
import re
import time
from collections.abc import Callable, Collection, Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError

from ..extract.focus import search_phrase
from ..llm.gateway import (
    Budget,
    cost_of,
    explain_error,
    is_local,
    is_rate_limit,
    is_transient,
    key_for,
    rate_limit_wait,
    usage_of,
)
from ..models import LLMCall
from . import geo
from .config import DiscoverConfig
from .merge import Candidate, name_key, store_website
from .paid import ApiError, read_cached, write_cached

log = logging.getLogger(__name__)

PROMPT_VERSION = "discover-v2"
PROMPT = """Find retail stores that sell {items}.

Task: {task}

What counts: independent boutiques, multi-brand clothing stores, and online stores that \
sell {items} to consumers, located in or shipping from: {countries}.
What does not count: marketplaces (Amazon, Etsy, eBay), department-store chains, yarn or \
knitting-supply shops, wholesalers, and brands' own sites that have no shop.
{exclude}{known}
Search the web several times with different wording, including searches of Instagram and \
Facebook, where many small boutiques only have a profile. Read the results and collect as \
many real stores as you can find (aim for 20 or more). Only report a store you actually \
saw in a search result: do not invent names, websites or profile links. If you are not \
sure of a store's website, leave it empty.

Answer with ONLY a JSON array, no other text. Each element is an object with the keys \
name, website, instagram, facebook, city, state (two-letter code), country (two-letter \
code) and note (one short line: what it sells and where you saw it). Use an empty string \
for anything unknown."""
# Names of stores already found, sent so the next run looks for new ones.
MAX_EXCLUDED_NAMES = 80
# Websites of stores read before, sent so the model spends its answer on new ones.
MAX_KNOWN_WEBSITES = 150

Completion = Callable[..., Any]

# Models with web search, in the order the interface uses them: the first whose key is
# set answers, the next takes over when it fails. Gemini first: its free tier costs
# nothing. Verified 2026-10-07: openai/gpt-5-search-api (the -search-preview models are
# deprecated).
AGENT_MODELS = (
    ("gemini", "gemini/gemini-2.5-flash"),
    ("openai", "openai/gpt-5-search-api"),
)
# A failure that may pass is tried once more after this wait, then the next model is used.
RETRY_DELAY_SECONDS = 3.0
# A rate limit is waited out, as long as the provider says, this many times per task:
# search models have small per-minute token limits, and a search asks several times a
# minute. Measured 2026-10-13: 45,000 tokens a minute, about two asks.
RATE_LIMIT_WAITS = 2
# With no model left to take over, the agent stops after this many failed tasks in a row.
MAX_FAILED_TASKS = 2
# Gemini counts its thinking against max_tokens and, unless told otherwise, thinks as
# long as it likes: the store list then comes back cut off or empty. "low" is 1,024
# thinking tokens in LiteLLM.
GEMINI_REASONING_EFFORT = "low"


def agent_models(keys: Mapping[str, SecretStr]) -> list[str]:
    """The agent models whose provider has a key, in the order they are tried."""
    return [model for provider, model in AGENT_MODELS if provider in keys]


def pick_agent_model(keys: Mapping[str, SecretStr]) -> str:
    """The first agent model whose provider has a key; "" when none has."""
    return next(iter(agent_models(keys)), "")


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
        sleep: Callable[[float], None] = time.sleep,
        known: Collection[str] = (),
    ):
        self.config = config
        # Domains of stores read before, newest first. They do not count toward the
        # target, and the model is asked for others.
        self.known = list(dict.fromkeys(known))
        self._known = set(self.known)
        self.opts = config.ai_agent
        self.keys = keys
        # The models that can answer, in order. One without its key is passed over.
        self.models = [
            m
            for m in dict.fromkeys([self.opts.model, *self.opts.fallbacks])
            if m and (is_local(m) or key_for(m, keys))
        ]
        self.model = self.models[0] if self.models else self.opts.model  # the one in use
        self.cache_dir = Path(cache_dir) / self.name
        self.budget = Budget(self.opts.budget_usd)
        self._completion = completion
        self._sleep = sleep
        self._failed_tasks = 0
        self.found: list[Candidate] = []
        self.notes: list[str] = []
        self.calls: list[LLMCall] = []
        self.sent = 0
        self.cached = 0

    @property
    def key(self) -> str | None:
        return key_for(self.model, self.keys)

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
        return tasks

    def stores_found(self) -> int:
        """Distinct stores with a website so far, without those read before: what a
        target counts."""
        return len(
            {
                name_key(c.name)
                for c in self.found
                if c.website and store_website(c.website) not in self._known
            }
        )

    def _prompt(self, task: str) -> str:
        names = list(dict.fromkeys(c.name for c in self.found))[-MAX_EXCLUDED_NAMES:]
        exclude = (
            "These stores are already known; find others: " + "; ".join(names) + "\n"
            if names
            else ""
        )
        known = (
            "These websites are already known; do not report their stores: "
            + "; ".join(self.known[:MAX_KNOWN_WEBSITES])
            + "\n"
            if self.known
            else ""
        )
        return PROMPT.format(
            items=search_phrase(self.config.items, self.config.terms),
            task=task,
            countries=" / ".join(self.config.countries),
            exclude=exclude,
            known=known,
        )

    def run(self, progress: Callable[[int], None] | None = None) -> None:
        """Each task once; with `target_stores`, the tasks again in turn (asking for
        stores not yet named) until the target, `max_runs`, the budget, or a full round
        that finds nothing new."""
        tasks = self.tasks()
        if not tasks:
            self.notes.append("ai_agent.areas is empty and brand_tasks is off: nothing to do")
            return
        target = self.config.target_stores
        runs = 0
        while True:
            before = self.stores_found()
            for task in tasks:
                if runs >= self.opts.max_runs or (target and self.stores_found() >= target):
                    return
                runs += 1
                stores = self._ask(self._prompt(task))
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
                if progress:
                    progress(self.stores_found())
                if self.budget.exhausted():
                    self.notes.append("budget reached")
                    return
            if not target or self.stores_found() == before:
                return

    def _cache_file(self, model: str, prompt: str) -> Path:
        digest = hashlib.sha256(f"{model}\n{PROMPT_VERSION}\n{prompt}".encode()).hexdigest()
        return self.cache_dir / f"{digest[:32]}.json"

    def _ask(self, prompt: str) -> list[AgentStore] | None:
        # An answer any of the models gave before is free, whichever is in use now.
        for model in self.models or [self.model]:
            cached = read_cached(self._cache_file(model, prompt))
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
            write_cached(self._cache_file(self.model, prompt), [s.model_dump() for s in stores])
        return stores

    def _note(self, note: str) -> None:
        if note not in self.notes:
            self.notes.append(note)

    def _next_model(self, message: str) -> bool:
        """Hand the rest of the search to the next model; False when none is left."""
        later = self.models[self.models.index(self.model) + 1 :] if self.models else []
        if not later:
            return False
        self._note(f"{self.model}: {message} Continued with {later[0]}.")
        log.warning("ai_agent: %s failed, continuing with %s", self.model, later[0])
        self.model = later[0]
        return True

    def _call(self, prompt: str) -> str | None:
        """The answer of the model in use. A rate limit is waited out as long as the
        provider asks; another failure that may pass is tried once more. After that, or
        at once when it cannot pass, the next model takes over. With none left the task
        is skipped, and the agent stops when that keeps happening."""
        retried, waits = False, 0
        while True:
            started = time.monotonic()
            try:
                text = self._complete(prompt)
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
                passing = is_transient(exc)
                if is_rate_limit(exc):
                    wait = rate_limit_wait(exc)
                    if wait is not None and waits < RATE_LIMIT_WAITS:
                        waits += 1
                        self._note(f"{self.model}: rate limit reached; waited and asked again.")
                        log.info("ai_agent: rate limit, waiting %.0f s", wait)
                        self._sleep(wait)
                        continue
                elif passing and not retried:
                    retried = True
                    self._sleep(RETRY_DELAY_SECONDS)
                    continue
                if self._next_model(message):
                    retried, waits = False, 0
                    continue
                self._failed_tasks += 1
                if not passing or self._failed_tasks >= MAX_FAILED_TASKS:
                    raise ApiError(f"ai_agent: {message}") from None
                self._note(message)
                return None
            self._failed_tasks = 0
            return text

    def _complete(self, prompt: str) -> str:
        import litellm

        litellm.suppress_debug_info = True
        complete: Completion = self._completion or litellm.completion
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": self.opts.max_tokens,
            "web_search_options": {"search_context_size": "medium"},
        }
        if self.model.startswith("gemini/"):
            kwargs["reasoning_effort"] = GEMINI_REASONING_EFFORT
        if self.key:
            kwargs["api_key"] = self.key
        started = time.monotonic()
        self.sent += 1
        completion: Any = complete(**kwargs)
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
            choice = completion.choices[0]
            text = choice.message.content or ""
        except (AttributeError, IndexError):
            return ""
        if getattr(choice, "finish_reason", "") == "length":
            self._note(
                f"{self.model}: an answer was cut off at max_tokens "
                f"({self.opts.max_tokens}); only the complete stores in it are kept."
            )
        return text

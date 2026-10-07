"""One discovery: every source, merged, websites looked up, written as a links file.

    data/discover/<discovery_id>/
      stores.csv     one row per store; `scrapebot run` reads it as its input
      stores.json    the same stores with every location, query and note
      report.json    per source: status, stores found, paid and cached requests, cost

A source without its key is skipped and the others still run (PRD section 9).
"""

import csv
import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, Field, SecretStr

from .. import __version__
from .agent import AgentSource, Completion
from .config import DiscoverConfig
from .merge import EXPORT_COLUMNS, Candidate, FoundStore, export_row, fold_by_website, merge
from .paid import ApiError, BudgetReached, PaidApi, Transport
from .places import PlacesSource
from .search import SocialSearchSource, WebSearchSource, WebsiteLookup

log = logging.getLogger(__name__)

SOURCE_NAMES = ("google_places", "web_search", "social_search", "ai_agent")
STEP_NAMES = (*SOURCE_NAMES, "resolve")  # what `--only` accepts
# Which key each source needs, by the names `keys.load_keys` gives them.
SOURCE_KEYS = {"google_places": "google_places", "web_search": "tavily", "social_search": "tavily"}


class SourceReport(BaseModel):
    name: str
    status: str = "ok"  # ok | disabled | no_api_key | budget_reached | error
    candidates: int = 0
    requests_sent: int = 0
    requests_cached: int = 0
    cost_usd: float = 0.0  # the agent only; search APIs bill per request, see their pricing
    error: str = ""
    notes: list[str] = Field(default_factory=list)


@dataclass
class DiscoverResult:
    discovery_id: str
    root: Path
    stores_csv: Path
    report_path: Path
    stores: list[FoundStore]
    sources: list[SourceReport]
    websites_looked_up: int

    @property
    def with_website(self) -> int:
        return sum(bool(s.website) for s in self.stores)


class _Source(Protocol):
    name: str
    found: list[Candidate]
    notes: list[str]

    def run(self) -> None: ...


def _secret(keys: Mapping[str, SecretStr], name: str) -> str:
    value = keys.get(name)
    return value.get_secret_value() if value else ""


# (step name, how many stores or sightings so far): for a live progress display.
Progress = Callable[[str, int], None]


def _run_source(
    source: _Source, report: SourceReport, run: Callable[[], None] | None = None
) -> list[Candidate]:
    try:
        (run or source.run)()
    except BudgetReached as exc:
        report.status = "budget_reached"
        log.warning("%s", exc)
    except ApiError as exc:
        report.status, report.error = "error", str(exc)
        log.error("%s stopped: %s", source.name, exc)
    report.candidates = len(source.found)
    report.notes = source.notes
    return source.found


def _run_agent(
    config: DiscoverConfig,
    keys: Mapping[str, SecretStr],
    completion: Completion | None,
    report: SourceReport,
    progress: Progress | None,
    found_before: int,
) -> list[Candidate]:
    agent = AgentSource(config, keys, config.cache_dir, completion=completion)
    if not agent.model:
        report.status = "disabled"
        report.notes = ["ai_agent.model is empty"]
        return []
    if agent.needs_key and not agent.key:
        report.status = "no_api_key"
        return []

    def on_agent(n: int) -> None:
        if progress:
            progress("ai_agent", found_before + n)

    found = _run_source(agent, report, lambda: agent.run(on_agent))
    report.requests_sent, report.requests_cached = agent.sent, agent.cached
    report.cost_usd = round(sum(c.cost_usd for c in agent.calls), 6)
    return found


def _lookup_websites(
    config: DiscoverConfig, stores: list[FoundStore], key: str, api: PaidApi
) -> tuple[int, str]:
    """Find a website for stores known only by name, place or profile. -> (found, error)."""
    lookup = WebsiteLookup(config, key, api)
    found = 0
    for store in stores:
        if store.website:
            continue
        try:
            website = lookup.find(store)
        except BudgetReached:
            return found, "request cap reached; the rest are looked up on the next discovery"
        except ApiError as exc:
            return found, str(exc)
        if website:
            store.website, store.website_source = website, "lookup"
            found += 1
    return found, ""


def _write_csv(stores: list[FoundStore], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=EXPORT_COLUMNS)
        writer.writeheader()
        for store in stores:
            writer.writerow(export_row(store))


def run_discover(
    config: DiscoverConfig,
    keys: Mapping[str, SecretStr],
    only: list[str] | None = None,
    transport: Transport | None = None,
    completion: Completion | None = None,
    progress: Progress | None = None,
) -> DiscoverResult:
    started = datetime.now(UTC)
    discovery_id = started.strftime("%Y%m%dT%H%M%SZ")
    root = config.out_dir / discovery_id
    root.mkdir(parents=True, exist_ok=True)

    def paid(name: str, max_requests: int) -> PaidApi:
        return PaidApi(name, config.cache_dir, max_requests, transport=transport)

    candidates: list[Candidate] = []
    reports: list[SourceReport] = []
    for name in SOURCE_NAMES:
        report = SourceReport(name=name)
        reports.append(report)
        if (only and name not in only) or not getattr(config, name).enabled:
            report.status = "disabled"
            continue
        if name == "ai_agent":
            candidates += _run_agent(config, keys, completion, report, progress, len(candidates))
            continue
        key = _secret(keys, SOURCE_KEYS[name])
        if not key:
            report.status = "no_api_key"
            continue
        opts = getattr(config, name)
        api = paid(name, opts.max_requests)
        source_class = {
            "google_places": PlacesSource,
            "web_search": WebSearchSource,
            "social_search": SocialSearchSource,
        }[name]
        candidates += _run_source(source_class(config, key, api), report)
        report.requests_sent, report.requests_cached = api.sent, api.cached
        if progress:
            progress(name, len(candidates))

    stores = merge(candidates, config.countries, config.exclude_domains)

    looked_up, lookup_error = 0, ""
    lookup_api = paid("resolve", config.resolve.max_requests)
    tavily = _secret(keys, "tavily")
    wants_lookup = not only or "resolve" in only
    if config.resolve.enabled and tavily and wants_lookup:
        looked_up, lookup_error = _lookup_websites(config, stores, tavily, lookup_api)
        stores = fold_by_website(stores)

    stores_csv = root / "stores.csv"
    _write_csv(stores, stores_csv)
    (root / "stores.json").write_text(
        json.dumps([s.model_dump() for s in stores], ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    summary: dict[str, Any] = {
        "discovery_id": discovery_id,
        "started_at": started.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "scrapebot_version": __version__,
        "config": config.model_dump(mode="json"),  # never holds keys
        "sources": [r.model_dump() for r in reports],
        "website_lookup": {
            "found": looked_up,
            "requests_sent": lookup_api.sent,
            "requests_cached": lookup_api.cached,
            "error": lookup_error,
        },
        "candidates": len(candidates),
        "stores": len(stores),
        "stores_with_website": sum(bool(s.website) for s in stores),
    }
    report_path = root / "report.json"
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return DiscoverResult(
        discovery_id=discovery_id,
        root=root,
        stores_csv=stores_csv,
        report_path=report_path,
        stores=stores,
        sources=reports,
        websites_looked_up=looked_up,
    )


def stores_to_visit(stores: list[FoundStore], count: int | None) -> list[FoundStore]:
    """The stores a run should visit: those with a website, at most `count`, in the order
    the sources found them most often (stores several sources agree on first)."""
    with_site = [s for s in stores if s.website]
    with_site.sort(key=lambda s: -len(s.sources))
    return with_site[:count] if count else with_site


def write_links_file(stores: list[FoundStore], path: Path) -> Path:
    """A links file `scrapebot run` reads, for a chosen subset of stores."""
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_csv(stores, path)
    return path

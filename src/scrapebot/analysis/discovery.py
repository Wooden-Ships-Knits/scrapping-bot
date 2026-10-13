"""How good a discovery was, checked against things the bot did not invent.

A discovery's stores are leads from search APIs and a language model, and a model can
invent a store. Three checks say how far to trust one, none of which opens a website:

- **Known stockists found.** The operator's stockist list is ground truth: stores that
  exist and carry Wooden Ships. How many of the stockists in the countries searched did
  the discovery find (recall), and how many of the stores it found are stockists? It
  cannot say a store is wrong: a store that is not a stockist is the prospect the search
  is for.
- **Agreement.** A store two sources found independently is far less likely invented.
- **What the run then found**, when a run folder is given: of the stores visited, how
  many could be read, how many made the final list (multi-brand, sells knitwear), and
  how many have no website at that address at all, which is what an invented store
  looks like.

Reads the discovery folder, the stockist list and a run's `stores` table; never fetches.
"""

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ..discover import geo
from ..final import qualifies
from ..inputs.resolve import canonical_domain
from .inputs import Customer, core_name

MIN_NAME = 4  # a shorter core name ("ava", "zoe") matches too many stores
EXAMPLES = 10
# How a failed visit reads when the name does not resolve: there is no such website.
_NO_SITE = ("NameResolution", "getaddrinfo", "nodename nor servname", "Name or service not known")


class SourceScore(BaseModel):
    name: str
    stores: int  # stores this source saw
    with_website: int
    stockists: int  # of them, known stockists


class Scorecard(BaseModel):
    discovery_id: str
    stores: int
    with_website: int
    confirmed: int  # found by two or more sources
    read_before: int = 0  # found again, but a run had read them: left out of the visit
    cost_usd: float  # the discovery's own estimate
    countries: list[str]
    # Against the stockist list; all zero or None when there is no list.
    stockists_known: int  # stockists in the countries searched
    stockists_found: int
    recall: float | None  # stockists_found / stockists_known
    stockist_share: float | None  # stockists_found / stores: how on-target the search was
    stockist_examples: list[str] = Field(default_factory=list)
    sources: list[SourceScore] = Field(default_factory=list)
    # Against the run that visited them; None when no run was given.
    run_id: str = ""
    visited: int | None = None
    read: int | None = None  # ok or no_products: the website exists
    failed: int | None = None  # error of any kind: robots.txt, a timeout, no such site
    missing: int | None = None  # of those, no website at that address: invented or closed
    blocked: int | None = None  # blocked or rate-limited: exists, but said nothing
    final: int | None = None  # multi-brand and sells knitwear (ADR 0010)
    precision: float | None = None  # final / read
    cost_per_final_store: float | None = None
    missing_examples: list[str] = Field(default_factory=list)


def _in_countries(stockist: Customer, countries: Iterable[str]) -> bool:
    """Whether a stockist is in one of the countries searched. The list writes a name
    ("United States") or a code; a stockist with no country is counted everywhere."""
    written = stockist.country.strip().lower()
    if not written:
        return True
    code = geo.COUNTRIES.get(written, written.upper())
    return code in set(countries)


def _ratio(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def _stockist_of(
    store: dict[str, Any], by_domain: dict[str, Customer], by_name: dict[str, list[Customer]]
) -> Customer | None:
    """The stockist a found store is: by website, else by name where the state agrees."""
    domain = canonical_domain(store.get("website") or "") if store.get("website") else ""
    if domain and domain in by_domain:
        return by_domain[domain]
    label = core_name(store.get("name") or "")
    if len(label) < MIN_NAME:
        return None
    states = {loc.get("state") for loc in store.get("locations") or [] if loc.get("state")}
    for stockist in by_name.get(label, []):
        if not states or not stockist.state or stockist.state in states:
            return stockist
    return None


def score(discovery: Path, stockists: list[Customer], run: Path | None = None) -> Scorecard:
    """The scorecard of the discovery in folder `discovery`, against the stockist list
    and, when given, the folder of the run that visited its stores."""
    report = json.loads((discovery / "report.json").read_text(encoding="utf-8"))
    stores = json.loads((discovery / "stores.json").read_text(encoding="utf-8"))
    countries = report.get("config", {}).get("countries") or []

    known = [s for s in stockists if _in_countries(s, countries)]
    by_domain = {s.domain: s for s in known if s.domain}
    by_name: dict[str, list[Customer]] = {}
    for s in known:
        if len(core_name(s.name)) >= MIN_NAME:
            by_name.setdefault(core_name(s.name), []).append(s)

    matched: dict[int, Customer] = {}
    for i, store in enumerate(stores):
        if stockist := _stockist_of(store, by_domain, by_name):
            matched[i] = stockist
    found = {id(s): s for s in matched.values()}  # two found stores can be one stockist

    per_source = []
    for name in dict.fromkeys(src for store in stores for src in store.get("sources") or []):
        seen = [i for i, store in enumerate(stores) if name in (store.get("sources") or [])]
        per_source.append(
            SourceScore(
                name=name,
                stores=len(seen),
                with_website=sum(bool(stores[i].get("website")) for i in seen),
                stockists=sum(i in matched for i in seen),
            )
        )

    card = Scorecard(
        discovery_id=report.get("discovery_id", discovery.name),
        stores=len(stores),
        with_website=sum(bool(s.get("website")) for s in stores),
        confirmed=sum(len(s.get("sources") or []) >= 2 for s in stores),
        read_before=report.get("stores_read_before", 0),
        cost_usd=report.get("cost_usd")
        or round(sum(s.get("cost_usd", 0.0) for s in report.get("sources", [])), 6),
        countries=countries,
        stockists_known=len(known),
        stockists_found=len(found),
        recall=_ratio(len(found), len(known)),
        stockist_share=_ratio(len(matched), len(stores)) if known else None,
        stockist_examples=sorted(s.name for s in found.values())[:EXAMPLES],
        sources=per_source,
    )
    if run is not None:
        _add_run(card, run)
    return card


def _add_run(card: Scorecard, run: Path) -> None:
    rows = []
    path = run / "tables" / "stores.jsonl"
    if path.exists():
        with path.open(encoding="utf-8") as fh:
            rows = [json.loads(line) for line in fh if line.strip()]
    read = [r for r in rows if r.get("status") in ("ok", "no_products")]
    failed = [r for r in rows if r.get("status") == "error"]
    final = [r for r in rows if qualifies(r)]
    card.run_id = run.name
    card.visited = len(rows)
    card.read = len(read)
    card.failed = len(failed)
    missing = [r for r in failed if any(mark in (r.get("error") or "") for mark in _NO_SITE)]
    card.missing = len(missing)
    card.missing_examples = [r["domain"] for r in missing][:EXAMPLES]
    card.blocked = sum(r.get("status") in ("blocked", "rate_limited") for r in rows)
    card.final = len(final)
    card.precision = _ratio(len(final), len(read))
    paid = card.cost_usd > 0 and bool(final)  # a search answered from the cache cost nothing
    card.cost_per_final_store = round(card.cost_usd / len(final), 4) if paid else None


def as_text(card: Scorecard) -> str:
    """The scorecard as lines for a terminal."""

    def pct(value: float | None) -> str:
        return "n/a" if value is None else f"{100 * value:.0f}%"

    lines = [
        f"Discovery {card.discovery_id}: {card.stores} stores, {card.with_website} with a "
        f"website, {card.confirmed} found by two or more sources. Estimated cost "
        f"US${card.cost_usd:.3f}.",
        "",
    ]
    if card.stockists_known:
        lines += [
            f"Known stockists in {', '.join(card.countries) or 'the countries searched'}: "
            f"{card.stockists_known}. Found: {card.stockists_found} ({pct(card.recall)}).",
            f"Stores found that are already stockists: {pct(card.stockist_share)}.",
        ]
        if card.stockist_examples:
            lines.append("  e.g. " + "; ".join(card.stockist_examples))
    else:
        lines.append("No stockist list for the countries searched: nothing to check against.")
    if card.sources:
        lines += ["", f"{'source':<16}{'stores':>8}{'website':>9}{'stockists':>11}"]
        lines += [
            f"{s.name:<16}{s.stores:>8}{s.with_website:>9}{s.stockists:>11}" for s in card.sources
        ]
    if card.visited is not None:
        lines += [
            "",
            f"Run {card.run_id}: {card.visited} visited, {card.read} read, {card.blocked} "
            f"blocked, {card.failed} failed.",
            f"No website at that address (invented or closed): {card.missing}"
            + (f": {', '.join(card.missing_examples)}" if card.missing_examples else "")
            + ".",
            f"On the final list (multi-brand, sells knitwear): {card.final} "
            f"({pct(card.precision)} of the stores read).",
        ]
        if card.cost_per_final_store is not None:
            lines.append(f"Search cost per final store: US${card.cost_per_final_store:.3f}.")
    return "\n".join(lines)

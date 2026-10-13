"""Which store was read when, and by which run (ADR 0013).

A store read in the last `fetch.reuse_days` days is loaded from that run's tables
instead of being visited again: no requests to the store, no LLM tokens. The ledger
is a SQLite file next to the run folders. It is derived from them, so it can be
deleted: it is rebuilt from every run on disk the next time it is opened.
"""

import json
import logging
import re
import sqlite3
from collections.abc import Container, Iterable, Iterator
from contextlib import closing, suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .models import Acquired, Contact, Page, Product
from .store import SUMMARY_ROWS_FILE

log = logging.getLogger(__name__)

LEDGER_FILE = "ledger.sqlite"
# Bumped when the table changes. A ledger of another version, or one whose first build
# did not finish, is thrown away and built again from the run folders.
SCHEMA_VERSION = 2
# A store that was read, with or without a catalogue, stays as it is for a while. One
# that was blocked, rate-limited or failed is worth another visit.
REUSABLE = ("ok", "no_products")
# A visit that says something about the store itself. An error or a rate limit says
# nothing, so the store still counts as new to a search.
SETTLED = (*REUSABLE, "blocked", "js_required")
LOAD_AT_ONCE = 10  # stores of one run held in memory together while they are loaded
_DOMAIN = re.compile(r'\{"run_id":"[^"]*","domain":"([^"]*)"')

_SCHEMA = """
CREATE TABLE IF NOT EXISTS visits (
    domain TEXT NOT NULL,
    run_id TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    status TEXT NOT NULL,
    product_count INTEGER NOT NULL,
    unfinished INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (domain, run_id)
)
"""


@dataclass(frozen=True)
class Visit:
    """One store read by one run. A store loaded from an earlier run is not a visit."""

    domain: str
    run_id: str
    fetched_at: str  # ISO 8601, UTC
    status: str
    product_count: int
    # The LLM stage could still change what was found, and did not get to: see
    # `is_unfinished`. Such a visit is only good enough for a run that has no LLM either.
    unfinished: bool = False


@dataclass
class Loaded:
    """A store as an earlier run read it."""

    acquired: Acquired
    # That run's summary row: it was computed while the page HTML was in memory, which is
    # never stored, so it cannot be computed again. None for a run that kept none.
    summary: dict[str, Any] | None


def is_unfinished(status: str, store_type: str, llm_worked: bool) -> bool:
    """Whether a visit left a question the LLM stage answers (no catalogue found, or a
    store type nothing decided) while that stage did not work for it: switched off, no
    key, or every call failed. Without this, a store read on a day the key was wrong
    would count as done for a month."""
    open_question = status == "no_products" or (status == "ok" and store_type in ("", "unknown"))
    return open_question and not llm_worked


def _rows(path: Path) -> Iterator[dict[str, Any]]:
    """A table's rows. A line that is not JSON (a run killed mid-write) is passed over."""
    if not path.exists():
        return
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except ValueError:
                log.warning("Skipped a broken line in %s", path)


def _run_visits(root: Path) -> Iterator[Visit]:
    """The visits one run folder records. Whether its LLM stage worked is read from its
    config, its `runs` row and its `llm_calls`."""
    tables = root / "tables"
    config: dict[str, Any] = {}
    with suppress(OSError, ValueError):
        config = json.loads((root / "config.json").read_text(encoding="utf-8"))
    run = next(_rows(tables / "runs.jsonl"), {})
    stage_on = bool((config.get("llm") or {}).get("enabled")) and not run.get("llm_skipped")
    answered: set[str] = set()
    failed: set[str] = set()
    for call in _rows(tables / "llm_calls.jsonl"):
        (answered if call.get("status") == "ok" else failed).add(call.get("domain", ""))
    for row in _rows(tables / "stores.jsonl"):
        if row.get("reused_from") or "domain" not in row:
            continue
        domain, status = row["domain"], row.get("status", "")
        worked = stage_on and (domain in answered or domain not in failed)
        yield Visit(
            domain=domain,
            run_id=root.name,
            fetched_at=row.get("fetched_at", ""),
            status=status,
            product_count=row.get("product_count", 0),
            unfinished=is_unfinished(status, row.get("store_type", ""), worked),
        )


class Ledger:
    def __init__(self, runs_dir: Path):
        self.runs_dir = Path(runs_dir)
        self.path = self.runs_dir / LEDGER_FILE
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db:
            built = db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        if not built:
            self.rebuild()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=30)

    def record(self, visits: Iterable[Visit]) -> None:
        rows = [
            (v.domain, v.run_id, v.fetched_at, v.status, v.product_count, int(v.unfinished))
            for v in visits
        ]
        with closing(self._connect()) as db, db:
            db.executemany("INSERT OR REPLACE INTO visits VALUES (?, ?, ?, ?, ?, ?)", rows)

    def rebuild(self) -> int:
        """Throw the table away and read every run folder again; returns the visits
        found. The version is written last, so a rebuild that did not finish is done
        again the next time the ledger is opened."""
        visits = [
            visit
            for root in sorted(p for p in self.runs_dir.iterdir() if p.is_dir())
            for visit in _run_visits(root)
        ]
        with closing(self._connect()) as db, db:
            db.execute("PRAGMA user_version = 0")
            db.execute("DROP TABLE IF EXISTS visits")
            db.execute(_SCHEMA)
        self.record(visits)
        with closing(self._connect()) as db, db:
            db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        log.info("Ledger rebuilt from %s: %d store visits", self.runs_dir, len(visits))
        return len(visits)

    def _newest(self, max_age_days: float, now: datetime | None) -> dict[str, Visit]:
        """Each store's newest visit in the last `max_age_days`, whatever its outcome:
        the newest one is what is known about the store. Visits whose run folder is gone
        are not counted: deleting a run forgets its stores."""
        cutoff = (now or datetime.now(UTC)) - timedelta(days=max_age_days)
        with closing(self._connect()) as db:
            rows = db.execute(
                "SELECT domain, run_id, fetched_at, status, product_count, unfinished "
                "FROM visits WHERE fetched_at >= ? ORDER BY fetched_at",
                (cutoff.isoformat(timespec="seconds"),),
            ).fetchall()
        present: dict[str, bool] = {}
        newest: dict[str, Visit] = {}
        for domain, run_id, fetched_at, status, products, unfinished in rows:  # oldest first
            if run_id not in present:
                present[run_id] = self._has_rows(run_id)
            if present[run_id]:
                newest[domain] = Visit(
                    domain, run_id, fetched_at, status, products, bool(unfinished)
                )
        return newest

    def recent(
        self,
        domains: Iterable[str],
        max_age_days: float,
        now: datetime | None = None,
        with_unfinished: bool = False,
    ) -> dict[str, Visit]:
        """The stores of `domains` that can be loaded instead of visited: their newest
        visit in the last `max_age_days` read the store. A store whose newest visit was
        blocked or failed is visited again, whatever an older visit found. One the LLM
        stage did not get to is only loaded `with_unfinished`: by a run that has no LLM
        stage either. 0 days finds nothing."""
        wanted = set(domains)
        if not wanted or not max_age_days:
            return {}
        return {
            domain: visit
            for domain, visit in self._newest(max_age_days, now).items()
            if domain in wanted
            and visit.status in REUSABLE
            and (with_unfinished or not visit.unfinished)
        }

    def settled(
        self, max_age_days: float, now: datetime | None = None, with_unfinished: bool = False
    ) -> list[str]:
        """The stores whose newest visit in the last `max_age_days` gave an answer: read,
        blocked, or needing a browser. Newest first; 0 days gives none. A search for new
        stores leaves these out (ADR 0013). One the LLM stage did not get to still counts
        as new, unless `with_unfinished`."""
        if not max_age_days:
            return []
        visits = [
            v
            for v in self._newest(max_age_days, now).values()
            if v.status in SETTLED and (with_unfinished or not v.unfinished)
        ]
        return [v.domain for v in sorted(visits, key=lambda v: v.fetched_at, reverse=True)]

    def _has_rows(self, run_id: str) -> bool:
        return (self.runs_dir / run_id / "tables" / "stores.jsonl").exists()


def _rows_of(path: Path, domains: Container[str]) -> Iterator[dict[str, Any]]:
    """The rows of some stores in one table. Only those rows are parsed: a products
    table can hold a gigabyte, and `run_id` and `domain` are the first fields of a row."""
    if not path.exists():
        return
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            found = _DOMAIN.match(line)
            domain = found.group(1) if found else json.loads(line).get("domain")
            if domain in domains:
                yield json.loads(line)


def load_stores(runs_dir: Path, visits: Iterable[Visit]) -> Iterator[tuple[Visit, Loaded]]:
    """The stores of `visits` as their runs read them, a few stores at a time so a large
    run never sits in memory whole. A store whose rows are gone is left out: the caller
    visits it instead."""
    by_run: dict[str, list[Visit]] = {}
    for visit in visits:
        by_run.setdefault(visit.run_id, []).append(visit)
    for run_id, wanted in by_run.items():
        tables = Path(runs_dir) / run_id / "tables"
        for at in range(0, len(wanted), LOAD_AT_ONCE):
            batch = {v.domain: v for v in wanted[at : at + LOAD_AT_ONCE]}
            yield from _load_batch(tables, batch)


def _load_batch(tables: Path, batch: dict[str, Visit]) -> Iterator[tuple[Visit, Loaded]]:
    got = {row["domain"]: _acquired(row) for row in _rows_of(tables / "stores.jsonl", batch)}
    for row in _rows_of(tables / "products.jsonl", got):
        fields = {k: v for k, v in row.items() if k in Product.model_fields}
        got[row["domain"]].products.append(Product.model_validate(fields))
    for row in _rows_of(tables / "pages.jsonl", got):
        got[row["domain"]].pages.append(
            Page(
                url=row["url"],
                text=row.get("text", ""),
                kind=row.get("page_kind", "other"),
                http_status=row.get("http_status"),
                error=row.get("error", ""),
                via=row.get("via", "http"),
            )
        )
    for row in _rows_of(tables / "contacts.jsonl", got):
        got[row["domain"]].contacts.append(
            Contact(type=row["type"], value=row["value"], source_url=row["source_url"])
        )
    summaries = {r["domain"]: r for r in _rows_of(tables.parent / SUMMARY_ROWS_FILE, got)}
    for domain, acquired in got.items():
        yield batch[domain], Loaded(acquired, summaries.get(domain))


def _acquired(store: dict[str, Any]) -> Acquired:
    """A `stores` row back as the record it was written from; its products, pages and
    contacts are added by the caller. Model calls are not carried over: they were paid
    for by the run that made them."""
    keep = set(Acquired.model_fields) - {"products", "pages", "contacts", "llm_calls"}
    return Acquired.model_validate({k: v for k, v in store.items() if k in keep})

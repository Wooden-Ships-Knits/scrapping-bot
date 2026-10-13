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
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .models import Acquired, Contact, Page, Product
from .store import SUMMARY_ROWS_FILE

log = logging.getLogger(__name__)

LEDGER_FILE = "ledger.sqlite"
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


@dataclass
class Loaded:
    """A store as an earlier run read it."""

    acquired: Acquired
    # That run's summary row: it was computed while the page HTML was in memory, which is
    # never stored, so it cannot be computed again. None for a run that kept none.
    summary: dict[str, Any] | None


def _rows(path: Path) -> Iterator[dict[str, Any]]:
    if not path.exists():
        return
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


class Ledger:
    def __init__(self, runs_dir: Path):
        self.runs_dir = Path(runs_dir)
        self.path = self.runs_dir / LEDGER_FILE
        fresh = not self.path.exists()
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db, db:
            db.execute(_SCHEMA)
        if fresh:
            self.rebuild()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=30)

    def record(self, visits: Iterable[Visit]) -> None:
        rows = [(v.domain, v.run_id, v.fetched_at, v.status, v.product_count) for v in visits]
        with closing(self._connect()) as db, db:
            db.executemany("INSERT OR REPLACE INTO visits VALUES (?, ?, ?, ?, ?)", rows)

    def rebuild(self) -> int:
        """Read every run folder's `stores` table again; returns the visits found."""
        visits = [
            Visit(
                domain=row["domain"],
                run_id=root.name,
                fetched_at=row.get("fetched_at", ""),
                status=row.get("status", ""),
                product_count=row.get("product_count", 0),
            )
            for root in sorted(p for p in self.runs_dir.iterdir() if p.is_dir())
            for row in _rows(root / "tables" / "stores.jsonl")
            if not row.get("reused_from")
        ]
        with closing(self._connect()) as db, db:
            db.execute("DELETE FROM visits")
        self.record(visits)
        log.info("Ledger rebuilt from %s: %d store visits", self.runs_dir, len(visits))
        return len(visits)

    def recent(
        self, domains: Iterable[str], max_age_days: float, now: datetime | None = None
    ) -> dict[str, Visit]:
        """For each of `domains`, its newest reusable visit in the last `max_age_days`
        whose run folder still holds the rows. 0 days finds nothing."""
        wanted = set(domains)
        if not wanted or not max_age_days:
            return {}
        cutoff = (now or datetime.now(UTC)) - timedelta(days=max_age_days)
        marks = ", ".join("?" for _ in REUSABLE)
        with closing(self._connect()) as db:
            rows = db.execute(
                f"SELECT domain, run_id, fetched_at, status, product_count FROM visits "
                f"WHERE status IN ({marks}) AND fetched_at >= ? ORDER BY fetched_at",
                (*REUSABLE, cutoff.isoformat(timespec="seconds")),
            ).fetchall()
        found: dict[str, Visit] = {}
        for row in rows:  # oldest first: the newest one wins
            visit = Visit(*row)
            if visit.domain in wanted and self._has_rows(visit.run_id):
                found[visit.domain] = visit
        return found

    def settled(self, max_age_days: float, now: datetime | None = None) -> list[str]:
        """The stores a run visited in the last `max_age_days` and got an answer from:
        read, blocked, or needing a browser. Newest visit first; 0 days gives none. A
        search for new stores leaves these out (ADR 0013)."""
        if not max_age_days:
            return []
        cutoff = (now or datetime.now(UTC)) - timedelta(days=max_age_days)
        marks = ", ".join("?" for _ in SETTLED)
        with closing(self._connect()) as db:
            rows = db.execute(
                f"SELECT domain, MAX(fetched_at) AS seen FROM visits "
                f"WHERE status IN ({marks}) AND fetched_at >= ? GROUP BY domain ORDER BY seen DESC",
                (*SETTLED, cutoff.isoformat(timespec="seconds")),
            ).fetchall()
        return [domain for domain, _ in rows]

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

"""Which stores detect the bot, read from the run folders.

A store "blocks" when its homepage answers with an anti-bot challenge page or a
401/403/429 (`acquire`). The bot never works around a block (ADR 0002); this view
only shows how often it happens, how, and which stores are not worth visiting again.
"""

import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .library import read_jsonl, run_roots, started_at
from .schemas import BlockedStoreOut, BlockState, DetectionOut, DetectionRunOut

_CHALLENGE = re.compile(r"challenge page \((\w+)\)")
_HTTP = re.compile(r"HTTP (\d{3})")


def block_method(error: str) -> str:
    """`challenge page (cloudflare)` -> cloudflare, `HTTP 403` -> http_403, else other.
    A refusal met in the browser stage reads the same, followed by "in the browser"."""
    if found := _CHALLENGE.search(error):
        return found.group(1)
    if found := _HTTP.search(error):
        return f"http_{found.group(1)}"
    return "other"


def _state(history: list[bool]) -> BlockState:
    """`history` holds, oldest first, whether each visit was blocked."""
    if all(history):
        return "always"
    return "sometimes" if history[-1] else "recovered"


def detection(runs_dir: Path) -> DetectionOut:
    runs: list[DetectionRunOut] = []
    methods: Counter[str] = Counter()
    # domain -> its visits, oldest first: (run_id, started_at, store row)
    visits: dict[str, list[tuple[str, str, dict[str, Any]]]] = defaultdict(list)
    for root in reversed(run_roots(runs_dir)):  # oldest first
        stores = read_jsonl(root / "tables" / "stores.jsonl")
        if not stores:
            continue
        started = started_at(root)
        blocked = [s for s in stores if s["status"] == "blocked"]
        methods.update(block_method(s["error"]) for s in blocked)
        runs.append(
            DetectionRunOut(
                run_id=root.name, started_at=started, visits=len(stores), blocked=len(blocked)
            )
        )
        for store in stores:
            visits[store["domain"]].append((root.name, started, store))

    blocked_stores = []
    for domain, seen in visits.items():
        history = [s["status"] == "blocked" for _, _, s in seen]
        if not any(history):
            continue
        last_block = next(s for _, _, s in reversed(seen) if s["status"] == "blocked")
        run_id, last_seen, last = seen[-1]
        blocked_stores.append(
            BlockedStoreOut(
                domain=domain,
                platform=last.get("platform") or "",
                visits=len(seen),
                blocked=sum(history),
                state=_state(history),
                last_method=block_method(last_block["error"]),
                last_run_id=run_id,
                last_seen=last_seen,
            )
        )
    order = {"always": 0, "sometimes": 1, "recovered": 2}
    blocked_stores.sort(key=lambda s: (order[s.state], -s.blocked, s.domain))

    return DetectionOut(
        visits=sum(r.visits for r in runs),
        blocked=sum(r.blocked for r in runs),
        stores=len(visits),
        stores_blocked=len(blocked_stores),
        by_method=dict(methods.most_common()),
        runs=runs[::-1],
        blocked_stores=blocked_stores,
    )

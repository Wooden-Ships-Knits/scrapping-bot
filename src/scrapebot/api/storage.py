"""What the operator may delete from the interface: a run, and the caches.

Both are final: nothing is moved to a bin. A run's folder holds everything the bot
learned about its stores, so once it is gone the ledger forgets those visits and the
stores count as not read (ADR 0013). A cache only saves a second request or a second
payment: deleting one loses nothing that cannot be fetched or asked again.
"""

import shutil
from pathlib import Path

from ..fetch import CACHE_KEEP

# pages:  what store websites returned. Fetched again by the next run.
# search: answers of the paid search APIs and the agent. Asked, and paid for, again.
# llm:    answers of the LLM stage, by content. Asked, and paid for, again.
CACHE_KINDS = ("pages", "search", "llm")


def delete_run(root: Path, process_dir: Path) -> None:
    """Remove a run's folder, and what `process/` wrote for it (the Retailer map would
    otherwise keep showing a run that no longer exists)."""
    shutil.rmtree(root)
    shutil.rmtree(process_dir / root.name, ignore_errors=True)


def _folders(kind: str, cache_dir: Path, search_dir: Path) -> list[Path]:
    """The folders one kind of cache lives in."""
    if kind == "search":
        return [search_dir]
    if kind == "llm":
        return [cache_dir / "llm"]
    if not cache_dir.is_dir():
        return []
    # Pages: one folder per host. Everything else in the cache folder is another kind.
    other = {search_dir.resolve(), (cache_dir / "llm").resolve()}
    return [
        p
        for p in sorted(cache_dir.iterdir())
        if p.is_dir() and p.name not in CACHE_KEEP and p.resolve() not in other
    ]


def cache_usage(cache_dir: Path, search_dir: Path) -> dict[str, tuple[int, int]]:
    """Per kind of cache: (files, bytes)."""
    usage = {}
    for kind in CACHE_KINDS:
        files = [
            f for d in _folders(kind, cache_dir, search_dir) if d.is_dir() for f in d.rglob("*")
        ]
        sizes = [f.stat().st_size for f in files if f.is_file()]
        usage[kind] = (len(sizes), sum(sizes))
    return usage


def clear_cache(kind: str, cache_dir: Path, search_dir: Path) -> None:
    """Delete one kind of cache, or every kind for "all"."""
    for one in CACHE_KINDS if kind == "all" else (kind,):
        for folder in _folders(one, cache_dir, search_dir):
            shutil.rmtree(folder, ignore_errors=True)

"""Runs started from the web app, executed one at a time in a background thread.

One worker keeps the per-domain politeness of a single run intact and keeps the
machine responsive; later runs wait in the queue.
"""

import logging
import threading
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from pydantic import SecretStr

from ..fetch import Fetcher
from ..pipeline import PreparedRun, execute
from .schemas import RunState

log = logging.getLogger(__name__)

FetcherFactory = Callable[[], Fetcher]


@dataclass
class LiveRun:
    run_id: str
    state: RunState = "queued"
    error: str = ""
    stop: threading.Event = field(default_factory=threading.Event)
    # Keys for this run, in memory only, kept so a stopped run can resume with them.
    keys: Mapping[str, SecretStr] = field(default_factory=dict, repr=False)


class RunManager:
    def __init__(self, fetcher_factory: FetcherFactory | None = None):
        self._fetcher_factory = fetcher_factory
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="scrapebot-run")
        self._runs: dict[str, LiveRun] = {}
        self._lock = threading.Lock()

    def submit(self, prepared: PreparedRun, keys: Mapping[str, SecretStr] | None = None) -> LiveRun:
        live = LiveRun(run_id=prepared.run_id, keys=dict(keys or {}))
        with self._lock:
            self._runs[live.run_id] = live
        self._executor.submit(self._execute, prepared, live)
        return live

    def _execute(self, prepared: PreparedRun, live: LiveRun) -> None:
        if live.stop.is_set():  # stopped while still queued
            live.state = "stopped"
            return
        live.state = "running"
        try:
            fetcher = self._fetcher_factory() if self._fetcher_factory else None
            result = execute(prepared, fetcher=fetcher, stop=live.stop, keys=live.keys)
            live.state = "stopped" if result.stopped else "done"
        except Exception as exc:  # a failed run must be visible, never crash the server
            log.exception("Run %s failed", live.run_id)
            live.error = f"{type(exc).__name__}: {exc}"
            live.state = "failed"

    def stop(self, run_id: str) -> bool:
        """Ask a queued or running run to stop after the stores in progress."""
        live = self.get(run_id)
        if live is None or live.state not in ("queued", "running"):
            return False
        live.stop.set()
        return True

    def get(self, run_id: str) -> LiveRun | None:
        with self._lock:
            return self._runs.get(run_id)

    def states(self) -> dict[str, RunState]:
        with self._lock:
            return {run_id: live.state for run_id, live in self._runs.items()}

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

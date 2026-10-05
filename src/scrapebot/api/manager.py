"""Runs started from the web app, executed one at a time in a background thread.

One worker keeps the per-domain politeness of a single run intact and keeps the
machine responsive; later runs wait in the queue.
"""

import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

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


class RunManager:
    def __init__(self, fetcher_factory: FetcherFactory | None = None):
        self._fetcher_factory = fetcher_factory
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="scrapebot-run")
        self._runs: dict[str, LiveRun] = {}
        self._lock = threading.Lock()

    def submit(self, prepared: PreparedRun) -> LiveRun:
        live = LiveRun(run_id=prepared.run_id)
        with self._lock:
            self._runs[live.run_id] = live
        self._executor.submit(self._execute, prepared, live)
        return live

    def _execute(self, prepared: PreparedRun, live: LiveRun) -> None:
        live.state = "running"
        try:
            fetcher = self._fetcher_factory() if self._fetcher_factory else None
            execute(prepared, fetcher=fetcher)
            live.state = "done"
        except Exception as exc:  # a failed run must be visible, never crash the server
            log.exception("Run %s failed", live.run_id)
            live.error = f"{type(exc).__name__}: {exc}"
            live.state = "failed"

    def get(self, run_id: str) -> LiveRun | None:
        with self._lock:
            return self._runs.get(run_id)

    def states(self) -> dict[str, RunState]:
        with self._lock:
            return {run_id: live.state for run_id, live in self._runs.items()}

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

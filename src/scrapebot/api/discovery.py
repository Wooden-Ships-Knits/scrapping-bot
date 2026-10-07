"""Discoveries started from the web app: find stores, then start a test run on them.

One discovery at a time, in its own thread: it talks to paid search APIs, not to
store websites, so it never competes with a run's per-domain politeness. Its state
lives in memory; its files (stores found, report) stay in the discovery folder.
"""

import logging
import secrets
import threading
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import SecretStr

from ..discover import DiscoverConfig, run_discover
from ..discover.agent import Completion
from ..discover.paid import Transport
from ..discover.run import stores_to_visit, write_links_file
from ..keys import redact
from .schemas import DiscoveryOut, DiscoverySourceOut, DiscoveryState

log = logging.getLogger(__name__)

# (links file, discovery request) -> the run id of the test run started on it.
StartRun = Callable[[Path], str]


@dataclass
class LiveDiscovery:
    discovery_id: str
    count: int
    state: DiscoveryState = "searching"
    step: str = ""
    found: int = 0
    stores_to_visit: int = 0
    sources: list[DiscoverySourceOut] = field(default_factory=list)
    cost_usd: float = 0.0
    run_id: str | None = None
    error: str = ""

    def out(self) -> DiscoveryOut:
        return DiscoveryOut(
            discovery_id=self.discovery_id,
            state=self.state,
            count=self.count,
            step=self.step,
            found=self.found,
            stores_to_visit=self.stores_to_visit,
            sources=list(self.sources),
            cost_usd=self.cost_usd,
            run_id=self.run_id,
            error=self.error,
        )


class DiscoveryManager:
    def __init__(self, transport: Transport | None = None, completion: Completion | None = None):
        self._transport = transport
        self._completion = completion
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="scrapebot-find")
        self._jobs: dict[str, LiveDiscovery] = {}
        self._lock = threading.Lock()

    def submit(
        self,
        config: DiscoverConfig,
        keys: Mapping[str, SecretStr],
        start_run: StartRun,
    ) -> LiveDiscovery:
        job = LiveDiscovery(discovery_id=secrets.token_hex(8), count=config.target_stores or 0)
        with self._lock:
            self._jobs[job.discovery_id] = job
        self._executor.submit(self._work, job, config, dict(keys), start_run)
        return job

    def _work(
        self,
        job: LiveDiscovery,
        config: DiscoverConfig,
        keys: Mapping[str, SecretStr],
        start_run: StartRun,
    ) -> None:
        def progress(step: str, found: int) -> None:
            job.step, job.found = step, found

        try:
            result = run_discover(
                config,
                keys,
                transport=self._transport,
                completion=self._completion,
                progress=progress,
            )
            job.sources = [
                DiscoverySourceOut(name=r.name, status=r.status, found=r.candidates, error=r.error)
                for r in result.sources
            ]
            job.cost_usd = round(sum(r.cost_usd for r in result.sources), 6)
            job.step, job.found = "", len(result.stores)
            chosen = stores_to_visit(result.stores, config.target_stores)
            job.stores_to_visit = len(chosen)
            if not chosen:
                job.error = "Tidak ada toko berwebsite yang ditemukan. Lihat status tiap sumber."
                job.state = "failed"
                return
            links = write_links_file(chosen, result.root / "to_visit.csv")
            job.state = "starting_run"
            job.run_id = start_run(links)
            job.state = "done"
        except Exception as exc:  # a failed discovery must be visible, never crash the server
            log.exception("Discovery %s failed", job.discovery_id)
            job.error = redact(f"{type(exc).__name__}: {exc}")
            job.state = "failed"

    def get(self, discovery_id: str) -> LiveDiscovery | None:
        with self._lock:
            return self._jobs.get(discovery_id)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

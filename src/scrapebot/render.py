"""The browser: the only module besides `fetch` that touches the network (ADR 0002).

A page whose catalogue is built by JavaScript is rendered in Camoufox. The browser
obeys the same rules as HTTP: `robots.txt` (for the page and for every request it
makes to the store's own site), one request per server at a time with the same
delay, and no way around a challenge. A challenge page, or a 401/403/429 answer, is
reported as such and its content is not used.

Playwright's sync API belongs to the thread that started it, so each browser lives
in its own worker thread and pages are handed to the workers through a queue.
"""

import contextlib
import logging
import queue
import threading
import urllib.robotparser
from collections.abc import Callable
from concurrent.futures import Future
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlparse

from .fetch import USER_AGENT, detect_challenge
from .models import FetchResult

log = logging.getLogger(__name__)

BLOCKED_STATUSES = (401, 403, 429)
# What the page needs to show its content; everything else is not loaded.
SKIPPED_RESOURCES = frozenset({"image", "media", "font"})
MAX_CAPTURED_JSON = 40
MAX_JSON_BYTES = 3_000_000


@dataclass
class CapturedJson:
    """A JSON response the page loaded while rendering, with where it came from."""

    url: str
    data: Any


@dataclass
class Rendered:
    """One rendered page: the final HTML as `result.body`, plus the JSON it loaded."""

    result: FetchResult
    captured: list[CapturedJson] = field(default_factory=list)


class Renderer(Protocol):
    """Anything that can render a URL. Acquisition depends on this, not on a browser."""

    def render(self, url: str) -> Rendered: ...

    def close(self) -> None: ...


class PoliteHost(Protocol):
    """The parts of `HttpFetcher` the browser shares, so both obey one set of rules."""

    def allowed(self, url: str) -> bool: ...

    def robots(self, url: str) -> urllib.robotparser.RobotFileParser | None: ...

    def polite(self, url: str) -> AbstractContextManager[None]: ...


def camoufox_available() -> bool:
    """True when the camoufox package and its browser are installed."""
    try:
        from camoufox.pkgman import installed_verstr  # type: ignore[import-untyped]

        return bool(installed_verstr())
    except Exception:
        return False


def _failed(url: str, error: str, status: int | None = None, challenge: str = "") -> Rendered:
    return Rendered(
        FetchResult(
            url=url, status_code=status, body="", final_url=url, error=error, challenge=challenge
        )
    )


@dataclass
class _Job:
    url: str
    rules: urllib.robotparser.RobotFileParser | None
    future: "Future[Rendered]"


class CamoufoxRenderer:
    """Renders pages in Camoufox, `workers` browsers at once. Never raises for page
    conditions: a failure comes back as a `Rendered` with `result.error` set."""

    def __init__(
        self,
        host: PoliteHost,
        workers: int = 2,
        timeout_seconds: float = 30,
        settle_seconds: float = 6,
        headless: bool = True,
    ):
        self.host = host
        self.timeout_ms = timeout_seconds * 1000
        self.settle_ms = settle_seconds * 1000
        self.headless = headless
        self._jobs: queue.Queue[_Job | None] = queue.Queue()
        self._workers = [
            threading.Thread(target=self._work, name=f"render-{i}", daemon=True)
            for i in range(workers)
        ]
        self._started = False
        self._lock = threading.Lock()

    # -- public ------------------------------------------------------------
    def render(self, url: str) -> Rendered:
        if not self.host.allowed(url):
            return _failed(url, "robots_disallowed")
        rules = self.host.robots(url)
        self._start()
        job = _Job(url, rules, Future())
        with self.host.polite(url):  # the server sees one request at a time, as with HTTP
            self._jobs.put(job)
            return job.future.result()

    def close(self) -> None:
        with self._lock:
            if not self._started:
                return
            self._started = False
        for _ in self._workers:
            self._jobs.put(None)
        for worker in self._workers:
            worker.join(timeout=30)

    # -- workers -----------------------------------------------------------
    def _start(self) -> None:
        with self._lock:
            if not self._started:
                self._started = True
                for worker in self._workers:
                    worker.start()

    def _work(self) -> None:
        browser_cm: Any = None
        browser: Any = None
        try:
            while (job := self._jobs.get()) is not None:
                try:
                    if browser is None:
                        from camoufox.sync_api import Camoufox  # type: ignore[import-untyped]

                        # en-US so prices are not localised to a guessed language (ADR 0002).
                        browser_cm = Camoufox(headless=self.headless, locale="en-US")
                        browser = browser_cm.__enter__()
                    job.future.set_result(self._render_in(browser, job))
                except Exception as exc:
                    log.warning("Browser failed on %s: %s", job.url, exc)
                    job.future.set_result(_failed(job.url, f"browser: {type(exc).__name__}"))
                    if browser_cm is not None:  # start a fresh browser for the next page
                        _quietly(lambda cm=browser_cm: cm.__exit__(None, None, None))
                    browser_cm = browser = None
        finally:
            if browser_cm is not None:
                _quietly(lambda: browser_cm.__exit__(None, None, None))

    def _render_in(self, browser: Any, job: _Job) -> Rendered:
        page = browser.new_page()
        responses: list[Any] = []
        try:
            page.route("**/*", lambda route: _route(route, job.url, job.rules))
            page.on(
                "response",
                lambda r: (
                    responses.append(r) if r.request.resource_type in ("xhr", "fetch") else None
                ),
            )
            first = page.goto(job.url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            status = first.status if first else None
            if status in BLOCKED_STATUSES:
                return _failed(job.url, f"HTTP {status}", status)
            challenge = detect_challenge(status, _text_of(first))
            if challenge:
                return _failed(job.url, "", status, challenge)
            # A page that never goes quiet (analytics, live video) is read as it is.
            with contextlib.suppress(Exception):
                page.wait_for_load_state("networkidle", timeout=self.settle_ms)
            html = page.content()
            challenge = detect_challenge(status, html)
            if challenge:
                return _failed(job.url, "", status, challenge)
            result = FetchResult(url=job.url, status_code=status, body=html, final_url=page.url)
            return Rendered(result, _json_of(responses))
        finally:
            _quietly(page.close)


def _route(route: Any, page_url: str, rules: urllib.robotparser.RobotFileParser | None) -> None:
    """Skip images, media and fonts; refuse what robots.txt disallows on the store's site."""
    request = route.request
    if request.resource_type in SKIPPED_RESOURCES:
        route.abort()
        return
    same_site = urlparse(request.url).netloc == urlparse(page_url).netloc
    if rules is not None and same_site and not rules.can_fetch(USER_AGENT, request.url):
        route.abort()
        return
    route.continue_()


def _text_of(response: Any) -> str:
    try:
        return response.text() if response is not None else ""
    except Exception:
        return ""


def _json_of(responses: list[Any]) -> list[CapturedJson]:
    out: list[CapturedJson] = []
    for response in responses:
        if len(out) >= MAX_CAPTURED_JSON:
            break
        try:
            if "json" not in (response.headers.get("content-type") or "") or response.status != 200:
                continue
            body = response.body()
            if len(body) > MAX_JSON_BYTES:
                continue
            out.append(CapturedJson(response.url, response.json()))
        except Exception:
            continue  # a response the page discarded, or not JSON after all
    return out


def _quietly(fn: Callable[[], Any]) -> None:
    with contextlib.suppress(Exception):
        fn()

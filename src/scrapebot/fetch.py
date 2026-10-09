"""The only module that touches the network over HTTP.

`HttpFetcher` is polite (robots.txt, a delay per server, backoff), cached (successful
responses only) and thread-safe, so several stores can be visited at once while
each server still sees one request at a time, `delay` seconds apart.

"Server" means the network a host resolves to (/24 for IPv4, /48 for IPv6), not the
host name: hosted platforms put thousands of stores behind one edge. Measured on
2026-10-05: six Shopify stores fetched in parallel, each politely by its own name,
all hit 23.227.38.x, and Shopify answered with a challenge page.
"""

import gzip
import hashlib
import ipaddress
import json
import socket
import threading
import time
import urllib.robotparser
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

from .models import FetchResult

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)
SSL_MARKERS = ("SSL", "CERTIFICATE_VERIFY_FAILED", "HANDSHAKE")
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_BACKOFF_SECONDS = 30.0

# Deliberately NO Accept-Language header.
#
# Sending one makes Shopify Markets localise prices to the *requester's* geo.
# Measured against a real prospect (shoploveceline.com), the same product came
# back as:
#     Accept-Language: en-US,en;q=0.9  ->  "2757000.00"   (Indonesian Rupiah)
#     no Accept-Language               ->  "98.00"        (store base currency)
# Reproduced 5/5. Four stores in the prospect list were affected.
#
# Prices are compared against the operator's own price point, so they must
# arrive in the store's base currency. A store localising to a *near* currency
# (CAD, EUR) would corrupt the price columns invisibly rather than obviously.
REQUEST_HEADERS = {"User-Agent": USER_AGENT}

# Markers of anti-bot challenge pages, by vendor. Such a page is recorded as
# `blocked` and never worked around (ADR 0002).
#
# Cloudflare is matched on its challenge page only: the title, the challenge options and the
# challenge script under /h/. Its bot-detection script (/cdn-cgi/challenge-platform/scripts/
# jsd/main.js) also sits on ordinary pages, and matching it read normal stores as blocked
# (dearprudence.com, outgoing.world, foundationcenter.org: status 200, whole page; checked
# 2026-10-09). Roadmap issue 15.
CHALLENGE_MARKERS = {
    "cloudflare": (
        "<title>just a moment",
        "_cf_chl_opt",
        "cf-chl-",
        "/cdn-cgi/challenge-platform/h/",
        "attention required! | cloudflare",
    ),
    "datadome": ("captcha-delivery.com", "datadome"),
    "perimeterx": ("px-captcha", "_pxappid"),
    "incapsula": ("_incapsula_resource", "incap_ses"),
    "sucuri": ("sucuri website firewall", "sucuri_cloudproxy"),
    "akamai": ("_abck", "bm-verify", "sec-if-cpt"),
}
# A real page can mention these words; a challenge page is short and little else.
CHALLENGE_MAX_CHARS = 60_000
CHALLENGE_STATUSES = frozenset({200, 301, 302, 303, 307, 308, 403, 429, 503})

# Roadmap issue 16. Hosted platforms put thousands of stores behind one network, and that
# network limits a client across all of them: on 2026-10-08, 306 of 376 "blocked" stores
# were Shopify stores behind 23.227.38.x, refused in waves, and all opened normally the
# next day. So when two different sites on one network refuse us within RATE_LIMIT_WINDOW,
# or one answers 429, it is our address being limited, not the stores blocking us: the
# network is left alone for a cooldown (doubled each time), its delay is doubled, and the
# stores are retried after the pause. Slowing down is the polite answer (ADR 0002).
RATE_LIMIT_WINDOW = 600.0
RATE_LIMIT_SITES = 2
COOLDOWN_SECONDS = 300.0
MAX_COOLDOWN_SECONDS = 1800.0
MAX_DELAY_SECONDS = 10.0
REFUSAL_STATUSES = frozenset({401, 403})

# (url, headers, verify_tls, timeout) -> (status_code, body, final_url). Raises on
# network failure. Swapped for a fake in tests.
Transport = Callable[[str, dict[str, str], bool, float], tuple[int, str, str]]
# host -> IP address, or None when it cannot be resolved.
Resolver = Callable[[str], str | None]


def _resolve(host: str) -> str | None:
    try:
        return str(socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)[0][4][0])
    except (OSError, IndexError, UnicodeError):
        return None


def server_network(ip: str) -> str:
    """The network an address belongs to, as the unit of politeness."""
    addr = ipaddress.ip_address(ip)
    prefix = 24 if addr.version == 4 else 48
    return str(ipaddress.ip_network(f"{ip}/{prefix}", strict=False))


class Fetcher(Protocol):
    """Anything that can GET a URL. Acquisition depends on this, not on HTTP."""

    def get(self, url: str) -> FetchResult: ...

    def sitemaps(self, origin: str) -> list[str]:
        """Sitemaps the site declares (robots.txt); [] when unknown."""
        ...


def detect_challenge(status: int | None, body: str) -> str:
    """The vendor of an anti-bot challenge page, or "" for an ordinary response.

    Redirect statuses count: PerimeterX answers ralphlauren.com with its block page
    and status 307 (no Location header), which used to end as a plain `error`. A 404
    does not: Cloudflare injects its challenge script into ordinary pages too.
    """
    if status not in CHALLENGE_STATUSES or len(body) > CHALLENGE_MAX_CHARS:
        return ""
    lowered = body.lower()
    for vendor, markers in CHALLENGE_MARKERS.items():
        if any(m in lowered for m in markers):
            return vendor
    return ""


# Folders inside the cache that are not pages and must never be pruned: the paid
# discovery answers (ADR 0008) live in data/.cache/discover.
CACHE_KEEP = frozenset({"discover"})


def prune_cache(cache_dir: Path, max_age_seconds: float, now: float | None = None) -> int:
    """Delete cached pages older than `max_age_seconds`; returns how many. Pages only:
    folders in CACHE_KEEP are left alone. 0 deletes nothing."""
    if not max_age_seconds or not cache_dir.is_dir():
        return 0
    cutoff = (now if now is not None else time.time()) - max_age_seconds
    removed = 0
    for host in cache_dir.iterdir():
        if not host.is_dir() or host.name in CACHE_KEEP:
            continue
        for page in host.iterdir():
            if page.suffix in (".json", ".part") and page.stat().st_mtime < cutoff:
                page.unlink(missing_ok=True)
                removed += 1
        if not any(host.iterdir()):
            host.rmdir()
    return removed


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def _decode(content: bytes, encoding: str | None) -> str:
    if content[:2] == b"\x1f\x8b":  # a gzipped file such as sitemap.xml.gz
        content = gzip.decompress(content)
    return content.decode(encoding or "utf-8", errors="replace")


def _requests_transport(
    url: str, headers: dict[str, str], verify: bool, timeout: float
) -> tuple[int, str, str]:
    import requests

    r = requests.get(url, headers=headers, verify=verify, timeout=timeout, allow_redirects=True)
    return (r.status_code, _decode(r.content, r.encoding or r.apparent_encoding), r.url)


class HttpFetcher:
    """Polite, cached, thread-safe HTTP. Never raises for network conditions."""

    def __init__(
        self,
        cache_dir: str | Path,
        delay: float = 1.5,
        timeout: float = 20,
        retries: int = 2,
        transport: Transport | None = None,
        respect_robots: bool = True,
        backoff_seconds: float = 2.0,
        resolver: Resolver | None = None,
        clock: Callable[[], float] = time.monotonic,
        max_age_seconds: float = 0,
    ):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.delay = delay
        self.timeout = timeout
        self.retries = retries
        self.respect_robots = respect_robots
        self.backoff_seconds = backoff_seconds
        self._transport = transport or _requests_transport
        self._last_request: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}
        self._resolver = resolver or _resolve
        self._lock = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}
        self._keys: dict[str, str] = {}
        self._clock = clock
        self.max_age_seconds = max_age_seconds  # 0: cached pages never expire
        self._refusals: dict[str, list[tuple[float, str]]] = {}  # network -> (when, host)
        self._cool_until: dict[str, float] = {}
        self._cool_length: dict[str, float] = {}
        self._delays: dict[str, float] = {}  # a network's own delay once it limited us
        self._limited: set[str] = set()  # networks that limited us during this run

    # -- cache -------------------------------------------------------------
    def _cache_path(self, url: str) -> Path:
        host = urlparse(url).netloc or "_"
        digest = hashlib.sha256(url.encode()).hexdigest()[:20]
        d = self.cache_dir / host
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{digest}.json"

    def _read_cache(self, url: str) -> FetchResult | None:
        path = self._cache_path(url)
        if not path.exists():
            return None
        if self.max_age_seconds and time.time() - path.stat().st_mtime > self.max_age_seconds:
            path.unlink(missing_ok=True)  # too old: this run reads the page again
            return None
        try:
            res = FetchResult(**json.loads(path.read_text()), from_cache=True)
        except (ValueError, TypeError):
            return None
        # Caches written before failures stopped being stored may still hold one.
        return res if res.ok else None

    def _write_cache(self, res: FetchResult) -> None:
        """Store successful responses only, so a re-run retries every failure."""
        if not res.ok:
            return
        tmp = self._cache_path(res.url).with_suffix(".part")
        tmp.write_text(
            json.dumps(
                {
                    "url": res.url,
                    "status_code": res.status_code,
                    "body": res.body,
                    "final_url": res.final_url,
                    "error": res.error,
                    "ssl_bypassed": res.ssl_bypassed,
                }
            )
        )
        tmp.replace(self._cache_path(res.url))  # atomic: a reader never sees half a file

    # -- politeness --------------------------------------------------------
    def throttle_key(self, url: str) -> str:
        """The server network of a URL's host (cached), or the host name if unresolvable."""
        host = (urlparse(url).hostname or "").lower()
        with self._lock:
            if host in self._keys:
                return self._keys[host]
        ip = self._resolver(host) if host else None
        key = server_network(ip) if ip else host
        with self._lock:
            return self._keys.setdefault(host, key)

    def _server_lock(self, url: str) -> threading.Lock:
        key = self.throttle_key(url)
        with self._lock:
            return self._locks.setdefault(key, threading.Lock())

    def throttle(self, url: str) -> None:
        """Wait until `delay` seconds have passed since the last request to this server.

        Callers hold the server lock, so requests to one server never overlap.
        """
        key = self.throttle_key(url)
        last = self._last_request.get(key)
        if last is not None:
            wait = self._delays.get(key, self.delay) - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
        self._last_request[key] = time.monotonic()

    def _robots_for(self, url: str) -> urllib.robotparser.RobotFileParser:
        parts = urlparse(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        with self._server_lock(url):
            if origin not in self._robots:
                parser = urllib.robotparser.RobotFileParser()
                self.throttle(url)
                try:
                    status, body, _ = self._transport(
                        origin + "/robots.txt", {"User-Agent": USER_AGENT}, True, self.timeout
                    )
                    parser.parse(body.splitlines() if status == 200 else [])
                except Exception:
                    parser.parse([])  # unreachable robots.txt means allow
                self._robots[origin] = parser
            return self._robots[origin]

    def allowed(self, url: str) -> bool:
        return not self.respect_robots or self._robots_for(url).can_fetch(USER_AGENT, url)

    def robots(self, url: str) -> urllib.robotparser.RobotFileParser | None:
        """The robots.txt rules for a URL's site, or None when robots are not respected."""
        return self._robots_for(url) if self.respect_robots else None

    @contextmanager
    def polite(self, url: str) -> Iterator[None]:
        """Hold the server's turn for a request made outside this class (the browser):
        no other request to that server overlaps it, and the delay applies before it."""
        with self._server_lock(url):
            self.throttle(url)
            yield

    def sitemaps(self, origin: str) -> list[str]:
        """Sitemaps the site declares in robots.txt."""
        return list(self._robots_for(origin + "/").site_maps() or [])

    # -- rate limits (roadmap issue 16) -------------------------------------
    def cooldown_remaining(self, urls: list[str]) -> float:
        """Seconds until every network these URLs live on may be asked again."""
        now = self._clock()
        with self._lock:
            ends = [self._cool_until.get(self._keys.get(_host(u), ""), 0.0) for u in urls]
        return max([0.0, *(end - now for end in ends)])

    def was_rate_limited(self, url: str) -> bool:
        """Whether the network a URL lives on limited us during this run."""
        return self.throttle_key(url) in self._limited

    def _cooling(self, key: str) -> bool:
        with self._lock:
            return self._cool_until.get(key, 0.0) > self._clock()

    def _note_refusal(self, url: str, res: FetchResult) -> bool:
        """Record a refusal; True when it shows the network is limiting us."""
        if res.status_code != 429 and not (res.challenge or res.status_code in REFUSAL_STATUSES):
            return False
        key, host, now = self.throttle_key(url), _host(url), self._clock()
        with self._lock:
            recent = [r for r in self._refusals.get(key, []) if now - r[0] <= RATE_LIMIT_WINDOW]
            recent.append((now, host))
            self._refusals[key] = recent
            limited = res.status_code == 429 or len({h for _, h in recent}) >= RATE_LIMIT_SITES
            if limited:
                length = min(self._cool_length.get(key, COOLDOWN_SECONDS / 2) * 2,
                             MAX_COOLDOWN_SECONDS)  # fmt: skip
                self._cool_length[key] = length
                self._cool_until[key] = now + length
                self._delays[key] = min(self._delays.get(key, self.delay) * 2, MAX_DELAY_SECONDS)
                self._limited.add(key)
        return limited

    # -- public ------------------------------------------------------------
    def get(self, url: str) -> FetchResult:
        cached = self._read_cache(url)
        if cached is not None:
            return cached

        if self._cooling(self.throttle_key(url)):
            return FetchResult(
                url=url,
                status_code=None,
                body="",
                final_url=url,
                error="rate_limited: the server network is cooling down",
                rate_limited=True,
            )
        if not self.allowed(url):
            return FetchResult(
                url=url, status_code=None, body="", final_url=url, error="robots_disallowed"
            )
        with self._server_lock(url):
            res = self._fetch(url)
        if self._note_refusal(url, res):
            res = res.model_copy(update={"rate_limited": True})
        self._write_cache(res)
        return res

    def _fetch(self, url: str) -> FetchResult:
        headers = dict(REQUEST_HEADERS)
        last_error = ""
        for attempt in range(self.retries + 1):
            self.throttle(url)
            try:
                status, body, final = self._transport(url, headers, True, self.timeout)
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"[:200]
                if any(m in str(exc).upper() for m in SSL_MARKERS):
                    break
                self._backoff(attempt)
                continue
            challenge = detect_challenge(status, body)
            res = FetchResult(
                url=url, status_code=status, body=body, final_url=final, challenge=challenge
            )
            # A challenge is never retried: retrying is a way of working around it.
            if status in RETRY_STATUSES and not challenge and attempt < self.retries:
                self._backoff(attempt)
                continue
            return res

        if any(m in last_error.upper() for m in SSL_MARKERS):
            try:
                self.throttle(url)
                status, body, final = self._transport(url, headers, False, self.timeout)
                return FetchResult(
                    url=url,
                    status_code=status,
                    body=body,
                    final_url=final,
                    ssl_bypassed=True,
                    challenge=detect_challenge(status, body),
                )
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"[:200]

        return FetchResult(url=url, status_code=None, body="", final_url=url, error=last_error)

    def _backoff(self, attempt: int) -> None:
        if attempt < self.retries:
            time.sleep(min(self.backoff_seconds * (2**attempt), MAX_BACKOFF_SECONDS))

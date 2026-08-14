"""The only module that touches the network."""
import hashlib
import json
import time
import urllib.robotparser
from pathlib import Path
from urllib.parse import urlparse

from .models import FetchResult

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)
SSL_MARKERS = ("SSL", "CERTIFICATE_VERIFY_FAILED", "HANDSHAKE")

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


def _requests_transport(url, headers, verify, timeout):
    import requests
    r = requests.get(url, headers=headers, verify=verify, timeout=timeout,
                     allow_redirects=True)
    return (r.status_code, r.text, r.url)


class Fetcher:
    """Polite, cached HTTP. Never raises for network conditions."""

    def __init__(self, cache_dir, delay: float = 1.5, timeout: int = 20,
                 retries: int = 2, transport=None, respect_robots: bool = True):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.delay = delay
        self.timeout = timeout
        self.retries = retries
        self.respect_robots = respect_robots
        self._transport = transport or _requests_transport
        self._last_request: dict[str, float] = {}
        self._robots: dict[str, object] = {}

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
        try:
            data = json.loads(path.read_text())
        except ValueError:
            return None
        return FetchResult(**data, from_cache=True)

    def _write_cache(self, res: FetchResult) -> None:
        self._cache_path(res.url).write_text(json.dumps({
            "url": res.url, "status_code": res.status_code, "body": res.body,
            "final_url": res.final_url, "error": res.error,
            "ssl_bypassed": res.ssl_bypassed,
        }))

    # -- politeness --------------------------------------------------------
    def _throttle(self, url: str) -> None:
        host = urlparse(url).netloc
        last = self._last_request.get(host)
        if last is not None:
            wait = self.delay - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
        self._last_request[host] = time.monotonic()

    def _allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        parts = urlparse(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            parser = urllib.robotparser.RobotFileParser()
            try:
                status, body, _ = self._transport(
                    origin + "/robots.txt", {"User-Agent": USER_AGENT}, True, self.timeout
                )
                parser.parse(body.splitlines() if status == 200 else [])
            except Exception:
                parser.parse([])          # unreachable robots.txt means allow
            self._robots[origin] = parser
        return self._robots[origin].can_fetch(USER_AGENT, url)

    # -- public ------------------------------------------------------------
    def get(self, url: str) -> FetchResult:
        cached = self._read_cache(url)
        if cached is not None:
            return cached

        if not self._allowed(url):
            return FetchResult(url=url, status_code=None, body="",
                               final_url=url, error="robots_disallowed")

        headers = dict(REQUEST_HEADERS)
        last_error = ""
        for attempt in range(self.retries + 1):
            self._throttle(url)
            try:
                status, body, final = self._transport(url, headers, True, self.timeout)
                res = FetchResult(url=url, status_code=status, body=body, final_url=final)
                self._write_cache(res)
                return res
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"[:200]
                if any(m in str(exc).upper() for m in SSL_MARKERS):
                    break
                if attempt < self.retries:
                    time.sleep(0.5 * (2 ** attempt))

        if any(m in last_error.upper() for m in SSL_MARKERS):
            try:
                self._throttle(url)
                status, body, final = self._transport(url, headers, False, self.timeout)
                res = FetchResult(url=url, status_code=status, body=body,
                                  final_url=final, ssl_bypassed=True)
                self._write_cache(res)
                return res
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"[:200]

        res = FetchResult(url=url, status_code=None, body="", final_url=url, error=last_error)
        self._write_cache(res)
        return res

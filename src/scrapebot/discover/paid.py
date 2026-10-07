"""A JSON client for the paid search APIs. Every call costs money, so it is:

- cached on disk: the same request is never paid for twice, so a discovery can be
  repeated or resumed for free (delete the cache folder for fresh answers);
- capped: a source stops when its request budget is used up;
- key-safe: keys travel in headers, which are left out of the cache key and the
  cache file, and error text is redacted before it is shown.

Only successful answers are cached, so a failed request is tried again next time. A
cache file is written whole or not at all, and one that cannot be read is asked again.
"""

import hashlib
import json
import logging
import random
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..keys import redact

log = logging.getLogger(__name__)

RETRY_STATUSES = frozenset({408, 429, 500, 502, 503, 504, 529})
MAX_BACKOFF_SECONDS = 60.0

# (method, url, headers, json body, timeout) -> (status, response text). Raises on a
# network failure. Swapped for a fake in tests.
Transport = Callable[[str, str, dict[str, str], bytes | None, float], tuple[int, str]]


class ApiError(Exception):
    """The API refused the request in a way retrying will not fix (bad key, bad request)."""

    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status  # the HTTP status; 0 when the request never got one


class BudgetReached(Exception):
    """The source has sent every request it is allowed in this discovery."""


def read_cached(path: Path) -> Any | None:
    """A cached answer, or None when there is none or the file is broken (then removed)."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log.warning("cache file %s is unreadable; asking again", path.name)
        path.unlink(missing_ok=True)
        return None


def write_cached(path: Path, data: Any) -> None:
    """Write to a temporary file, then rename: an interrupted write leaves no half file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".partial")
    partial.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    partial.replace(path)


def _requests_transport(
    method: str, url: str, headers: dict[str, str], body: bytes | None, timeout: float
) -> tuple[int, str]:
    import requests

    r = requests.request(method, url, headers=headers, data=body, timeout=timeout)
    return r.status_code, r.text


class PaidApi:
    def __init__(
        self,
        name: str,
        cache_dir: Path,
        max_requests: int,
        transport: Transport | None = None,
        retries: int = 3,
        timeout: float = 60.0,
        min_interval: float = 0.25,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.name = name
        self.cache_dir = Path(cache_dir) / name
        self.max_requests = max_requests
        self.retries = retries
        self.timeout = timeout
        self.min_interval = min_interval
        self.sent = 0  # requests that went out: the ones that are billed
        self.cached = 0
        self._transport = transport or _requests_transport
        self._sleep = sleep
        self._last = 0.0

    def post(self, url: str, body: dict[str, Any], headers: dict[str, str]) -> Any:
        payload = json.dumps(body, sort_keys=True).encode()
        digest = hashlib.sha256(f"POST {url} ".encode() + payload).hexdigest()[:32]
        cache_file = self.cache_dir / f"{digest}.json"
        cached = read_cached(cache_file)
        if cached is not None:
            self.cached += 1
            return cached
        data = self._send(url, payload, {"Content-Type": "application/json", **headers})
        write_cached(cache_file, data)
        return data

    def _send(self, url: str, payload: bytes, headers: dict[str, str]) -> Any:
        last, status = "", 0
        for attempt in range(self.retries + 1):
            if self.sent >= self.max_requests:
                raise BudgetReached(f"{self.name}: request cap of {self.max_requests} reached")
            pause = self._last + self.min_interval - time.monotonic()
            if pause > 0:
                self._sleep(pause)
            self.sent += 1
            try:
                status, text = self._transport("POST", url, headers, payload, self.timeout)
            except Exception as exc:  # network trouble: worth another try
                status, text = 0, f"{type(exc).__name__}"
            self._last = time.monotonic()
            if status == 200:
                try:
                    return json.loads(text)
                except ValueError:
                    status, text = 0, "the answer was not JSON"
            last = f"HTTP {status}: {redact(text[:300])}" if status else redact(text)
            if status and status not in RETRY_STATUSES:
                raise ApiError(f"{self.name}: {last}", status)
            if attempt < self.retries:
                delay = min(MAX_BACKOFF_SECONDS, 2 ** (attempt + 1)) + random.uniform(0, 1)
                log.warning("%s: %s; retrying in %.0fs", self.name, last[:120], delay)
                self._sleep(delay)
        raise ApiError(f"{self.name}: {last}", status)

"""Traffic on our own Shopify store, read from Shopify Analytics (ADR 0009).

This has nothing to do with scraping other stores: it reads ShopifyQL through the
Admin GraphQL API with our store's own app credentials, so the team can watch who
visits the store, live.

Shopify meters ShopifyQL at about 1,000 cost points an hour per app, and one refresh
of every table costs about 50. So answers are cached and refreshed on a timer, never
once per browser request, and the slow tables pause when the quota runs low.

What it cannot show: clients that never run JavaScript, such as a scraper reading
`/products.json`. Shopify does not count those as sessions.
"""

import json
import logging
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, SecretStr

from .discover.paid import Transport
from .keys import redact, register

log = logging.getLogger(__name__)

API_VERSION = "2026-07"
TIMEOUT_SECONDS = 20.0
MINUTE_TTL = 30.0  # the per-minute chart; 2 points a query
BREAKDOWN_TTL = 300.0  # chart, totals, cities, pages, sources, devices; about 48 points
MINUTE_RESERVE = 20  # quota points kept back: below this, serve the last answer
BREAKDOWN_RESERVE = 150
TOKEN_MARGIN_SECONDS = 300.0  # renew a client-credentials token this long before it expires

Period = Literal["1h", "24h", "7d"]
CityKind = Literal["data_center", "own_team", "other"]
Problem = Literal["", "quota_low", "unreachable", "auth_failed", "query_failed"]
Grain = Literal["minute", "hour"]

# How finely the chart of each period is drawn: 60 minutes, 25 hours, about 170 hours.
GRAIN: dict[str, Grain] = {"1h": "minute", "24h": "hour", "7d": "hour"}

# Small towns that are mostly cloud data centres (Google, AWS, Microsoft, Meta). A
# session from one is very likely a bot running a real browser. A guess, not a proof.
DATA_CENTER_CITIES = frozenset(
    {
        "council bluffs",
        "ashburn",
        "boardman",
        "the dalles",
        "moncks corner",
        "prineville",
        "quincy",
        "boydton",
        "cheyenne",
        "lenoir",
        "forest city",
        "altoona",
        "papillion",
        "new albany",
        "midlothian",
    }
)
OWN_TEAM_CITIES = frozenset({"denpasar"})  # where the team works (WITA)

ENV_DOMAIN = "SHOPIFY_STORE_DOMAIN"
ENV_CLIENT_ID = "SHOPIFY_CLIENT_ID"
ENV_CLIENT_SECRET = "SHOPIFY_CLIENT_SECRET"
ENV_ADMIN_TOKEN = "SHOPIFY_ADMIN_TOKEN"


class TrafficError(Exception):
    """Shopify could not answer. `code` is one of the `Problem` values or `not_configured`."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class TrafficMinute(BaseModel):
    minute: str  # ISO timestamp, UTC; the last one is the minute in progress
    sessions: int


class TrafficPoint(BaseModel):
    at: str  # ISO timestamp, UTC, start of the minute or hour; the last one is still running
    sessions: int


class TrafficTotals(BaseModel):
    sessions: int
    cart_sessions: int  # sessions that added to cart
    checkout_sessions: int  # sessions that reached checkout


class TrafficCity(BaseModel):
    city: str  # "" when Shopify does not know
    country: str
    sessions: int
    cart_sessions: int
    kind: CityKind


class TrafficPage(BaseModel):
    path: str  # the landing page
    sessions: int
    cart_sessions: int


class TrafficShare(BaseModel):
    name: str  # a referrer source or a device type, as Shopify names it
    sessions: int


class TrafficQuota(BaseModel):
    available: int
    maximum: int
    resets_at: str


class TrafficSnapshot(BaseModel):
    shop: str
    period: Period
    minutes: list[TrafficMinute]  # the last 60 minutes
    minutes_at: str  # when the minute data was read from Shopify
    series: list[TrafficPoint]  # sessions over the chosen period, at `series_grain`
    series_grain: Grain
    totals: TrafficTotals
    data_center_sessions: int  # sessions from DATA_CENTER_CITIES among the top cities
    cities: list[TrafficCity]
    pages: list[TrafficPage]
    sources: list[TrafficShare]
    devices: list[TrafficShare]
    breakdown_at: str  # when the tables were read from Shopify
    quota: TrafficQuota | None
    problem: Problem  # why the data shown may be older than usual; "" when it is not


@dataclass(frozen=True)
class Credentials:
    """Our store's app credentials. A client ID and secret (a Dev Dashboard app) are
    preferred; a fixed Admin API token works too."""

    domain: str = ""
    client_id: str = ""
    client_secret: SecretStr | None = None
    admin_token: SecretStr | None = None

    @property
    def configured(self) -> bool:
        return bool(self.domain and ((self.client_id and self.client_secret) or self.admin_token))


def load_credentials(env_file: str | Path = ".env") -> Credentials:
    """The environment wins over `.env`; `.env` is read without touching `os.environ`."""
    from_file: dict[str, str | None] = {}
    if Path(env_file).exists():
        from dotenv import dotenv_values

        from_file = dict(dotenv_values(env_file))

    def value(name: str) -> str:
        return (os.environ.get(name) or from_file.get(name) or "").strip()

    secret, token = value(ENV_CLIENT_SECRET), value(ENV_ADMIN_TOKEN)
    for s in (secret, token):
        register(s)
    domain = value(ENV_DOMAIN).removeprefix("https://").removeprefix("http://").strip("/")
    return Credentials(
        domain=domain,
        client_id=value(ENV_CLIENT_ID),
        client_secret=SecretStr(secret) if secret else None,
        admin_token=SecretStr(token) if token else None,
    )


def _requests_transport(
    method: str, url: str, headers: dict[str, str], body: bytes | None, timeout: float
) -> tuple[int, str]:
    import requests

    r = requests.request(method, url, headers=headers, data=body, timeout=timeout)
    return r.status_code, r.text


@dataclass
class Table:
    rows: list[dict[str, Any]]
    quota: TrafficQuota | None


class ShopifyAnalytics:
    """Runs ShopifyQL against one store."""

    def __init__(
        self,
        credentials: Credentials,
        transport: Transport | None = None,
        clock: Callable[[], float] = time.time,
    ):
        self.credentials = credentials
        self.transport = transport or _requests_transport
        self.clock = clock
        self._token = ""
        self._token_until = 0.0

    def _post(self, url: str, headers: dict[str, str], payload: dict[str, Any]) -> tuple[int, str]:
        body = json.dumps(payload).encode()
        try:
            return self.transport(
                "POST", url, {"Content-Type": "application/json", **headers}, body, TIMEOUT_SECONDS
            )
        except Exception as exc:  # any network failure: no answer at all
            raise TrafficError(
                "unreachable", redact(f"Shopify tidak bisa dihubungi: {exc}")
            ) from exc

    def _access_token(self) -> str:
        c = self.credentials
        if not (c.client_id and c.client_secret):
            return c.admin_token.get_secret_value() if c.admin_token else ""
        if self._token and self.clock() < self._token_until:
            return self._token
        status, text = self._post(
            f"https://{c.domain}/admin/oauth/access_token",
            {},
            {
                "grant_type": "client_credentials",
                "client_id": c.client_id,
                "client_secret": c.client_secret.get_secret_value(),
            },
        )
        if status != 200:
            raise TrafficError(
                "auth_failed" if status in (400, 401, 403) else "unreachable",
                f"Shopify menolak client ID/secret (HTTP {status}).",
            )
        answer = json.loads(text)
        self._token = str(answer["access_token"])
        register(self._token)
        lifetime = float(answer.get("expires_in") or 86400)
        self._token_until = self.clock() + max(lifetime - TOKEN_MARGIN_SECONDS, 60.0)
        return self._token

    def query(self, shopifyql: str) -> Table:
        url = f"https://{self.credentials.domain}/admin/api/{API_VERSION}/graphql.json"
        payload = {
            "query": "query($q: String!) { shopifyqlQuery(query: $q) "
            "{ tableData { rows } parseErrors } }",
            "variables": {"q": shopifyql},
        }
        for attempt in (1, 2):
            status, text = self._post(
                url, {"X-Shopify-Access-Token": self._access_token()}, payload
            )
            if status == 401 and attempt == 1 and self.credentials.client_id:
                self._token = ""  # revoked or expired early: get a new one once
                continue
            break
        if status in (401, 403):
            raise TrafficError("auth_failed", f"Shopify menolak akses (HTTP {status}).")
        if status == 429:
            raise TrafficError("quota_low", "Shopify membatasi permintaan; coba lagi sebentar.")
        if status != 200:
            raise TrafficError("unreachable", f"Shopify menjawab HTTP {status}.")
        answer = json.loads(text)
        quota = _quota(answer.get("extensions") or {})
        errors = answer.get("errors") or []
        if errors:
            message = redact(str(errors[0].get("message", errors[0])))
            code = "quota_low" if "throttl" in json.dumps(errors).lower() else "query_failed"
            raise TrafficError(code, f"Shopify menolak query: {message}")
        result = (answer.get("data") or {}).get("shopifyqlQuery") or {}
        if result.get("parseErrors"):
            raise TrafficError("query_failed", f"Query ditolak: {result['parseErrors'][0]}")
        rows = (result.get("tableData") or {}).get("rows") or []
        return Table(rows=list(rows), quota=quota)


def _quota(extensions: dict[str, Any]) -> TrafficQuota | None:
    cost = extensions.get("shopifyqlCost")
    if not isinstance(cost, dict):
        return None
    return TrafficQuota(
        available=int(cost.get("currentlyAvailable") or 0),
        maximum=int(cost.get("maximumAvailable") or 0),
        resets_at=str(cost.get("windowResetAt") or ""),
    )


def _int(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def city_kind(city: str) -> CityKind:
    name = city.strip().lower()
    if name in DATA_CENTER_CITIES:
        return "data_center"
    if name in OWN_TEAM_CITIES:
        return "own_team"
    return "other"


def queries(period: Period) -> dict[str, str]:
    since = f"SINCE -{period} UNTIL now"
    series = (
        {"series": f"FROM sessions SHOW sessions TIMESERIES {GRAIN[period]} {since}"}
        if GRAIN[period] != "minute"  # the minute chart already covers the last hour
        else {}
    )
    return {
        **series,
        "totals": "FROM sessions SHOW sessions, sessions_with_cart_additions, "
        f"sessions_that_reached_checkout {since}",
        "cities": "FROM sessions SHOW sessions, sessions_with_cart_additions "
        f"GROUP BY session_city, session_country {since} ORDER BY sessions DESC LIMIT 25",
        "pages": "FROM sessions SHOW sessions, sessions_with_cart_additions "
        f"GROUP BY landing_page_path {since} ORDER BY sessions DESC LIMIT 12",
        "sources": f"FROM sessions SHOW sessions GROUP BY referrer_source {since} "
        "ORDER BY sessions DESC",
        "devices": f"FROM sessions SHOW sessions GROUP BY session_device_type {since} "
        "ORDER BY sessions DESC",
    }


MINUTE_QUERY = "FROM sessions SHOW sessions TIMESERIES minute SINCE -1h UNTIL now"


@dataclass
class Breakdown:
    series: list[TrafficPoint]
    totals: TrafficTotals
    cities: list[TrafficCity]
    pages: list[TrafficPage]
    sources: list[TrafficShare]
    devices: list[TrafficShare]


def parse_minutes(rows: list[dict[str, Any]]) -> list[TrafficMinute]:
    return [
        TrafficMinute(minute=str(r.get("minute") or ""), sessions=_int(r.get("sessions")))
        for r in rows
    ]


def parse_breakdown(tables: dict[str, list[dict[str, Any]]]) -> Breakdown:
    total = (tables["totals"] or [{}])[0]
    return Breakdown(
        series=[
            TrafficPoint(
                at=str(r.get("hour") or r.get("day") or ""), sessions=_int(r.get("sessions"))
            )
            for r in tables.get("series", [])
        ],
        totals=TrafficTotals(
            sessions=_int(total.get("sessions")),
            cart_sessions=_int(total.get("sessions_with_cart_additions")),
            checkout_sessions=_int(total.get("sessions_that_reached_checkout")),
        ),
        cities=[
            TrafficCity(
                city=str(r.get("session_city") or ""),
                country=str(r.get("session_country") or ""),
                sessions=_int(r.get("sessions")),
                cart_sessions=_int(r.get("sessions_with_cart_additions")),
                kind=city_kind(str(r.get("session_city") or "")),
            )
            for r in tables["cities"]
        ],
        pages=[
            TrafficPage(
                path=str(r.get("landing_page_path") or ""),
                sessions=_int(r.get("sessions")),
                cart_sessions=_int(r.get("sessions_with_cart_additions")),
            )
            for r in tables["pages"]
        ],
        sources=[
            TrafficShare(name=str(r.get("referrer_source") or ""), sessions=_int(r.get("sessions")))
            for r in tables["sources"]
        ],
        devices=[
            TrafficShare(
                name=str(r.get("session_device_type") or ""), sessions=_int(r.get("sessions"))
            )
            for r in tables["devices"]
        ],
    )


@dataclass
class _Entry:
    at: float
    data: Any


@dataclass
class TrafficService:
    """Caches Shopify's answers so any number of open pages costs the same quota."""

    env_file: Path = Path(".env")
    transport: Transport | None = None
    clock: Callable[[], float] = time.time
    _analytics: ShopifyAnalytics | None = None
    _cache: dict[str, _Entry] = field(default_factory=lambda: {})
    _quota: TrafficQuota | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _client(self) -> ShopifyAnalytics:
        if self._analytics is None:
            credentials = load_credentials(self.env_file)
            if not credentials.configured:
                raise TrafficError(
                    "not_configured",
                    f"Isi {ENV_DOMAIN} dan {ENV_CLIENT_ID} + {ENV_CLIENT_SECRET} (atau "
                    f"{ENV_ADMIN_TOKEN}) di .env, lalu muat ulang halaman ini.",
                )
            self._analytics = ShopifyAnalytics(credentials, self.transport, self.clock)
        return self._analytics

    def _run(self, shopifyql: str) -> list[dict[str, Any]]:
        table = self._client().query(shopifyql)
        if table.quota:
            self._quota = table.quota
        return table.rows

    def _quota_left(self) -> int | None:
        q = self._quota
        if q is None:
            return None
        try:
            reset = datetime.fromisoformat(q.resets_at).timestamp()
        except ValueError:
            return q.available
        return None if self.clock() >= reset else q.available

    def _get(
        self, key: str, ttl: float, reserve: int, fetch: Callable[[], Any]
    ) -> tuple[_Entry, str]:
        entry = self._cache.get(key)
        now = self.clock()
        if entry and now - entry.at < ttl:
            return entry, ""
        left = self._quota_left()
        if entry and left is not None and left < reserve:
            return entry, "quota_low"
        try:
            fresh = _Entry(now, fetch())
        except TrafficError as exc:
            if entry is None or exc.code == "not_configured":
                raise
            log.warning("traffic: %s; showing the last answer", exc.code)
            return entry, exc.code
        self._cache[key] = fresh
        return fresh, ""

    def snapshot(self, period: Period) -> TrafficSnapshot:
        with self._lock:
            client = self._client()
            minutes, minute_problem = self._get(
                "minutes",
                MINUTE_TTL,
                MINUTE_RESERVE,
                lambda: parse_minutes(self._run(MINUTE_QUERY)),
            )
            breakdown, breakdown_problem = self._get(
                f"breakdown:{period}",
                BREAKDOWN_TTL,
                BREAKDOWN_RESERVE,
                lambda: parse_breakdown({k: self._run(q) for k, q in queries(period).items()}),
            )
        data: Breakdown = breakdown.data
        grain = GRAIN[period]
        series = (
            [TrafficPoint(at=m.minute, sessions=m.sessions) for m in minutes.data]
            if grain == "minute"
            else data.series
        )
        return TrafficSnapshot(
            shop=client.credentials.domain,
            period=period,
            minutes=minutes.data,
            minutes_at=_iso(minutes.at),
            series=series,
            series_grain=grain,
            totals=data.totals,
            data_center_sessions=sum(c.sessions for c in data.cities if c.kind == "data_center"),
            cities=data.cities,
            pages=data.pages,
            sources=data.sources,
            devices=data.devices,
            breakdown_at=_iso(breakdown.at),
            quota=self._quota,
            problem=minute_problem or breakdown_problem,  # type: ignore[arg-type]
        )


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).isoformat(timespec="seconds")

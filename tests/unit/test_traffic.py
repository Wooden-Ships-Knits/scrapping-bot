"""Own-store traffic from Shopify Analytics, offline: Shopify is a FakeSearchApi."""

from datetime import UTC, datetime

import pytest

from scrapebot.traffic import (
    BREAKDOWN_TTL,
    MINUTE_QUERY,
    MINUTE_TTL,
    TrafficError,
    TrafficService,
    city_kind,
    queries,
)
from tests.fakes import FakeSearchApi

SHOP = "example-store.myshopify.com"
TOKEN_URL = f"https://{SHOP}/admin/oauth/access_token"
GRAPHQL_URL = f"https://{SHOP}/admin/api/2026-07/graphql.json"
START = datetime(2026, 10, 8, 4, 0, tzinfo=UTC).timestamp()
ENV = f"SHOPIFY_STORE_DOMAIN={SHOP}\nSHOPIFY_CLIENT_ID=client-1\nSHOPIFY_CLIENT_SECRET=secret-0123456789\n"

TABLES = {
    MINUTE_QUERY: [
        {"minute": "2026-10-08T03:59:00Z", "sessions": "3"},
        {"minute": "2026-10-08T04:00:00Z", "sessions": "1"},
    ],
    "series": [
        {"hour": "2026-10-08T03:00:00Z", "sessions": "40"},
        {"hour": "2026-10-08T04:00:00Z", "sessions": "2"},
    ],
    "totals": [
        {"sessions": "120", "sessions_with_cart_additions": "9", "sessions_that_reached_checkout": "4"}
    ],
    "cities": [
        {"session_city": "Council Bluffs", "session_country": "United States", "sessions": "40",
         "sessions_with_cart_additions": "0"},
        {"session_city": "Denpasar", "session_country": "Indonesia", "sessions": "12",
         "sessions_with_cart_additions": "1"},
        {"session_city": None, "session_country": "United States", "sessions": "5",
         "sessions_with_cart_additions": "0"},
    ],
    "pages": [{"landing_page_path": "/", "sessions": "60", "sessions_with_cart_additions": "5"}],
    "sources": [{"referrer_source": "social", "sessions": "70"}, {"referrer_source": "direct", "sessions": "50"}],
    "devices": [{"session_device_type": "mobile", "sessions": "80"}],
}  # fmt: skip


class Clock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> float:
        return self.now


@pytest.fixture(autouse=True)
def no_shopify_env(monkeypatch):
    for name in (
        "SHOPIFY_STORE_DOMAIN",
        "SHOPIFY_CLIENT_ID",
        "SHOPIFY_CLIENT_SECRET",
        "SHOPIFY_ADMIN_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)


def shopify(available: int = 900, fail: dict | None = None):
    """A fake store. `fail` maps a query to the (status, answer) it gets instead."""
    by_query = {MINUTE_QUERY: TABLES[MINUTE_QUERY]}
    for key, q in queries("24h").items():
        by_query[q] = TABLES[key]

    def graphql(payload):
        q = payload["variables"]["q"]
        if fail and q in fail:
            return fail[q]
        return 200, {
            "data": {"shopifyqlQuery": {"tableData": {"rows": by_query[q]}, "parseErrors": []}},
            "extensions": {
                "shopifyqlCost": {
                    "requestedQueryCost": 10,
                    "maximumAvailable": 1000,
                    "currentlyAvailable": available,
                    "windowResetAt": "2026-10-08T05:00:00+00:00",
                }
            },
        }

    return FakeSearchApi(
        {
            TOKEN_URL: lambda p: (200, {"access_token": "shpat_" + "a" * 32, "expires_in": 86399}),
            GRAPHQL_URL: graphql,
        }
    )


def service(tmp_path, api, env: str = ENV) -> tuple[TrafficService, Clock]:
    env_file = tmp_path / ".env"
    env_file.write_text(env)
    clock = Clock()
    return TrafficService(env_file, api, clock), clock


def graphql_queries(api) -> list[str]:
    return [body["variables"]["q"] for url, _, body in api.calls if url == GRAPHQL_URL]


def test_snapshot_reads_every_table_and_marks_cities(tmp_path):
    api = shopify()
    s, _ = service(tmp_path, api)
    snap = s.snapshot("24h")
    assert snap.shop == SHOP
    assert [m.sessions for m in snap.minutes] == [3, 1]
    assert (snap.totals.sessions, snap.totals.cart_sessions, snap.totals.checkout_sessions) == (
        120,
        9,
        4,
    )
    assert [(c.city, c.kind) for c in snap.cities] == [
        ("Council Bluffs", "data_center"),
        ("Denpasar", "own_team"),
        ("", "other"),
    ]
    assert snap.data_center_sessions == 40
    assert [s.name for s in snap.sources] == ["social", "direct"]
    assert snap.quota is not None
    assert snap.quota.available == 900
    assert snap.problem == ""
    assert snap.series_grain == "hour"
    assert [p.sessions for p in snap.series] == [40, 2]
    # One token, then the minute chart, the hourly chart and the five tables.
    assert [url for url, _, _ in api.calls].count(TOKEN_URL) == 1
    assert len(graphql_queries(api)) == 7


def test_the_token_never_travels_in_a_query_body(tmp_path):
    api = shopify()
    s, _ = service(tmp_path, api)
    s.snapshot("24h")
    for url, headers, body in api.calls:
        if url == GRAPHQL_URL:
            assert headers["X-Shopify-Access-Token"].startswith("shpat_")
            assert "shpat_" not in str(body)
        assert "Accept-Language" not in headers


def test_answers_are_cached_until_they_expire(tmp_path):
    api = shopify()
    s, clock = service(tmp_path, api)
    s.snapshot("24h")
    s.snapshot("24h")
    assert len(graphql_queries(api)) == 7  # the second page view cost nothing

    clock.now += MINUTE_TTL + 1
    s.snapshot("24h")
    assert graphql_queries(api)[7:] == [MINUTE_QUERY]

    clock.now += BREAKDOWN_TTL
    s.snapshot("24h")
    assert len(graphql_queries(api)) == 7 + 1 + 7


def test_low_quota_keeps_the_tables_and_still_moves_the_minute_chart(tmp_path):
    api = shopify(available=100)
    s, clock = service(tmp_path, api)
    first = s.snapshot("24h")
    clock.now += BREAKDOWN_TTL + 1
    snap = s.snapshot("24h")
    assert graphql_queries(api)[7:] == [MINUTE_QUERY]
    assert snap.problem == "quota_low"
    assert snap.breakdown_at == first.breakdown_at


def test_a_failure_shows_the_last_answer_with_the_reason(tmp_path):
    api = shopify()
    s, clock = service(tmp_path, api)
    s.snapshot("24h")
    api.routes[GRAPHQL_URL] = lambda p: (503, "unavailable")
    clock.now += MINUTE_TTL + 1
    snap = s.snapshot("24h")
    assert snap.problem == "unreachable"
    assert [m.sessions for m in snap.minutes] == [3, 1]


def test_a_failure_with_nothing_cached_is_an_error(tmp_path):
    s, _ = service(tmp_path, shopify(fail={MINUTE_QUERY: (403, "forbidden")}))
    with pytest.raises(TrafficError) as err:
        s.snapshot("24h")
    assert err.value.code == "auth_failed"


def test_a_rejected_query_is_query_failed(tmp_path):
    bad = (
        200,
        {"data": {"shopifyqlQuery": {"tableData": None, "parseErrors": ["Column Not Found"]}}},
    )
    s, _ = service(tmp_path, shopify(fail={MINUTE_QUERY: bad}))
    with pytest.raises(TrafficError) as err:
        s.snapshot("24h")
    assert err.value.code == "query_failed"


def test_an_expired_token_is_renewed_once(tmp_path):
    api = shopify()
    answers = iter([(401, "expired")])
    good = api.routes[GRAPHQL_URL]
    api.routes[GRAPHQL_URL] = lambda p: next(answers, None) or good(p)
    s, _ = service(tmp_path, api)
    assert s.snapshot("24h").problem == ""
    assert [url for url, _, _ in api.calls].count(TOKEN_URL) == 2


def test_a_fixed_admin_token_works_without_client_credentials(tmp_path):
    api = shopify()
    s, _ = service(
        tmp_path, api, f"SHOPIFY_STORE_DOMAIN={SHOP}\nSHOPIFY_ADMIN_TOKEN=shpat_{'b' * 32}\n"
    )
    s.snapshot("24h")
    assert TOKEN_URL not in [url for url, _, _ in api.calls]


def test_without_credentials_nothing_is_asked(tmp_path):
    api = shopify()
    s, _ = service(tmp_path, api, "")
    with pytest.raises(TrafficError) as err:
        s.snapshot("24h")
    assert err.value.code == "not_configured"
    assert api.calls == []


def test_the_last_hour_is_charted_per_minute_without_an_extra_query(tmp_path):
    api = shopify()
    by_query = {q: TABLES[k] for k, q in queries("1h").items()}
    good = api.routes[GRAPHQL_URL]

    def graphql(payload):
        q = payload["variables"]["q"]
        if q in by_query:
            rows = by_query[q]
            return 200, {
                "data": {"shopifyqlQuery": {"tableData": {"rows": rows}, "parseErrors": []}}
            }
        return good(payload)

    api.routes[GRAPHQL_URL] = graphql
    s, _ = service(tmp_path, api)
    snap = s.snapshot("1h")
    assert snap.series_grain == "minute"
    assert [p.sessions for p in snap.series] == [3, 1]
    assert not any("TIMESERIES hour" in q for q in graphql_queries(api))


def test_city_kind_ignores_case_and_spaces():
    assert city_kind(" council bluffs ") == "data_center"
    assert city_kind("DENPASAR") == "own_team"
    assert city_kind("Naples") == "other"

"""GET /api/traffic end to end, offline: Shopify is a FakeSearchApi."""

from fastapi.testclient import TestClient

from scrapebot.api import ApiSettings, create_app
from scrapebot.config import RunConfig
from tests.unit.test_traffic import ENV, GRAPHQL_URL, no_shopify_env, shopify  # noqa: F401


def client(tmp_path, env: str, api) -> TestClient:
    env_file = tmp_path / ".env"
    env_file.write_text(env)
    base = RunConfig.model_validate({"output": {"runs_dir": tmp_path / "runs"}})
    return TestClient(create_app(ApiSettings(base=base, env_file=env_file), traffic_transport=api))


def test_traffic_returns_the_snapshot(tmp_path):
    api = shopify()
    with client(tmp_path, ENV, api) as c:
        body = c.get("/api/traffic", params={"period": "24h"}).json()
        assert body["period"] == "24h"
        assert body["totals"]["sessions"] == 120
        assert body["cities"][0]["kind"] == "data_center"
        assert body["data_center_sessions"] == 40
        calls = len(api.calls)
        assert c.get("/api/traffic").status_code == 200
        assert len(api.calls) == calls  # served from the cache


def test_traffic_without_credentials_says_what_to_set(tmp_path):
    with client(tmp_path, "", shopify()) as c:
        r = c.get("/api/traffic")
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "not_configured"
    assert "SHOPIFY_STORE_DOMAIN" in r.json()["detail"]["message"]


def test_traffic_rejects_an_unknown_period(tmp_path):
    with client(tmp_path, ENV, shopify()) as c:
        assert c.get("/api/traffic", params={"period": "1y"}).status_code == 422


def test_shopify_refusing_access_is_a_502(tmp_path):
    api = shopify()
    api.routes[GRAPHQL_URL] = lambda p: (403, "forbidden")
    with client(tmp_path, ENV, api) as c:
        r = c.get("/api/traffic")
    assert r.status_code == 502
    assert r.json()["detail"]["code"] == "auth_failed"

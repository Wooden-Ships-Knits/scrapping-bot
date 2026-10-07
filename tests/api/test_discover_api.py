"""Finding stores from the web API, offline: the agent is a LiteLLM mock response and
the stores are a FakeFetcher. One request finds stores, then starts a test run."""

import json
import time

import litellm
import pytest
from fastapi.testclient import TestClient

from scrapebot.api import ApiSettings, create_app
from scrapebot.config import RunConfig
from tests.api.test_api import RESPONSES, wait_until_finished
from tests.fakes import FakeFetcher

AGENT_ANSWER = json.dumps(
    [
        {"name": "Monkees", "website": "https://monkees.com", "city": "Naples", "state": "FL",
         "country": "US", "note": "sweaters"},
        {"name": "The Boutique", "website": "https://boutique.com", "city": "Naples",
         "state": "FL", "country": "US", "note": "knitwear"},
        {"name": "Third Shop", "website": "https://thirdshop.com", "country": "US"},
        {"name": "No Site", "city": "Naples", "state": "FL", "country": "US"},
    ]
)  # fmt: skip


def make_client(tmp_path, env: str):
    env_file = tmp_path / ".env"
    env_file.write_text(env)
    base = RunConfig.model_validate(
        {"output": {"runs_dir": tmp_path / "runs"}, "fetch": {"cache_dir": tmp_path / "cache"}}
    )
    settings = ApiSettings(
        base=base,
        uploads_dir=tmp_path / "uploads",
        poll_seconds=0.01,
        env_file=env_file,
        discover_dir=tmp_path / "discover",
        discover_cache_dir=tmp_path / "discover-cache",
    )
    calls = []

    def completion(**kwargs):
        calls.append(kwargs)
        return litellm.completion(mock_response=AGENT_ANSWER, **kwargs)

    app = create_app(
        settings,
        fetcher_factory=lambda: FakeFetcher(RESPONSES),
        discover_completion=completion,
    )
    return app, calls


@pytest.fixture
def client(tmp_path):
    app, calls = make_client(tmp_path, "OPENAI_API_KEY=sk-test-0123456789abcdef\n")
    with TestClient(app) as c:
        c.agent_calls = calls  # type: ignore[attr-defined]
        yield c


def wait_for_discovery(client, discovery_id, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found = client.get(f"/api/discover/{discovery_id}").json()
        if found["state"] in ("done", "failed"):
            return found
        time.sleep(0.02)
    raise AssertionError(f"discovery {discovery_id} did not finish")


def discover(client, **body):
    payload = {
        "count": 2,
        "region": "north_america",
        "items": ["knitwear"],
        "writers": ["csv"],
        **body,
    }
    return client.post("/api/discover", json=payload)


def test_options_offer_regions_items_and_say_which_sources_have_a_key(client):
    body = client.get("/api/discover/options").json()
    assert {"north_america", "europe", "asia"} <= set(body["regions"])
    assert body["items"] == ["knitwear", "cashmere_wool", "fall_winter", "spring_summer", "other"]
    assert body["default_items"] == ["knitwear"]
    assert body["agent_model"] == "openai/gpt-5-search-api"
    assert body["sources"] == {
        "google_places": False,
        "web_search": False,
        "social_search": False,
        "ai_agent": True,
    }
    assert "sk-test" not in json.dumps(body)


def test_one_click_finds_stores_then_starts_a_test_run_on_them(client):
    resp = discover(client, items=["knitwear", "fall_winter"], count=2)
    assert resp.status_code == 202
    found = wait_for_discovery(client, resp.json()["discovery_id"])
    assert found["state"] == "done", found["error"]
    assert found["stores_to_visit"] == 2, "the count caps the stores handed to the run"
    agent = next(s for s in found["sources"] if s["name"] == "ai_agent")
    assert agent["status"] == "ok"
    prompt = client.agent_calls[0]["messages"][0]["content"]  # type: ignore[attr-defined]
    assert "sweaters and knitwear, fall and winter collections" in prompt
    assert client.agent_calls[0]["web_search_options"]  # type: ignore[attr-defined]

    run = wait_until_finished(client, found["run_id"])
    assert run["state"] == "done"
    assert run["mode"] == "test"
    assert run["links_in"] == 2
    assert run["config"]["focus"] == {"items": ["knitwear", "fall_winter"], "terms": []}
    rows = client.get(f"/api/runs/{run['run_id']}/rows/products").json()
    [cher] = [r for r in rows["rows"] if r["title"] == "Cher Sweater"]
    assert cher["matched_items"] == ["knitwear"]


def test_a_full_run_follows_a_discovered_test_run(client):
    found = wait_for_discovery(client, discover(client).json()["discovery_id"])
    wait_until_finished(client, found["run_id"])
    full = client.post(f"/api/runs/{found['run_id']}/full")
    assert full.status_code == 202
    assert wait_until_finished(client, full.json()["run_id"])["mode"] == "full"


def test_other_needs_its_words(client):
    resp = discover(client, items=["other"], terms=["  "])
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "terms_required"
    ok = discover(client, items=["other"], terms=["poncho"])
    assert ok.status_code == 202


def test_an_unknown_region_or_item_is_refused_before_paying(client):
    assert discover(client, region="mars").json()["detail"]["code"] == "bad_region"
    assert discover(client, items=["hats"]).json()["detail"]["code"] == "bad_settings"
    assert client.agent_calls == []  # type: ignore[attr-defined]


def test_without_any_search_key_nothing_starts(tmp_path):
    app, calls = make_client(tmp_path, "")
    with TestClient(app) as c:
        resp = discover(c)
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "no_discovery_source"
        assert c.get("/api/discover/options").json()["agent_model"] == ""
    assert calls == []


def test_an_unknown_discovery_is_404(client):
    assert client.get("/api/discover/nope").status_code == 404

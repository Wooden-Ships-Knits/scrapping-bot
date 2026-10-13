"""Deleting from the interface: a run, and the caches. Offline (FakeFetcher)."""

import threading

import pytest
from fastapi.testclient import TestClient

from scrapebot.api import ApiSettings, create_app
from scrapebot.config import RunConfig
from tests.api.test_api import LINKS, RESPONSES, wait_until_finished
from tests.fakes import FakeFetcher


def settings_for(tmp_path) -> ApiSettings:
    base = RunConfig.model_validate(
        {"output": {"runs_dir": tmp_path / "runs"}, "fetch": {"cache_dir": tmp_path / "cache"}}
    )
    return ApiSettings(
        base=base,
        uploads_dir=tmp_path / "uploads",
        poll_seconds=0.01,
        env_file=tmp_path / ".env",
        discover_dir=tmp_path / "discover",
        discover_cache_dir=tmp_path / "cache" / "discover",
        process_dir=tmp_path / "process",
        inputs_dir=tmp_path / "inputs",
    )


@pytest.fixture
def client(tmp_path):
    app = create_app(settings_for(tmp_path), fetcher_factory=lambda: FakeFetcher(RESPONSES))
    with TestClient(app) as c:
        yield c


def start(client):
    body = {"source": {"text": LINKS}, "writers": ["csv"]}
    return wait_until_finished(client, client.post("/api/runs", json=body).json()["run_id"])


def test_a_deleted_run_is_gone_and_its_stores_count_as_not_read(client, tmp_path):
    first, second = start(client), start(client)
    assert second["reused_stores"] == 2, "the second run loaded what the first had read"
    process = tmp_path / "process" / first["run_id"]
    process.mkdir(parents=True)
    (process / "retailer_map.json").write_text("{}")

    assert client.delete(f"/api/runs/{first['run_id']}").json() == {"run_id": first["run_id"]}
    assert not (tmp_path / "runs" / first["run_id"]).exists()
    assert not process.exists(), "what the process step wrote for it goes too"
    assert client.get(f"/api/runs/{first['run_id']}").status_code == 404
    assert [r["run_id"] for r in client.get("/api/runs").json()] == [second["run_id"]]
    assert client.delete(f"/api/runs/{first['run_id']}").status_code == 404

    preview = client.post("/api/preview", json={"source": {"text": LINKS}}).json()
    assert preview["read_before"] == 0, (
        "the first run read them and is gone; the second only loaded them, which is no visit"
    )
    third = start(client)
    assert third["reused_stores"] == 0


def test_a_run_that_is_still_going_cannot_be_deleted(tmp_path):
    gate = threading.Event()

    class GatedFetcher(FakeFetcher):
        def get(self, url):
            gate.wait(5)
            return super().get(url)

    app = create_app(settings_for(tmp_path), fetcher_factory=lambda: GatedFetcher(RESPONSES))
    with TestClient(app) as c:
        body = {"source": {"text": LINKS}, "writers": ["csv"]}
        run_id = c.post("/api/runs", json=body).json()["run_id"]
        refused = c.delete(f"/api/runs/{run_id}")
        assert (refused.status_code, refused.json()["detail"]["code"]) == (409, "run_active")
        assert c.get("/api/cache").json()["busy"] is True
        assert c.delete("/api/cache/all").json()["detail"]["code"] == "busy"
        gate.set()
        wait_until_finished(c, run_id)
        assert c.delete(f"/api/runs/{run_id}").status_code == 200


def test_a_bad_run_id_is_not_a_path(client):
    assert client.delete("/api/runs/..%2F..%2Fetc").status_code == 404


def fill_caches(tmp_path):
    cache = tmp_path / "cache"
    for path, size in (
        ("monkees.com/abc.json", 100),
        ("boutique.com/def.json", 50),
        ("llm/0123.json", 30),
        ("discover/ai_agent/4567.json", 20),
        ("discover/requests/89ab.json", 10),
        ("geocode.json", 7),
    ):
        (cache / path).parent.mkdir(parents=True, exist_ok=True)
        (cache / path).write_bytes(b"x" * size)
    return cache


def usage(body):
    return {k["name"]: (k["files"], k["bytes"]) for k in body["kinds"]}


def test_each_cache_is_counted_and_deleted_on_its_own(client, tmp_path):
    cache = fill_caches(tmp_path)
    before = client.get("/api/cache").json()
    assert usage(before) == {"pages": (2, 150), "search": (2, 30), "llm": (1, 30)}
    assert before["busy"] is False

    after = client.delete("/api/cache/pages").json()
    assert usage(after) == {"pages": (0, 0), "search": (2, 30), "llm": (1, 30)}
    assert not (cache / "monkees.com").exists()
    assert (cache / "geocode.json").exists(), "a file beside the caches is not a cache"

    assert usage(client.delete("/api/cache/llm").json())["llm"] == (0, 0)
    assert (cache / "discover" / "ai_agent" / "4567.json").exists()
    assert client.delete("/api/cache/everything").json()["detail"]["code"] == "cache_not_found"


def test_all_caches_can_be_deleted_at_once_and_runs_stay(client, tmp_path):
    run = start(client)
    fill_caches(tmp_path)
    after = client.delete("/api/cache/all").json()
    assert usage(after) == {"pages": (0, 0), "search": (0, 0), "llm": (0, 0)}
    assert client.get(f"/api/runs/{run['run_id']}").json()["products"] == run["products"]
    preview = client.post("/api/preview", json={"source": {"text": LINKS}}).json()
    assert preview["read_before"] == 2, "what was read is in the run, not in a cache"

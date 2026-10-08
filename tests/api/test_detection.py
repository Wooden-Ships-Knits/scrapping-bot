"""The detection view: which stores block the bot, across runs. Offline (FakeFetcher)."""

import pytest
from fastapi.testclient import TestClient

from scrapebot.api import ApiSettings, create_app
from scrapebot.api.detection import block_method
from scrapebot.config import RunConfig
from scrapebot.fetch import detect_challenge
from scrapebot.models import FetchResult
from tests.api.test_api import LINKS, READABLE, RESPONSES, wait_until_finished
from tests.fakes import FakeFetcher

CHALLENGE = "<html><head><title>Just a moment...</title></head><body>cf-chl</body></html>"


class ChallengeFetcher(FakeFetcher):
    """Recognises challenge pages the way the real fetcher does."""

    def get(self, url: str) -> FetchResult:
        res = super().get(url)
        return res.model_copy(update={"challenge": detect_challenge(res.status_code, res.body)})


@pytest.mark.parametrize(
    ("error", "method"),
    [
        ("challenge page (cloudflare)", "cloudflare"),
        ("challenge page (akamai) in the browser", "akamai"),
        ("HTTP 403", "http_403"),
        ("HTTP 429 in the browser", "http_429"),
        ("", "other"),
    ],
)
def test_block_method_reads_the_recorded_error(error, method):
    assert block_method(error) == method


def run_once(tmp_path, responses, links):
    base = RunConfig.model_validate(
        {"output": {"runs_dir": tmp_path / "runs"}, "fetch": {"cache_dir": tmp_path / "cache"}}
    )
    settings = ApiSettings(base=base, uploads_dir=tmp_path / "uploads", poll_seconds=0.01)
    with TestClient(create_app(settings, fetcher_factory=lambda: ChallengeFetcher(responses))) as c:
        body = {"source": {"text": links}, "writers": ["json"]}
        wait_until_finished(c, c.post("/api/runs", json=body).json()["run_id"])
        return c.get("/api/detection").json()


def test_no_runs_no_blocks(tmp_path):
    settings = ApiSettings(base=RunConfig.model_validate({"output": {"runs_dir": tmp_path}}))
    with TestClient(create_app(settings)) as c:
        body = c.get("/api/detection").json()
    assert (body["visits"], body["blocked"], body["blocked_stores"], body["runs"]) == (0, 0, [], [])


def test_blocks_are_counted_per_run_method_and_store(tmp_path):
    first = run_once(tmp_path, RESPONSES, LINKS)
    assert (first["visits"], first["blocked"], first["stores"], first["stores_blocked"]) == (
        3,
        1,
        3,
        1,
    )
    assert first["by_method"] == {"http_403": 1}
    [store] = first["blocked_stores"]
    assert (store["domain"], store["state"], store["last_method"]) == (
        "blocked.com",
        "always",
        "http_403",
    )

    # A week later: blocked.com lets the bot in, boutique.com now shows a Cloudflare challenge.
    later = {
        **RESPONSES,
        "https://blocked.com": (200, READABLE),
        "https://boutique.com": (403, CHALLENGE),
    }
    second = run_once(tmp_path, later, "https://blocked.com https://boutique.com")
    assert (second["visits"], second["blocked"], second["stores"]) == (5, 2, 3)
    assert second["by_method"] == {"http_403": 1, "cloudflare": 1}
    assert [(r["visits"], r["blocked"]) for r in second["runs"]] == [(2, 1), (3, 1)], "newest first"
    states = {
        s["domain"]: (s["state"], s["visits"], s["blocked"], s["last_method"])
        for s in second["blocked_stores"]
    }
    assert states == {
        "boutique.com": ("sometimes", 2, 1, "cloudflare"),
        "blocked.com": ("recovered", 2, 1, "http_403"),
    }
    assert [s["domain"] for s in second["blocked_stores"]] == ["boutique.com", "blocked.com"]

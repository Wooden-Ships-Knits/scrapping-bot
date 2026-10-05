"""The web API end to end, offline: a FakeFetcher stands in for the network."""

import io
import json
import time
import zipfile

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from scrapebot.api import ApiSettings, create_app
from scrapebot.config import RunConfig
from tests.fakes import FakeFetcher

SHOPIFY_HOME = (
    '<html><script>Shopify.currency = {"active":"USD","rate":"1.0"};</script>cdn.shopify.com</html>'
)
FEED = json.dumps(
    {"products": [{"title": "Cher Sweater", "handle": "cher", "variants": [{"price": "139.00"}]}]}
)
READABLE = "<html><body><p>" + "A boutique in Naples. " * 30 + "</p></body></html>"
RESPONSES = {
    "https://monkees.com": (200, SHOPIFY_HOME),
    "https://monkees.com/products.json?limit=250&page=1": (200, FEED),
    "https://boutique.com": (200, READABLE),
    "https://blocked.com": (403, ""),
}
LINKS = "Cek monkees.com, https://boutique.com dan https://blocked.com. IG: https://instagram.com/x"


@pytest.fixture
def client(tmp_path):
    base = RunConfig.model_validate(
        {"output": {"runs_dir": tmp_path / "runs"}, "fetch": {"cache_dir": tmp_path / "cache"}}
    )
    settings = ApiSettings(base=base, uploads_dir=tmp_path / "uploads", poll_seconds=0.01)
    app = create_app(settings, fetcher_factory=lambda: FakeFetcher(RESPONSES))
    with TestClient(app) as c:
        yield c


def wait_until_finished(client, run_id, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["state"] in ("done", "failed", "interrupted"):
            return run
        time.sleep(0.02)
    raise AssertionError(f"run {run_id} did not finish")


def start(client, **body):
    payload = {"source": {"text": LINKS}, "writers": ["xlsx", "csv"], **body}
    return client.post("/api/runs", json=payload)


def test_options_list_the_writers_and_defaults(client):
    body = client.get("/api/options").json()
    assert "parquet" in body["writers"]
    assert body["default_writers"] == ["xlsx", "csv"]
    assert body["default_test_limit"] == 2


def test_preview_counts_links_before_anything_is_fetched(client):
    body = client.post(
        "/api/preview", json={"source": {"text": LINKS + " monkees.com/shop"}}
    ).json()
    assert body["links"] == 5
    assert body["stores"] == 3
    assert body["duplicates"] == 1
    assert body["skipped"] == {"social_only": 1}
    assert body["tested"] is False


def test_main_scenario_test_run_then_full_run(client):
    """PRD section 4: paste, test the first 2 stores, check, run the rest, download."""
    resp = start(client, test_mode=True, test_limit=2)
    assert resp.status_code == 202
    test_run = wait_until_finished(client, resp.json()["run_id"])
    assert test_run["state"] == "done"
    assert test_run["mode"] == "test"
    assert test_run["stores_done"] == 2
    assert test_run["links_in"] == test_run["processed"] + test_run["skipped"]
    assert test_run["skipped_by_reason"] == {"over_limit": 1, "social_only": 1}
    assert {s["domain"]: s["status"] for s in test_run["stores"]} == {
        "monkees.com": "ok",
        "boutique.com": "no_products",
    }

    preview = client.post("/api/preview", json={"source": {"text": LINKS}}).json()
    assert preview["tested"] is True, "the same links now count as tested"

    full = client.post(f"/api/runs/{test_run['run_id']}/full")
    assert full.status_code == 202
    full_run = wait_until_finished(client, full.json()["run_id"])
    assert full_run["mode"] == "full"
    assert full_run["stores_done"] == 3
    assert full_run["status_counts"] == {"ok": 1, "no_products": 1, "blocked": 1}
    assert full_run["products"] == 1
    assert {d["key"] for d in full_run["downloads"]} >= {
        "report",
        "summary",
        "xlsx",
        "csv",
        "manifest",
    }

    xlsx = client.get(f"/api/runs/{full_run['run_id']}/download/xlsx")
    assert xlsx.status_code == 200
    sheets = load_workbook(io.BytesIO(xlsx.content), read_only=True).sheetnames
    assert sheets == ["runs", "inputs", "stores", "products", "pages", "contacts", "changes"]

    csv_zip = client.get(f"/api/runs/{full_run['run_id']}/download/csv")
    assert csv_zip.status_code == 200
    assert "products.csv" in zipfile.ZipFile(io.BytesIO(csv_zip.content)).namelist()

    listed = client.get("/api/runs").json()
    assert [r["run_id"] for r in listed] == [full_run["run_id"], test_run["run_id"]]


def test_full_run_needs_a_test_run_first(client):
    """PRD OP-01: no full run of an untested list unless the operator skips the test on purpose."""
    resp = start(client, test_mode=False)
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "test_run_required"

    resp = start(client, test_mode=False, skip_test_run=True)
    assert resp.status_code == 202
    assert wait_until_finished(client, resp.json()["run_id"])["mode"] == "full"


def test_upload_then_run_a_spreadsheet(client):
    csv_bytes = b"store_name,website\nMonkees,https://monkees.com\nNo site,\n"
    up = client.post("/api/uploads", files={"file": ("../../evil name.csv", csv_bytes, "text/csv")})
    assert up.status_code == 201
    upload = up.json()
    assert upload["filename"] == "evil_name.csv", "the path is stripped from uploaded names"

    preview = client.post(
        "/api/preview", json={"source": {"upload_id": upload["upload_id"]}}
    ).json()
    assert (preview["links"], preview["stores"]) == (2, 1)

    resp = client.post(
        "/api/runs",
        json={"source": {"upload_id": upload["upload_id"]}, "writers": ["json"], "test_limit": 1},
    )
    run = wait_until_finished(client, resp.json()["run_id"])
    assert run["source_kind"] == "file"
    assert run["source_name"] == "evil_name.csv"
    assert run["stores_done"] == 1


def test_unsupported_upload_is_refused(client):
    resp = client.post("/api/uploads", files={"file": ("links.pdf", b"x", "application/pdf")})
    assert resp.status_code == 415


def test_bad_input_and_settings_are_explained(client):
    assert (
        client.post("/api/preview", json={"source": {"text": "no links here"}}).json()["links"] == 0
    )
    resp = start(client, source={"text": "no links here"})
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "bad_input"
    resp = start(client, writers=["pdf"])
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "bad_settings"
    resp = client.post("/api/preview", json={"source": {"upload_id": "0" * 32}})
    assert resp.status_code == 404


@pytest.mark.parametrize("run_id", ["../../etc", "20261005T000000000Z-zzzzzz", "x"])
def test_unknown_or_malformed_run_ids_are_404(client, run_id):
    assert client.get(f"/api/runs/{run_id}").status_code == 404


def test_download_keys_are_a_fixed_list(client):
    run = wait_until_finished(client, start(client).json()["run_id"])
    assert client.get(f"/api/runs/{run['run_id']}/download/..%2Fconfig.json").status_code == 404
    assert client.get(f"/api/runs/{run['run_id']}/download/parquet").status_code == 404, (
        "not chosen"
    )


def test_events_stream_the_run_until_it_ends(client):
    run_id = start(client).json()["run_id"]
    with client.stream("GET", f"/api/runs/{run_id}/events") as resp:
        assert resp.headers["content-type"].startswith("text/event-stream")
        states = [
            json.loads(line.removeprefix("data: "))["state"]
            for line in resp.iter_lines()
            if line.startswith("data: ")
        ]
    assert states[-1] == "done"


def test_a_run_survives_a_server_restart(client, tmp_path):
    run = wait_until_finished(client, start(client).json()["run_id"])
    base = RunConfig.model_validate({"output": {"runs_dir": tmp_path / "runs"}})
    with TestClient(create_app(ApiSettings(base=base))) as fresh:
        again = fresh.get(f"/api/runs/{run['run_id']}").json()
    assert again["state"] == "done"
    assert again["stores_done"] == run["stores_done"]


def test_rows_preview_pages_through_a_table_without_raw_objects(client):
    run = wait_until_finished(
        client, start(client, test_mode=False, skip_test_run=True).json()["run_id"]
    )
    body = client.get(f"/api/runs/{run['run_id']}/rows/products?limit=1").json()
    assert body["total"] == 1
    assert body["rows"][0]["title"] == "Cher Sweater"
    assert "raw" not in body["columns"], "the bulky source object is left out of the preview"
    stores = client.get(f"/api/runs/{run['run_id']}/rows/stores?offset=1&limit=1").json()
    assert (stores["total"], len(stores["rows"]), stores["offset"]) == (3, 1, 1)
    assert client.get(f"/api/runs/{run['run_id']}/rows/runs").status_code == 404


def test_rows_preview_shortens_long_text(client, tmp_path):
    long_page = "<html><body><p>" + "word " * 2000 + "</p></body></html>"
    settings = ApiSettings(
        base=RunConfig.model_validate({"output": {"runs_dir": tmp_path / "long"}}),
        poll_seconds=0.01,
    )
    app = create_app(
        settings, fetcher_factory=lambda: FakeFetcher({"https://long.com": (200, long_page)})
    )
    with TestClient(app) as c:
        run_id = c.post(
            "/api/runs", json={"source": {"text": "long.com"}, "writers": ["json"]}
        ).json()["run_id"]
        wait_until_finished(c, run_id)
        body = c.get(f"/api/runs/{run_id}/rows/pages").json()
    assert body["truncated_fields"] is True
    assert body["rows"][0]["text"].endswith("…")


def test_run_detail_carries_params_and_the_equivalent_cli(client):
    run = wait_until_finished(client, start(client).json()["run_id"])
    assert run["cli"] == "uv run scrapebot run links.txt --limit 2 -f xlsx,csv"
    assert run["config"]["input"]["text"].endswith("characters of pasted links"), (
        "pasted text is summarised"
    )


def test_overview_totals(client):
    wait_until_finished(client, start(client).json()["run_id"])
    body = client.get("/api/overview").json()
    assert (body["runs"], body["runs_done"], body["stores"], body["products"]) == (1, 1, 2, 1)
    assert body["last_run"]["mode"] == "test"

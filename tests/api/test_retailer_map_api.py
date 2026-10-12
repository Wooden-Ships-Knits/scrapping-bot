"""The retailer map view: serves the newest file the process wrote. Offline, made-up stores."""

import json

from fastapi.testclient import TestClient

from scrapebot.api import ApiSettings, create_app
from scrapebot.api.retailer_map import FILE


def a_map(run_id: str) -> dict:
    return {
        "run_id": run_id,
        "stores": 10,
        "readable": 4,
        "radius_miles": 15.0,
        "watched": [{"key": "rails", "brand": "Rails", "stores": 2}],
        "watched_stores": 2,
        "watched_customers": 1,
        "watched_not_ours": 1,
        "watched_email": 1,
        "watched_territory": {"open": 1},
        "located": 1,
        "opportunities": [
            {
                "domain": "example-boutique.com",
                "name": None,
                "city": "Naples",
                "state": "FL",
                "score": 48.0,
                "knit": 120,
                "price": 139.5,
                "currency": "USD",
                "miles": 41.2,
                "territory": "open",
                "email": True,
                "watched": ["rails"],
                "relevant": ["Example Knits"],
            }
        ],
        "brands": [
            {
                "key": "rails",
                "brand": "Rails",
                "kind": "marker",
                "watched": True,
                "stores": 2,
                "shared": 1,
                "not_ours": 1,
                "open": 1,
                "knit_share": 0.12,
                "price": None,
                "rank": 0.6,
                "full": False,
            }
        ],
        "regions": [{"state": "FL", "opportunities": 1, "open_territory": 1, "stockists": 3}],
        "survey": [{"brand": "Rails", "locator": "Own page", "status": "own", "locations": None}],
        "locator": None,
    }


def client(tmp_path) -> TestClient:
    return TestClient(create_app(ApiSettings(process_dir=tmp_path)))


def write(tmp_path, run_id: str, body: dict) -> None:
    (tmp_path / run_id).mkdir()
    (tmp_path / run_id / FILE).write_text(json.dumps(body))


def test_nothing_processed_yet_says_how_to_start(tmp_path):
    with client(tmp_path) as c:
        resp = c.get("/api/retailer-map")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "no_process_output"
    assert "process/run_all.py" in resp.json()["detail"]["message"]


def test_serves_the_newest_processed_run_unchanged(tmp_path):
    old, new = "20261005T085253Z-56162b", "20261009T073717823Z-e4d60c"
    write(tmp_path, old, a_map(old))
    write(tmp_path, new, a_map(new))
    (tmp_path / "20261010T000000Z-aaaaaa").mkdir()  # processed halfway: no file yet
    with client(tmp_path) as c:
        resp = c.get("/api/retailer-map")
    assert resp.status_code == 200
    assert resp.json() == a_map(new)


def test_a_file_from_an_older_shape_is_an_error_not_a_blank_page(tmp_path):
    body = a_map("20261009T073717823Z-e4d60c")
    del body["opportunities"]
    write(tmp_path, body["run_id"], body)
    with client(tmp_path) as c:
        resp = c.get("/api/retailer-map")
    assert resp.status_code == 500
    assert resp.json()["detail"]["code"] == "process_output_invalid"

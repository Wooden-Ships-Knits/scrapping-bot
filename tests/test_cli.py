import csv
import json

from scrapebot.cli import run
from scrapebot.models import FetchResult


class FakeFetcher:
    def __init__(self, responses):
        self.responses = responses

    def get(self, url):
        entry = self.responses.get(url)
        if entry is None:
            return FetchResult(url=url, status_code=404, body="", final_url=url)
        status, body = entry
        return FetchResult(url=url, status_code=status, body=body, final_url=url)


def test_run_writes_csv_json_and_report(tmp_path):
    src = tmp_path / "in.csv"
    src.write_text(
        "store_name,website,address\n"
        "Monkees,https://monkees.com,Naples FL\n"
        "No Site,,Naples FL\n"
        "Insta Only,https://www.instagram.com/x/,Naples FL\n"
    )
    out_dir = tmp_path / "out"
    raw_dir = tmp_path / "raw"

    fetcher = FakeFetcher({
        "https://monkees.com": (200, "<html>cdn.shopify.com</html>"),
        "https://monkees.com/products.json?limit=250&page=1": (200, json.dumps({"products": [
            {"title": "Cher Sweater in Eggnog", "variants": [{"price": "139.00"}]},
            {"title": "Leather Bag", "variants": [{"price": "450.00"}]},
        ]})),
        "https://monkees.com/products.json?limit=250&page=2": (200, json.dumps({"products": []})),
    })

    run(str(src), str(out_dir), str(raw_dir), fetcher=fetcher)

    rows = list(csv.DictReader(open(out_dir / "in-enriched.csv")))
    assert len(rows) == 3, "every input row appears in the output, including skipped ones"

    by_name = {r["store_name"]: r for r in rows}
    assert by_name["Monkees"]["knit_count"] == "1"
    assert by_name["Monkees"]["knit_examples"] == "Cher Sweater in Eggnog"
    assert by_name["No Site"]["scrape_status"] == "no_website"
    assert by_name["Insta Only"]["scrape_status"] == "social_only"

    raw = json.loads((raw_dir / "monkees.com.json").read_text())
    assert len(raw["products"]) == 2
    assert raw["domain"] == "monkees.com"

    report = (out_dir / "run-report.md").read_text()
    assert "no_website" in report and "Total input rows" in report


def test_run_never_aborts_when_one_site_fails(tmp_path):
    src = tmp_path / "in.csv"
    src.write_text(
        "store_name,website\n"
        "Broken,https://broken.com\n"
        "Working,https://working.com\n"
    )
    fetcher = FakeFetcher({
        "https://broken.com": (403, ""),
        "https://working.com": (200, "<html><p>Hello</p></html>"),
    })
    run(str(src), str(tmp_path / "out"), str(tmp_path / "raw"), fetcher=fetcher)

    rows = list(csv.DictReader(open(tmp_path / "out" / "in-enriched.csv")))
    statuses = {r["store_name"]: r["scrape_status"] for r in rows}
    assert statuses["Broken"] == "blocked"
    assert statuses["Working"] in ("ok", "js_required")

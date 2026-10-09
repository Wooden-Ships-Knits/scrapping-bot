import csv
import json
import threading
import time
from datetime import UTC, datetime

import pytest

from scrapebot import pipeline
from scrapebot.config import RunConfig
from scrapebot.inputs.readers import InputError
from scrapebot.pipeline import execute, new_run_id, prepare, resume, run
from scrapebot.tables import FINAL_TABLES, TABLES
from tests.fakes import FakeFetcher

SHOPIFY_HOME = (
    '<html><script>Shopify.currency = {"active":"USD","rate":"1.0"};</script>cdn.shopify.com</html>'
)
FEED_PAGE_1 = json.dumps(
    {
        "products": [
            {
                "title": "Cher Sweater in Eggnog",
                "handle": "cher",
                "variants": [{"price": "139.00"}],
            },
            {"title": "Leather Bag", "handle": "bag", "variants": [{"price": "450.00"}]},
        ]
    }
)
READABLE = "<html><body><p>" + "A boutique in Naples. " * 30 + "</p></body></html>"


def config_for(tmp_path, csv_text: str, **overrides) -> RunConfig:
    src = tmp_path / "in.csv"
    src.write_text(csv_text)
    data = {
        "input": {"source": src},
        "output": {"runs_dir": tmp_path / "runs", "writers": ["csv", "xlsx", "parquet"]},
        "fetch": {"cache_dir": tmp_path / "cache"},
    }
    data.update(overrides)
    return RunConfig.model_validate(data)


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def test_run_writes_tables_exports_summary_and_report(tmp_path):
    cfg = config_for(
        tmp_path,
        "store_name,website,address\n"
        "Monkees,https://monkees.com,Naples FL\n"
        "No Site,,Naples FL\n"
        "Insta Only,https://www.instagram.com/x/,Naples FL\n",
    )
    fetcher = FakeFetcher(
        {
            "https://monkees.com": (200, SHOPIFY_HOME),
            "https://monkees.com/products.json?limit=250&page=1": (200, FEED_PAGE_1),
        }
    )
    result = run(cfg, fetcher=fetcher)

    assert (result.links_in, result.processed, result.skipped) == (3, 1, 2)
    tables = result.root / "tables"
    assert sorted(p.stem for p in tables.glob("*.jsonl")) == sorted([*TABLES, *FINAL_TABLES])

    inputs = read_jsonl(tables / "inputs.jsonl")
    assert [i["status"] for i in inputs] == ["processed", "no_website", "social_only"]
    assert inputs[0]["meta"] == {
        "store_name": "Monkees",
        "website": "https://monkees.com",
        "address": "Naples FL",
    }

    [store] = read_jsonl(tables / "stores.jsonl")
    assert (store["status"], store["currency"], store["product_count"]) == ("ok", "USD", 2)
    products = read_jsonl(tables / "products.jsonl")
    assert {p["currency"] for p in products} == {"USD"}
    assert products[0]["url"] == "https://monkees.com/products/cher"
    assert all(p["run_id"] == result.run_id for p in products)

    for fmt in ("csv", "xlsx", "parquet"):
        assert result.exports[fmt], fmt
        assert all(p.exists() for p in result.exports[fmt])

    with result.summary_path.open() as fh:
        summary = {r["store_name"]: r for r in csv.DictReader(fh)}
    assert summary["Monkees"]["knit_count"] == "1"
    assert summary["Monkees"]["knit_examples"] == "Cher Sweater in Eggnog"
    assert summary["No Site"]["scrape_status"] == "no_website"
    assert summary["Insta Only"]["scrape_status"] == "social_only"

    report = result.report_path.read_text()
    assert "Links in: 3 = processed 1 + skipped 2** (balanced)" in report
    manifest = json.loads((result.root / "manifest.json").read_text())
    assert manifest["counts"]["products"] == 2
    assert manifest["config"]["output"]["writers"] == ["csv", "xlsx", "parquet"]


def test_run_never_aborts_when_one_site_fails(tmp_path):
    cfg = config_for(
        tmp_path, "store_name,website\nBroken,https://broken.com\nWorking,https://working.com\n"
    )
    fetcher = FakeFetcher({"https://broken.com": (403, ""), "https://working.com": (200, READABLE)})
    result = run(cfg, fetcher=fetcher)
    stores = {s["domain"]: s["status"] for s in read_jsonl(result.root / "tables" / "stores.jsonl")}
    assert stores == {"broken.com": "blocked", "working.com": "no_products"}
    assert "broken.com: blocked (HTTP 403)" in result.report_path.read_text()


def test_pages_table_keeps_the_full_page_text(tmp_path):
    """Issue 6: later analysis must see whole pages, not the first 5,000 characters."""
    body = "<html><body><p>" + "word " * 4000 + "END-MARKER</p></body></html>"
    cfg = config_for(tmp_path, "website\nhttps://long.com\n")
    result = run(cfg, fetcher=FakeFetcher({"https://long.com": (200, body)}))
    [page] = read_jsonl(result.root / "tables" / "pages.jsonl")
    assert page["text"].endswith("END-MARKER")
    assert "html" not in page, "HTML is never stored"


def test_limit_visits_only_the_first_stores(tmp_path):
    """PRD OP-01: test mode runs the first N stores end to end."""
    cfg = config_for(tmp_path, "website\nhttps://a.com\nhttps://b.com\nhttps://c.com\n", limit=1)
    fetcher = FakeFetcher({"https://a.com": (200, READABLE)})
    result = run(cfg, fetcher=fetcher)
    assert all(url.startswith("https://a.com") for url in fetcher.calls)
    assert result.stores == 1
    assert (result.links_in, result.processed, result.skipped) == (3, 1, 2)
    report = result.report_path.read_text()
    assert "test mode, first 1 stores" in report
    assert "`over_limit` | 2" in report


def test_too_many_links_are_refused_before_anything_is_fetched(tmp_path):
    """PRD IN-07."""
    cfg = config_for(tmp_path, "website\nhttps://a.com\nhttps://b.com\n", input={"max_links": 1})
    cfg.input.source = tmp_path / "in.csv"
    fetcher = FakeFetcher({})
    with pytest.raises(InputError, match="limit per run is 1"):
        run(cfg, fetcher=fetcher)
    assert fetcher.calls == []
    assert not (tmp_path / "runs").exists()


def test_pasted_text_input(tmp_path):
    cfg = RunConfig.model_validate(
        {
            "input": {"text": "Please check a.com and https://b.com/products/x, thanks"},
            "output": {"runs_dir": tmp_path / "runs", "writers": ["json"]},
        }
    )
    result = run(cfg, fetcher=FakeFetcher({"https://a.com": (200, READABLE)}))
    inputs = read_jsonl(result.root / "tables" / "inputs.jsonl")
    assert [(i["domain"], i["is_deep_link"]) for i in inputs] == [("a.com", False), ("b.com", True)]
    with result.summary_path.open() as fh:
        assert [r["link"] for r in csv.DictReader(fh)] == ["a.com", "https://b.com/products/x"]


def test_each_run_gets_its_own_folder(tmp_path):
    cfg = config_for(
        tmp_path,
        "website\nhttps://a.com\n",
        output={"runs_dir": tmp_path / "runs", "writers": ["json"]},
    )
    first = run(cfg, fetcher=FakeFetcher({}))
    second = run(cfg, fetcher=FakeFetcher({}))
    assert first.root != second.root
    assert first.root.exists()
    assert second.root.exists()


def test_run_ids_sort_by_start_time_to_the_millisecond():
    first = new_run_id(datetime(2026, 10, 5, 8, 52, 53, 1000, tzinfo=UTC))
    second = new_run_id(datetime(2026, 10, 5, 8, 52, 53, 2000, tzinfo=UTC))
    assert first.startswith("20261005T085253001Z-")
    assert first < second


def test_stores_are_visited_in_parallel(tmp_path):
    """PRD AQ-11: several stores at once."""
    active, peak = [0], [0]
    lock = threading.Lock()

    class SlowFetcher(FakeFetcher):
        def get(self, url):
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            time.sleep(0.05)
            with lock:
                active[0] -= 1
            return super().get(url)

    links = "\n".join(f"https://s{i}.com" for i in range(6))
    cfg = config_for(
        tmp_path, f"website\n{links}\n", fetch={"cache_dir": tmp_path / "c", "concurrency": 3}
    )
    result = run(cfg, fetcher=SlowFetcher({}))
    assert result.stores == 6
    assert peak[0] == 3


def test_one_store_crashing_does_not_stop_the_run(tmp_path, monkeypatch):
    real = pipeline.acquire

    def flaky(target, fetcher, **kwargs):
        if target.domain == "bad.com":
            raise RuntimeError("parser bug")
        return real(target, fetcher, **kwargs)

    monkeypatch.setattr(pipeline, "acquire", flaky)
    cfg = config_for(tmp_path, "website\nhttps://bad.com\nhttps://good.com\n")
    result = run(cfg, fetcher=FakeFetcher({"https://good.com": (200, READABLE)}))
    stores = {s["domain"]: s for s in read_jsonl(result.root / "tables" / "stores.jsonl")}
    assert stores["bad.com"]["status"] == "error"
    assert "internal error: RuntimeError: parser bug" in stores["bad.com"]["error"]
    assert stores["good.com"]["status"] == "no_products"


def test_a_stopped_run_resumes_without_visiting_finished_stores(tmp_path):
    """PRD OP-03: stop in the middle, resume, and get the same data."""
    links = "\n".join(f"https://s{i}.com" for i in range(5))
    cfg = config_for(
        tmp_path, f"website\n{links}\n", fetch={"cache_dir": tmp_path / "c", "concurrency": 1}
    )
    responses = {f"https://s{i}.com": (200, READABLE) for i in range(5)}
    stop = threading.Event()

    def stop_after_two(n, total, got):
        if n == 2:
            stop.set()

    first = execute(
        prepare(cfg), fetcher=FakeFetcher(responses), progress=stop_after_two, stop=stop
    )
    assert first.stopped is True
    assert first.stores == 2
    assert (first.root / "stopped.json").exists()
    assert not (first.root / "report.md").exists()

    second_fetcher = FakeFetcher(responses)
    done = execute(resume(first.root), fetcher=second_fetcher)
    assert done.stopped is False
    assert done.run_id == first.run_id
    visited = {url for url in second_fetcher.calls if url.count("/") == 2}
    assert visited == {"https://s2.com", "https://s3.com", "https://s4.com"}
    stores = read_jsonl(done.root / "tables" / "stores.jsonl")
    assert sorted(s["domain"] for s in stores) == [f"s{i}.com" for i in range(5)]
    with done.summary_path.open() as fh:
        assert len(list(csv.DictReader(fh))) == 5
    assert "balanced" in done.report_path.read_text()


def test_resume_refuses_a_changed_input(tmp_path):
    cfg = config_for(
        tmp_path,
        "website\nhttps://a.com\nhttps://b.com\n",
        fetch={"cache_dir": tmp_path / "c", "concurrency": 1},
    )
    stop = threading.Event()
    stop.set()
    first = execute(prepare(cfg), fetcher=FakeFetcher({}), stop=stop)
    (tmp_path / "in.csv").write_text("website\nhttps://other.com\n")
    with pytest.raises(InputError, match="input changed"):
        resume(first.root)


def test_products_are_flagged_knitwear_and_none_are_dropped(tmp_path):
    cfg = config_for(tmp_path, "website\nhttps://monkees.com\n")
    fetcher = FakeFetcher(
        {
            "https://monkees.com": (200, SHOPIFY_HOME),
            "https://monkees.com/products.json?limit=250&page=1": (200, FEED_PAGE_1),
        }
    )
    result = run(cfg, fetcher=fetcher)
    tables = result.root / "tables"
    products = {p["title"]: p for p in read_jsonl(tables / "products.jsonl")}
    assert products["Cher Sweater in Eggnog"]["is_knitwear"] is True
    assert products["Leather Bag"]["is_knitwear"] is False, "kept, only flagged"
    [store] = read_jsonl(tables / "stores.jsonl")
    assert (store["product_count"], store["knit_count"]) == (2, 1)

import csv
import json

import pytest

from scrapebot.config import RunConfig
from scrapebot.inputs.readers import InputError
from scrapebot.pipeline import run
from scrapebot.tables import TABLES
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
    assert sorted(p.stem for p in tables.glob("*.jsonl")) == sorted(TABLES)

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

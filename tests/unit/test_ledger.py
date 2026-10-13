"""Stores read recently are loaded from that run, not visited again (ADR 0013). Offline."""

import json
import sqlite3
from datetime import UTC, datetime, timedelta

from pydantic import SecretStr

from scrapebot.ledger import LEDGER_FILE, Ledger, Visit, is_unfinished
from scrapebot.pipeline import prepare, run
from tests.fakes import FakeFetcher
from tests.unit.test_pipeline import FEED_PAGE_1, READABLE, SHOPIFY_HOME, config_for, read_jsonl

LINKS = "website\nhttps://monkees.com\nhttps://boutique.com\nhttps://blocked.com\n"


def responses():
    return {
        "https://monkees.com": (200, SHOPIFY_HOME),
        "https://monkees.com/products.json?limit=250&page=1": (200, FEED_PAGE_1),
        "https://boutique.com": (200, READABLE),
        "https://blocked.com": (403, ""),
    }


def tables(result, name):
    return read_jsonl(result.root / "tables" / f"{name}.jsonl")


def test_a_store_read_recently_is_loaded_and_only_the_rest_are_visited(tmp_path):
    first = run(config_for(tmp_path, LINKS), fetcher=FakeFetcher(responses()))
    fetcher = FakeFetcher(responses())
    second = run(
        config_for(tmp_path, LINKS, focus={"items": ["other"], "terms": ["bag"]}), fetcher=fetcher
    )

    assert {u.split("/")[2] for u in fetcher.calls} == {"blocked.com"}, (
        "the two stores that were read are not asked again; the blocked one is tried again"
    )
    stores = {s["domain"]: s for s in tables(second, "stores")}
    old = {s["domain"]: s for s in tables(first, "stores")}
    assert {d: s["reused_from"] for d, s in stores.items()} == {
        "monkees.com": first.run_id,
        "boutique.com": first.run_id,
        "blocked.com": "",
    }
    assert stores["monkees.com"]["fetched_at"] == old["monkees.com"]["fetched_at"]
    assert stores["monkees.com"]["run_id"] == second.run_id
    assert (stores["monkees.com"]["product_count"], stores["monkees.com"]["focus_count"]) == (2, 1)

    products = tables(second, "products")
    assert [p["title"] for p in products] == ["Cher Sweater in Eggnog", "Leather Bag"]
    assert [p["matched_items"] for p in products] == [[], ["other"]], "this run's own focus"
    assert {p["run_id"] for p in products} == {second.run_id}
    assert {p["raw"]["handle"] for p in products} == {"cher", "bag"}, "the source object is kept"
    assert len(tables(second, "pages")) == len(tables(first, "pages"))
    assert (second.root / "report.md").exists()
    summary = second.summary_path.read_text().splitlines()
    assert summary == first.summary_path.read_text().splitlines(), "the same view of each store"


def test_rescrape_visits_every_store(tmp_path):
    run(config_for(tmp_path, LINKS), fetcher=FakeFetcher(responses()))
    fetcher = FakeFetcher(responses())
    cfg = config_for(tmp_path, LINKS)
    cfg.fetch.reuse_days = 0
    again = run(cfg, fetcher=fetcher)
    assert {u.split("/")[2] for u in fetcher.calls} == {
        "monkees.com",
        "boutique.com",
        "blocked.com",
    }
    assert all(not s["reused_from"] for s in tables(again, "stores"))


def test_a_visit_older_than_the_window_or_never_read_is_not_reused(tmp_path):
    ledger = Ledger(tmp_path)
    now = datetime(2026, 10, 13, tzinfo=UTC)

    def visit(domain, days_ago, status="ok", run_id="R1"):
        (tmp_path / run_id / "tables").mkdir(parents=True, exist_ok=True)
        (tmp_path / run_id / "tables" / "stores.jsonl").touch()
        moment = (now - timedelta(days=days_ago)).isoformat(timespec="seconds")
        return Visit(domain, run_id, moment, status, 3)

    ledger.record(
        [
            visit("fresh.com", 29),
            visit("stale.com", 31),
            visit("blocked.com", 1, status="blocked"),
            visit("empty.com", 2, status="no_products"),
            visit("twice.com", 20, run_id="R1"),
            visit("twice.com", 5, run_id="R2"),
        ]
    )
    ledger.record([Visit("gone.com", "R9", now.isoformat(timespec="seconds"), "ok", 1)])
    domains = [
        "fresh.com",
        "stale.com",
        "blocked.com",
        "empty.com",
        "twice.com",
        "gone.com",
        "new.com",
    ]
    found = ledger.recent(domains, 30, now)
    assert {d: v.run_id for d, v in found.items()} == {
        "fresh.com": "R1",
        "empty.com": "R1",
        "twice.com": "R2",
    }, "gone.com's run folder was deleted: nothing to load"
    assert ledger.recent(domains, 0, now) == {}


def test_the_ledger_is_rebuilt_from_the_run_folders_when_it_is_missing(tmp_path):
    first = run(config_for(tmp_path, LINKS), fetcher=FakeFetcher(responses()))
    second = run(config_for(tmp_path, LINKS), fetcher=FakeFetcher(responses()))
    runs_dir = tmp_path / "runs"
    (runs_dir / LEDGER_FILE).unlink()

    rebuilt = Ledger(runs_dir)
    stores = ["monkees.com", "boutique.com", "blocked.com"]
    found = rebuilt.recent(stores, 30, with_unfinished=True)
    assert {d: v.run_id for d, v in found.items()} == {
        "monkees.com": first.run_id,
        "boutique.com": first.run_id,
    }, "the second run loaded them: that is not a visit"
    assert rebuilt.recent(stores, 30) == {}, (
        "these runs had no LLM key: what they left open is not done for a run that has one"
    )
    assert json.loads((second.root / "config.json").read_text())["fetch"]["reuse_days"] == 30


def test_a_store_whose_rows_are_gone_is_visited(tmp_path):
    first = run(config_for(tmp_path, LINKS), fetcher=FakeFetcher(responses()))
    products = first.root / "tables" / "stores.jsonl"
    products.write_text("")  # the run was emptied after the ledger noted it
    fetcher = FakeFetcher(responses())
    again = run(config_for(tmp_path, LINKS), fetcher=fetcher)
    assert "https://monkees.com" in fetcher.calls
    assert all(not s["reused_from"] for s in tables(again, "stores"))


def test_a_store_read_while_the_llm_stage_could_not_work_is_visited_once_it_can(tmp_path):
    """On 2026-10-12 six runs read 251 stores with a rejected key; 185 were left without
    a catalogue or a store type, and counted as done."""
    run(config_for(tmp_path, LINKS), fetcher=FakeFetcher(responses()))  # no key: LLM skipped

    without_key = prepare(config_for(tmp_path, LINKS))
    assert set(without_key.reusable) == {"monkees.com", "boutique.com"}, (
        "a run that has no LLM either cannot do better: it loads them"
    )
    with_key = prepare(config_for(tmp_path, LINKS), {"openai": SecretStr("sk-key-123456")})
    assert with_key.reusable == {}, "a run whose LLM can work reads them again"


def test_only_what_the_llm_could_change_makes_a_visit_unfinished():
    assert is_unfinished("no_products", "", llm_worked=False)
    assert is_unfinished("ok", "unknown", llm_worked=False)
    assert not is_unfinished("ok", "multi_brand", llm_worked=False), "the vendors decided it"
    assert not is_unfinished("no_products", "", llm_worked=True), "the LLM looked and found none"
    assert not is_unfinished("blocked", "", llm_worked=False)


def test_the_newest_visit_decides_and_a_deleted_run_is_forgotten(tmp_path):
    ledger = Ledger(tmp_path)
    now = datetime(2026, 10, 13, tzinfo=UTC)

    def visit(domain, days_ago, status, run_id, unfinished=False):
        (tmp_path / run_id / "tables").mkdir(parents=True, exist_ok=True)
        (tmp_path / run_id / "tables" / "stores.jsonl").touch()
        moment = (now - timedelta(days=days_ago)).isoformat(timespec="seconds")
        return Visit(domain, run_id, moment, status, 3, unfinished)

    ledger.record(
        [
            visit("went-bad.com", 10, "ok", "R1"),
            visit("went-bad.com", 3, "blocked", "R2"),
            visit("came-back.com", 10, "blocked", "R1"),
            visit("came-back.com", 2, "ok", "R2"),
            visit("broke.com", 10, "ok", "R1"),
            visit("broke.com", 2, "error", "R2"),
            visit("no-llm.com", 4, "no_products", "R2", unfinished=True),
            visit("gone.com", 1, "ok", "R3"),
        ]
    )
    (tmp_path / "R3" / "tables" / "stores.jsonl").unlink()  # the operator deleted run R3
    stores = ["went-bad.com", "came-back.com", "broke.com", "no-llm.com", "gone.com"]

    assert set(ledger.recent(stores, 30, now)) == {"came-back.com"}, (
        "an older good visit does not outlive a newer refusal or failure"
    )
    assert ledger.settled(30, now) == ["came-back.com", "went-bad.com"], (
        "blocked is an answer; an error, a visit the LLM never got to and a deleted run are not"
    )
    assert ledger.settled(30, now, with_unfinished=True) == [
        "came-back.com",
        "went-bad.com",
        "no-llm.com",
    ], "newest first"


def test_a_ledger_whose_first_build_did_not_finish_is_built_again(tmp_path):
    first = run(config_for(tmp_path, LINKS), fetcher=FakeFetcher(responses()))
    runs_dir = tmp_path / "runs"
    stores = first.root / "tables" / "stores.jsonl"
    stores.write_text(stores.read_text() + '{"run_id": "cut off mid-wri')  # a killed run

    path = runs_dir / LEDGER_FILE
    path.unlink()
    with sqlite3.connect(path) as db:  # what an interrupted build left: a file, no version
        db.execute("CREATE TABLE visits (domain TEXT)")
    found = Ledger(runs_dir).recent(["monkees.com"], 30, with_unfinished=True)
    assert set(found) == {"monkees.com"}, "rebuilt, and the broken line was passed over"


def test_a_store_whose_product_links_are_asked_for_is_visited(tmp_path):
    run(config_for(tmp_path, LINKS), fetcher=FakeFetcher(responses()))
    deep = "website\nhttps://monkees.com/products/cher\nhttps://boutique.com\n"
    prepared = prepare(config_for(tmp_path, deep))
    assert set(prepared.reusable) == {"boutique.com"}, (
        "the earlier run read monkees.com from its homepage, not this product page"
    )

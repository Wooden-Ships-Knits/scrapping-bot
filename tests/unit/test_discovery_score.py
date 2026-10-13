"""The scorecard of a discovery: known stockists found, agreement between sources, and
what the run made of the stores. Every store and stockist here is made up."""

import json

from scrapebot import cli
from scrapebot.analysis.discovery import as_text, score
from scrapebot.analysis.inputs import load_stockists

STOCKISTS = [
    {"name": "Cedar & Hyde", "website": "https://www.cedarandhyde.com", "city": "Boulder",
     "prov_state": "CO", "country": "United States"},
    {"name": "The Tango Boutique", "website": "", "city": "Denver", "prov_state": "CO",
     "country": "United States"},
    {"name": "Loop", "website": "https://loop.example", "city": "Austin", "prov_state": "TX",
     "country": "United States"},
    {"name": "Maple Knits", "website": "https://mapleknits.ca", "city": "Toronto",
     "prov_state": "ON", "country": "Canada"},
    {"name": "Ava", "website": "", "city": "Reno", "prov_state": "NV", "country": "United States"},
]  # fmt: skip

FOUND = [
    {"name": "Cedar and Hyde Mercantile", "website": "https://cedarandhyde.com",
     "sources": ["ai_agent", "google_places"], "locations": [{"city": "Boulder", "state": "CO"}]},
    {"name": "Tango", "website": "https://shoptango.com", "sources": ["ai_agent"],
     "locations": [{"city": "Denver", "state": "CO"}]},
    {"name": "Tango", "website": "https://tangomiami.com", "sources": ["web_search"],
     "locations": [{"city": "Miami", "state": "FL"}]},
    {"name": "Ava", "website": "https://ava.example", "sources": ["ai_agent"],
     "locations": [{"city": "Reno", "state": "NV"}]},
    {"name": "Invented Knits", "website": "https://inventedknits.example", "sources": ["ai_agent"],
     "locations": []},
    {"name": "No Site Yet", "website": "", "sources": ["social_search"], "locations": []},
]  # fmt: skip


def folders(tmp_path, countries=("US",)):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "stockists.json").write_text(json.dumps(STOCKISTS))
    discovery = tmp_path / "discover" / "D1"
    discovery.mkdir(parents=True)
    (discovery / "stores.json").write_text(json.dumps(FOUND))
    report = {
        "discovery_id": "D1",
        "config": {"countries": list(countries)},
        "sources": [{"name": "ai_agent", "cost_usd": 0.3}, {"name": "web_search", "cost_usd": 0.1}],
        "cost_usd": 0.4,
    }
    (discovery / "report.json").write_text(json.dumps(report))
    return inputs, discovery


def run_folder(tmp_path):
    def store(domain, status, error="", store_type="", knit=0):
        return {
            "domain": domain,
            "status": status,
            "error": error,
            "store_type": store_type,
            "knit_kind_count": knit,
        }

    rows = [
        store("cedarandhyde.com", "ok", store_type="multi_brand", knit=12),
        store("shoptango.com", "ok", store_type="own_brand", knit=3),
        store("tangomiami.com", "no_products"),
        store("ava.example", "blocked", "HTTP 403"),
        store(
            "inventedknits.example",
            "error",
            "ConnectionError: HTTPSConnectionPool(host='inventedknits.example', port=443): "
            "Max retries exceeded (Caused by NameResolutionError(...))",
        ),
    ]
    root = tmp_path / "runs" / "R1"
    (root / "tables").mkdir(parents=True)
    (root / "tables" / "stores.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return root


def test_stockists_are_matched_by_website_then_by_name_where_the_state_agrees(tmp_path):
    inputs, discovery = folders(tmp_path)
    card = score(discovery, load_stockists(inputs / "stockists.json"))
    assert (card.stores, card.with_website, card.confirmed) == (6, 5, 1)
    assert card.stockists_known == 4, "the Canadian stockist is outside a US search"
    assert card.stockist_examples == ["Cedar & Hyde", "The Tango Boutique"], (
        "Cedar & Hyde by its website; Tango by name in Colorado, not the one in Florida; "
        "a three-letter name is too short to trust"
    )
    assert (card.stockists_found, card.recall, card.stockist_share) == (2, 0.5, 0.3333)
    assert {s.name: (s.stores, s.with_website, s.stockists) for s in card.sources} == {
        "ai_agent": (4, 4, 2),
        "google_places": (1, 1, 1),
        "web_search": (1, 1, 0),
        "social_search": (1, 0, 0),
    }
    assert (card.visited, card.precision, card.missing) == (None, None, None), "no run given"


def test_the_run_says_what_was_real_and_what_made_the_final_list(tmp_path):
    inputs, discovery = folders(tmp_path)
    card = score(discovery, load_stockists(inputs / "stockists.json"), run_folder(tmp_path))
    assert (card.visited, card.read, card.blocked, card.failed) == (5, 3, 1, 1)
    assert (card.missing, card.missing_examples) == (1, ["inventedknits.example"])
    assert (card.final, card.precision, card.cost_per_final_store) == (1, 0.3333, 0.4)
    text = as_text(card)
    assert "Known stockists in US: 4. Found: 2 (50%)." in text
    assert "No website at that address (invented or closed): 1: inventedknits.example." in text
    assert "On the final list (multi-brand, sells knitwear): 1 (33% of the stores read)." in text


def test_without_a_stockist_list_the_other_checks_still_stand(tmp_path):
    _, discovery = folders(tmp_path)
    card = score(discovery, [], run_folder(tmp_path))
    assert (card.stockists_known, card.recall, card.stockist_share) == (0, None, None)
    assert (card.confirmed, card.final) == (1, 1)
    assert "nothing to check against" in as_text(card)


def test_the_score_command_prints_and_keeps_the_scorecard(tmp_path, capsys):
    inputs, discovery = folders(tmp_path, countries=("US", "CA"))
    run = run_folder(tmp_path)
    code = cli.main(
        ["score", str(discovery), "--run", str(run), "--stockists", str(inputs / "stockists.json")]
    )
    assert code == 0
    assert "Known stockists in US, CA: 5. Found: 2 (40%)." in capsys.readouterr().out
    kept = json.loads((discovery / "quality.json").read_text())
    assert (kept["run_id"], kept["stockists_found"], kept["missing"]) == ("R1", 2, 1)
    assert cli.main(["score", str(tmp_path / "nowhere")]) == 2

"""The final list (ADR 0010): multi-brand stores that sell knitwear, with their knitwear."""

import functools
import json

import litellm
import pytest

from scrapebot.config import LLMConfig, RunConfig
from scrapebot.final import exclusion, judge_store, qualifies
from scrapebot.llm.gateway import Budget, LiteLLMExtractor
from scrapebot.llm.schemas import StoreTypeJudgement
from scrapebot.models import Acquired, LLMCall, Page, Product
from scrapebot.pipeline import run
from tests.fakes import FakeFetcher

SWEATER = Product(title="Cable Knit Sweater", vendor="Rose")
TEE = Product(title="Plain Tee", vendor="Rose")


class FakeJudge:
    def __init__(self, store_type="multi_brand", confidence=0.9):
        self.answer = StoreTypeJudgement.model_validate(
            {"store_type": store_type, "brands_carried": ["Vince"], "confidence": confidence}
        )
        self.calls: list[tuple[str, list[str], list[tuple[str, int]]]] = []

    def judge_store_type(self, domain, pages, vendors, titles):
        self.calls.append((domain, [p.url for p in pages], vendors))
        call = LLMCall(model="fake/model", prompt_version="store-type-v1", status="ok")
        return self.answer, [call]


def store(*products, status="ok", pages=()):
    return Acquired(domain="rose.com", status=status, products=list(products), pages=list(pages))


def test_vendors_settle_a_multi_brand_store_without_a_call():
    judge = FakeJudge()
    got = store(*(Product(title="Cardigan", vendor=v) for v in ("A", "B", "C")))
    judge_store(got, judge)
    assert (got.store_type, got.store_type_source, got.brand_count) == ("multi_brand", "vendors", 3)
    assert judge.calls == []


def test_an_unclear_knitwear_store_goes_to_the_llm_with_its_about_page_first():
    judge = FakeJudge()
    pages = [
        Page(url="https://rose.com", kind="home", text="Welcome"),
        Page(url="https://rose.com/pages/about", kind="about", text="We carry Vince"),
    ]
    got = store(SWEATER, TEE, pages=pages)
    judge_store(got, judge)
    assert (got.store_type, got.store_type_source) == ("multi_brand", "llm")
    assert got.brands == ["Vince"], "brands named by the model when the vendors gave none"
    [(_, urls, vendors)] = judge.calls
    assert urls == ["https://rose.com/pages/about", "https://rose.com"]
    assert vendors == [("Rose", 2)]
    assert got.llm_calls[0].prompt_version == "store-type-v1"


def test_a_store_without_knitwear_is_not_worth_a_call():
    judge = FakeJudge()
    got = store(TEE)
    judge_store(got, judge)
    assert (got.store_type, judge.calls) == ("unknown", [])


def test_an_unsure_answer_leaves_the_store_unknown():
    got = store(SWEATER)
    judge_store(got, FakeJudge(confidence=0.3))
    assert (got.store_type, got.store_type_source) == ("unknown", "")
    assert len(got.llm_calls) == 1, "the call is still recorded and paid for"


def test_an_extraction_verdict_is_not_asked_again():
    judge = FakeJudge()
    got = store(SWEATER)
    got.store_type = "own_brand"
    judge_store(got, judge)
    assert (got.store_type, got.store_type_source, judge.calls) == ("own_brand", "llm", [])


def test_unread_stores_are_left_alone():
    got = store(status="blocked")
    judge_store(got, FakeJudge())
    assert got.store_type == ""


def test_qualifying_and_why_not():
    row = {"status": "ok", "store_type": "multi_brand", "knit_kind_count": 2}
    assert qualifies(row)
    assert exclusion(row) == ""
    assert exclusion({**row, "status": "blocked"}) == "not_read"
    assert exclusion({**row, "knit_kind_count": 0}) == "no_knitwear"
    assert exclusion({**row, "store_type": "own_brand"}) == "own_brand"
    assert exclusion({**row, "store_type": "unknown"}) == "not_judged"


# --- a whole run ---------------------------------------------------------------

HOME = (
    '<html><script>Shopify.currency = {"active":"USD","rate":"1.0"};</script>cdn.shopify.com'
    "<a href='mailto:hello@rose.com'>Email</a><a href='/pages/wholesale'>Wholesale</a></html>"
)
WHOLESALE = "<html><body><p>" + "Stock our brands. " * 20 + "</p></body></html>"


def feed(*items: tuple[str, str]) -> str:
    return json.dumps(
        {
            "products": [
                {"title": t, "vendor": v, "handle": f"p{i}", "variants": [{"price": "99.00"}]}
                for i, (t, v) in enumerate(items)
            ]
        }
    )


def shopify(domain: str, body: str) -> dict[str, tuple[int, str]]:
    origin = f"https://{domain}"
    return {
        origin: (200, HOME),
        f"{origin}/products.json?limit=250&page=1": (200, body),
        f"{origin}/pages/wholesale": (200, WHOLESALE),
    }


def config(tmp_path, csv_text: str) -> RunConfig:
    src = tmp_path / "in.csv"
    src.write_text(csv_text)
    return RunConfig.model_validate(
        {
            "input": {"source": src},
            "output": {"runs_dir": tmp_path / "runs", "writers": ["csv", "xlsx"]},
            "fetch": {"cache_dir": tmp_path / "cache"},
        }
    )


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def test_a_run_writes_the_final_list_beside_the_raw_tables(tmp_path):
    responses = {
        **shopify(
            "boutique.com",
            feed(
                ("Aran Cardigan", "Vince"),
                ("Linen Dress", "Ulla Johnson"),
                ("Knit Beanie", "Kinross"),
                ("Leather Belt", "Vince"),
            ),
        ),
        **shopify("label.com", feed(("Label Sweater", "Label"), ("Label Tee", "Label"))),
        **shopify("nosweaters.com", feed(("Dress", "A"), ("Skirt", "B"), ("Belt", "C"))),
    }
    cfg = config(
        tmp_path,
        "name,website\nRose Boutique,https://boutique.com\nLabel,https://label.com\n"
        "Plain,https://nosweaters.com\n",
    )
    result = run(cfg, fetcher=FakeFetcher(responses))

    tables = result.root / "tables"
    [final] = read_jsonl(tables / "final_stores.jsonl")
    assert (final["domain"], final["store_name"], final["store_type"]) == (
        "boutique.com",
        "Rose Boutique",
        "multi_brand",
    )
    assert (final["knit_products"], final["knit_garments"], final["knit_accessories"]) == (2, 1, 1)
    assert final["emails"] == ["hello@rose.com"]
    assert final["wholesale_pages"] == ["https://boutique.com/pages/wholesale"]
    products = read_jsonl(tables / "final_products.jsonl")
    assert [(p["title"], p["knit_kind"]) for p in products] == [
        ("Aran Cardigan", "garment"),
        ("Knit Beanie", "accessory"),
    ]
    assert len(read_jsonl(tables / "products.jsonl")) == 9, "raw tables keep every product"

    knit = {p["title"]: p for p in read_jsonl(tables / "knit_products.jsonl")}
    assert set(knit) == {"Aran Cardigan", "Knit Beanie", "Label Sweater"}, "every store's knitwear"
    assert (knit["Label Sweater"]["store_type"], knit["Label Sweater"]["on_final_list"]) == (
        "unknown",
        False,
    )
    assert (knit["Aran Cardigan"]["store_name"], knit["Aran Cardigan"]["on_final_list"]) == (
        "Rose Boutique",
        True,
    )
    assert (result.root / "export" / "knit" / "tables.xlsx").exists()

    assert (result.root / "export" / "final" / "tables.xlsx").exists()
    assert (result.root / "export" / "final" / "csv" / "final_products.csv").exists()
    report = result.report_path.read_text()
    assert "**1 stores, 2 knitwear products**" in report
    assert "on the list or not (`export/knit/`): 3." in report
    assert "| read, but no knitted garment or accessory | 1 |" in report
    assert "- label.com" in report, "a knitwear store whose type is unclear is listed"
    assert "Not used: no API key for openai" in report


def test_without_a_key_the_run_goes_on_and_says_so(tmp_path, caplog):
    cfg = config(tmp_path, "website\nhttps://label.com\n")
    responses = shopify("label.com", feed(("Label Sweater", "Label")))
    result = run(cfg, fetcher=FakeFetcher(responses))
    [row] = read_jsonl(result.root / "tables" / "runs.jsonl")
    assert row["llm_skipped"] == "no API key for openai (openai/gpt-4o-mini)"
    [store_row] = read_jsonl(result.root / "tables" / "stores.jsonl")
    assert (store_row["status"], store_row["store_type"]) == ("ok", "unknown")
    assert "LLM stage skipped" in caplog.text


def test_the_llm_is_on_by_default_with_a_cheap_model():
    llm = LLMConfig()
    assert (llm.enabled, llm.model, llm.budget_usd) == (True, "openai/gpt-4o-mini", 1.0)


# --- the judgement call, through LiteLLM's mock response (no network) ----------------


def test_the_gateway_judges_a_store_type_and_records_the_call():
    answer = json.dumps(
        {"store_type": "multi_brand", "brands_carried": ["Vince"], "confidence": 0.8}
    )
    llm = LiteLLMExtractor(
        "openai/gpt-4o-mini",
        {},
        Budget(1.0),
        completion=functools.partial(litellm.completion, mock_response=answer),
    )
    judgement, calls = llm.judge_store_type(
        "rose.com",
        [Page(url="https://rose.com/pages/about", text="We carry Vince and Ulla Johnson.")],
        [("Rose", 12)],
        ["Aran Cardigan"],
    )
    assert judgement is not None
    assert judgement.store_type == "multi_brand"
    [call] = calls
    assert (call.status, call.prompt_version) == ("ok", "store-type-v1")
    assert call.cost_usd > 0


def test_a_spent_budget_skips_the_judgement():
    budget = Budget(0.0)
    llm = LiteLLMExtractor("openai/gpt-4o-mini", {}, budget, completion=litellm.completion)
    judgement, [call] = llm.judge_store_type("rose.com", [], [], [])
    assert (judgement, call.status) == (None, "skipped_budget")


@pytest.mark.parametrize(("flag", "enabled"), [([], True), (["--no-llm"], False)])
def test_no_llm_turns_the_model_off(flag, enabled, monkeypatch, tmp_path):
    from scrapebot import cli

    seen = {}

    def fake_run(config, **kwargs):
        seen["config"] = config
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "run", fake_run)
    cli.main(["run", "x.csv", *flag])
    assert seen["config"].llm.enabled is enabled

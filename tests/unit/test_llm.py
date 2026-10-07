"""The LLM stage, offline: a fake extractor or LiteLLM's own mock responses."""

import functools
import json
import logging

import litellm
import pytest
from pydantic import SecretStr

from scrapebot.acquire import acquire
from scrapebot.keys import RedactingFilter, load_keys, redact, register
from scrapebot.llm.evidence import apply_evidence_rule
from scrapebot.llm.gateway import Budget, LiteLLMExtractor, build_messages, explain_error, key_for
from scrapebot.llm.schemas import ExtractedProduct, StoreExtraction
from scrapebot.models import LLMCall, Page, Target
from tests.fakes import FakeFetcher

HOME = (
    "<html><body><h1>Rose Boutique</h1><a href='/collections/all'>Shop</a>"
    + "<p>Fashion.</p>" * 30
    + "</body></html>"
)
GRID = "<html><body><div>Cable Knit Cardigan $129.00</div><div>Linen Wrap Dress $98.00</div></body></html>"


def extraction(*products, confidence=0.8):
    return StoreExtraction(store_type="multi_brand", products=list(products), confidence=confidence)


class FakeLLM:
    def __init__(self, result, status="ok"):
        self.result, self.status, self.calls = result, status, []

    def extract(self, domain, pages):
        self.calls.append((domain, [p.url for p in pages]))
        call = LLMCall(
            model="fake/model",
            prompt_version="extract-v1",
            status=self.status,
            input_tokens=100,
            output_tokens=20,
            cost_usd=0.001,
        )
        return (self.result if self.status == "ok" else None), [call]


def shop():
    return FakeFetcher(
        {"https://rose.com": (200, HOME), "https://rose.com/collections/all": (200, GRID)}
    )


def test_llm_reads_a_store_nothing_else_could_and_flags_every_product():
    llm = FakeLLM(
        extraction(
            ExtractedProduct(
                title="Cable Knit Cardigan",
                price="$129.00",
                source_url="https://rose.com/collections/all",
            ),
            ExtractedProduct(
                title="Linen Wrap Dress",
                price="$98.00",
                currency="usd",
                source_url="https://rose.com/collections/all",
            ),
        )
    )
    got = acquire(Target(domain="rose.com", url="https://rose.com"), shop(), llm=llm)
    assert (got.status, got.source_used) == ("ok", "llm")
    assert [p.title for p in got.products] == ["Cable Knit Cardigan", "Linen Wrap Dress"]
    assert all(p.needs_review and p.confidence == 0.8 and p.source == "llm" for p in got.products)
    assert got.products[0].evidence_url == "https://rose.com/collections/all"
    assert (got.products[0].price, got.products[1].currency) == (129.0, "USD")
    assert got.store_type == "multi_brand"
    assert "llm" in got.layers_tried
    assert llm.calls[0][1][0] == "https://rose.com/collections/all", "listing pages go first"


def test_evidence_rule_drops_made_up_products():
    """PRD LM-07: a product is kept only if its title is on the page it cites."""
    llm = FakeLLM(
        extraction(
            ExtractedProduct(
                title="Cable Knit Cardigan",
                price="$129.00",
                source_url="https://rose.com/collections/all",
            ),
            ExtractedProduct(
                title="Alpaca Poncho",
                price="$140.00",
                source_url="https://rose.com/collections/all",
            ),
            ExtractedProduct(
                title="Linen Wrap Dress", price="$98.00", source_url="https://rose.com/not-sent"
            ),
        )
    )
    got = acquire(Target(domain="rose.com", url="https://rose.com"), shop(), llm=llm)
    assert [p.title for p in got.products] == ["Cable Knit Cardigan"]
    assert got.llm_products_dropped == 2


def test_llm_is_only_called_for_stores_without_products():
    """PRD LM-06."""
    feed = json.dumps({"products": [{"title": "Sweater", "variants": [{"price": "10"}]}]})
    llm = FakeLLM(extraction())
    f = FakeFetcher(
        {
            "https://x.com": (200, "<html>cdn.shopify.com</html>"),
            "https://x.com/products.json?limit=250&page=1": (200, feed),
        }
    )
    got = acquire(Target(domain="x.com", url="https://x.com"), f, llm=llm)
    assert got.source_used == "shopify_feed"
    assert llm.calls == []


def test_an_llm_that_finds_nothing_leaves_no_products():
    got = acquire(
        Target(domain="rose.com", url="https://rose.com"), shop(), llm=FakeLLM(extraction())
    )
    assert got.status == "no_products"
    assert len(got.llm_calls) == 1


def test_evidence_rule_tolerates_entities_case_and_curly_quotes():
    page = Page(url="https://x.com/p", text="Marilyn’s  PEARL necklace &amp; earrings $45")
    claim = ExtractedProduct(
        title="marilyn's pearl necklace & earrings", price="45", source_url="https://x.com/p/"
    )
    kept, dropped = apply_evidence_rule(extraction(claim), [page], "m", "v")
    assert len(kept) == 1
    assert dropped == []


# --- gateway, through LiteLLM's mock responses (no network) ---------------------


def mocked(content):
    return functools.partial(litellm.completion, mock_response=content)


ANSWER = json.dumps(
    {
        "store_type": "own_brand",
        "products": [
            {"title": "Cable Knit Cardigan", "price": "$129.00", "source_url": "https://rose.com/c"}
        ],
        "confidence": 0.7,
    }
)


def test_gateway_parses_validates_and_records_the_call():
    extractor = LiteLLMExtractor("openai/gpt-4o-mini", {}, Budget(1.0), completion=mocked(ANSWER))
    result, calls = extractor.extract(
        "rose.com", [Page(url="https://rose.com/c", text="Cable Knit Cardigan $129.00")]
    )
    assert result is not None
    assert result.products[0].title == "Cable Knit Cardigan"
    [call] = calls
    assert (call.status, call.model, call.prompt_version) == (
        "ok",
        "openai/gpt-4o-mini",
        "extract-v3",
    )
    assert call.input_tokens > 0
    assert call.cost_usd > 0


def test_fallback_order_is_used_when_the_first_model_fails():
    """PRD LM-10."""

    def flaky(**kwargs):
        if kwargs["model"].startswith("gemini/"):
            raise litellm.exceptions.AuthenticationError(
                "bad key", llm_provider="gemini", model=kwargs["model"]
            )
        return litellm.completion(mock_response=ANSWER, **kwargs)

    extractor = LiteLLMExtractor(
        "gemini/gemini-2.5-flash",
        {},
        Budget(1.0),
        fallbacks=["openai/gpt-4o-mini"],
        completion=flaky,
    )
    result, calls = extractor.extract("rose.com", [Page(url="https://rose.com/c", text="x")])
    assert result is not None
    assert [(c.model, c.status) for c in calls] == [
        ("gemini/gemini-2.5-flash", "error"),
        ("openai/gpt-4o-mini", "ok"),
    ]
    assert calls[0].error == "API key ditolak penyedia. Periksa key dan penyedianya."


def busy(model):
    return litellm.exceptions.ServiceUnavailableError(
        "overloaded", llm_provider="gemini", model=model
    )


def test_a_busy_provider_is_tried_again_after_a_wait():
    """2026-10-06: Gemini answered 503 to two stores of four; a retry reads them."""
    attempts, waits = [], []

    def once_busy(**kwargs):
        attempts.append(kwargs["model"])
        if len(attempts) == 1:
            raise busy(kwargs["model"])
        return litellm.completion(mock_response=ANSWER, **kwargs)

    extractor = LiteLLMExtractor(
        "gemini/gemini-2.5-flash", {}, Budget(1.0), completion=once_busy, sleep=waits.append
    )
    result, calls = extractor.extract("rose.com", [Page(url="https://rose.com/c", text="x")])
    assert result is not None
    assert [c.status for c in calls] == ["error", "ok"]
    assert calls[0].error.startswith("Penyedia sedang sibuk")
    assert waits == [3.0]


def test_a_provider_that_stays_busy_falls_back_to_the_next_model():
    waits = []

    def gemini_down(**kwargs):
        if kwargs["model"].startswith("gemini/"):
            raise busy(kwargs["model"])
        return litellm.completion(mock_response=ANSWER, **kwargs)

    extractor = LiteLLMExtractor(
        "gemini/gemini-2.5-flash",
        {},
        Budget(1.0),
        fallbacks=["openai/gpt-4o-mini"],
        completion=gemini_down,
        sleep=waits.append,
    )
    result, calls = extractor.extract("rose.com", [Page(url="https://rose.com/c", text="x")])
    assert result is not None
    assert [(c.model, c.status) for c in calls] == [
        ("gemini/gemini-2.5-flash", "error"),
        ("gemini/gemini-2.5-flash", "error"),
        ("gemini/gemini-2.5-flash", "error"),
        ("openai/gpt-4o-mini", "ok"),
    ]
    assert waits == [3.0, 10.0]


def test_budget_stops_further_calls():
    """PRD LM-09."""
    budget = Budget(0.0)
    extractor = LiteLLMExtractor("openai/gpt-4o-mini", {}, budget, completion=mocked(ANSWER))
    result, calls = extractor.extract("rose.com", [Page(url="https://rose.com/c", text="x")])
    assert result is None
    assert [c.status for c in calls] == ["skipped_budget"]


def test_unknown_model_prices_are_estimated_so_the_budget_still_works():
    extractor = LiteLLMExtractor(
        "openai/model-without-a-list-price", {}, Budget(1.0), completion=mocked(ANSWER)
    )
    _, [call] = extractor.extract("rose.com", [Page(url="https://rose.com/c", text="x")])
    assert call.cost_estimated is True
    assert call.cost_usd > 0


def test_local_models_cost_nothing():
    extractor = LiteLLMExtractor("ollama/qwen2.5:3b", {}, Budget(0.01), completion=mocked(ANSWER))
    _, [call] = extractor.extract("rose.com", [Page(url="https://rose.com/c", text="x")])
    assert (call.cost_usd, call.cost_estimated) == (0.0, False)


def test_prompt_cites_every_page_url():
    pages = [Page(url="https://a.com/1", text="One"), Page(url="https://a.com/2", text="Two")]
    content = build_messages("a.com", pages)[0]["content"]
    assert "PAGE https://a.com/1\nOne" in content
    assert "PAGE https://a.com/2\nTwo" in content
    assert "Never invent" in content


@pytest.mark.parametrize(
    ("exc", "phrase"),
    [
        (
            litellm.exceptions.NotFoundError("x", llm_provider="openai", model="m"),
            "Model tidak ditemukan",
        ),
        (
            litellm.exceptions.RateLimitError("x", llm_provider="openai", model="m"),
            "Batas pemakaian",
        ),
        (
            litellm.exceptions.APIConnectionError("x", llm_provider="ollama", model="m"),
            "tidak bisa dihubungi",
        ),
        (ValueError("boom"), "Gagal memanggil model (ValueError)"),
    ],
)
def test_errors_are_explained_in_plain_words(exc, phrase):
    assert phrase in explain_error(exc)


# --- keys ---------------------------------------------------------------------------


def test_keys_come_from_the_interface_then_environment_then_dotenv(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("GEMINI_API_KEY=from-dotenv-1234567\nOPENAI_API_KEY=from-dotenv-openai\n")
    monkeypatch.setenv("OPENAI_API_KEY", "from-environment-123")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    keys = load_keys(env, given={"anthropic": "sk-ant-from-ui-1234567890"})
    assert keys["gemini"].get_secret_value() == "from-dotenv-1234567"
    assert keys["openai"].get_secret_value() == "from-environment-123"
    assert keys["anthropic"].get_secret_value() == "sk-ant-from-ui-1234567890"
    assert "from-dotenv" not in repr(keys)
    assert key_for("anthropic/claude-haiku-4-5-20251001", keys) == "sk-ant-from-ui-1234567890"
    assert key_for("ollama/qwen2.5:3b", keys) is None


def test_redaction_masks_registered_and_key_shaped_values():
    register("my-very-secret-value")
    text = "calling with my-very-secret-value and sk-proj-abcdefghijklmnopqrstu, api_key=AIzaSyA1234567890abcdefghijklmnopqrstuv"
    cleaned = redact(text)
    assert "my-very-secret-value" not in cleaned
    assert "sk-proj-abcdef" not in cleaned
    assert "AIzaSy" not in cleaned


def test_logging_filter_masks_keys_in_messages_and_tracebacks(caplog):
    logger = logging.getLogger("scrapebot.test")
    handler = caplog.handler
    handler.addFilter(RedactingFilter())
    secret = "sk-proj-zzzzzzzzzzzzzzzzzzzzzzzz"
    try:
        raise RuntimeError(f"provider said no to {secret}")
    except RuntimeError:
        logger.exception("call failed with key %s", secret)
    assert secret not in caplog.text
    assert "[redacted]" in caplog.text


def test_secretstr_never_prints():
    assert "abc" not in str(SecretStr("abc-123456"))


def test_evidence_rule_needs_a_price_that_is_on_the_page():
    """Seen live with a small local model: brand names and blog authors came back as
    'products'. Their titles were on the page, so title evidence alone let them in."""
    page = Page(
        url="https://x.com/brands", text="Peserico. Created in Italy in 1962. Cardigan Aria $189.00"
    )
    claims = extraction(
        ExtractedProduct(title="Peserico", source_url="https://x.com/brands"),
        ExtractedProduct(title="Cardigan Aria", price="$199.00", source_url="https://x.com/brands"),
        ExtractedProduct(title="Cardigan Aria", price="$189.00", source_url="https://x.com/brands"),
    )
    kept, dropped = apply_evidence_rule(claims, [page], "m", "v")
    assert [(p.title, p.price_raw) for p in kept] == [("Cardigan Aria", "$189.00")]
    assert len(dropped) == 2


def test_evidence_rule_keeps_one_product_per_title():
    pages = [Page(url=f"https://x.com/{i}", text="Lambswool Crew 98.00") for i in range(3)]
    claims = extraction(
        *[
            ExtractedProduct(title="Lambswool Crew", price="98.00", source_url=f"https://x.com/{i}")
            for i in range(3)
        ]
    )
    kept, _ = apply_evidence_rule(claims, pages, "m", "v")
    assert len(kept) == 1


def test_price_evidence_matches_the_number_not_the_formatting():
    page = Page(url="https://x.com/p", text="Fisherman Sweater USD 1,295.00")
    kept, _ = apply_evidence_rule(
        extraction(
            ExtractedProduct(title="Fisherman Sweater", price="$1295", source_url="https://x.com/p")
        ),
        [page],
        "m",
        "v",
    )
    assert len(kept) == 1


def test_a_failed_llm_says_why_the_store_has_no_products():
    class DownLLM:
        def extract(self, domain, pages):
            call = LLMCall(
                model="gemini/gemini-2.5-flash",
                prompt_version="extract-v1",
                status="error",
                error="Penyedia sedang sibuk (server penuh). Coba lagi nanti atau pasang model cadangan.",
            )
            return None, [call]

    got = acquire(Target(domain="rose.com", url="https://rose.com"), shop(), llm=DownLLM())
    assert got.status == "no_products"
    assert got.error.startswith("LLM: Penyedia sedang sibuk")
    assert "llm_failed" in got.layers_tried


def test_price_evidence_reads_european_prices():
    """knitfactory.com, 7 Oct 2026: the page says '€ 41,95' and the model wrote 41.95."""
    page = Page(
        url="https://x.com/w",
        text="-30% Casy Pullover (2) 6 colours € 59,95 € 41,95 Luna Spencer € 1.069,95",
    )
    kept, dropped = apply_evidence_rule(
        extraction(
            ExtractedProduct(title="Casy Pullover", price="41.95", source_url="https://x.com/w"),
            ExtractedProduct(title="Luna Spencer", price="€1069.95", source_url="https://x.com/w"),
        ),
        [page],
        "m",
        "v",
    )
    assert [(p.title, p.price) for p in kept] == [
        ("Casy Pullover", 41.95),
        ("Luna Spencer", 1069.95),
    ]
    assert dropped == []


def test_a_repeated_title_is_not_counted_as_dropped():
    """Dropped means failed the evidence rule; a second copy of a kept product did not."""
    pages = [Page(url=f"https://x.com/{i}", text="Lambswool Crew 98.00") for i in range(2)]
    claims = extraction(
        *[
            ExtractedProduct(title="Lambswool Crew", price="98.00", source_url=f"https://x.com/{i}")
            for i in range(2)
        ]
    )
    kept, dropped = apply_evidence_rule(claims, pages, "m", "v")
    assert len(kept) == 1
    assert dropped == []


def test_a_category_page_sends_its_product_grid_to_the_model():
    """knitfactory.com, 7 Oct 2026: trafilatura kept the SEO paragraph and dropped the
    grid, so the model saw no products on six category pages."""
    from pathlib import Path

    from scrapebot.extract.text import html_to_text
    from scrapebot.llm.gateway import MAX_CHARS_PER_PAGE, condensed_text

    html = (
        Path(__file__).parents[1] / "fixtures/http/knitfactory.com-2026-10-07-category.html"
    ).read_text()
    url = "https://www.knitfactory.com/en/women/clothing/pullover-sweaters"
    text = condensed_text(Page(url=url, html=html, text=html_to_text(html), kind="collection"))
    assert "Casy Pullover" in text
    assert "41,95" in text
    assert len(text) <= MAX_CHARS_PER_PAGE


def test_an_article_page_still_sends_its_main_content():
    prose = "".join(
        f"<p>{line}</p>"
        for line in (
            "We knit every sweater by hand in our studio in Porto, one at a time.",
            "Our wool comes from a small farm in the Serra da Estrela mountains.",
            "Each piece takes two days, and we mend anything we make for free.",
            "We started in 2011 with one machine and a rented room above a bakery.",
        )
    )
    html = f"<html><body><nav>Home Shop Cart</nav><article>{prose}</article></body></html>"
    from scrapebot.extract.text import html_to_text
    from scrapebot.llm.gateway import condensed_text

    text = condensed_text(Page(url="https://x.com/story", html=html, text=html_to_text(html)))
    assert text.startswith("We knit every sweater")


def test_prompt_asks_for_titles_in_the_page_language():
    """herrlicher.com, 7 Oct 2026: the model wrote 'Model Winona Hoodie' for the German
    'Modell Winona Hoodie', and the evidence rule rightly dropped 27 such products."""
    content = build_messages("x.com", [Page(url="https://x.com", text="Modell Winona 89,95 €")])
    text = content[0]["content"]
    assert "Do not translate" in text
    assert "Do not convert prices" in text

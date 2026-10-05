"""Every supported provider parses into the same schema (PRD LM-02).

Each provider's HTTP API is answered by respx with a response in that provider's
own wire format (tests/fixtures/llm/*.json), so the whole path is exercised:
LiteLLM's request and response translation, instructor's JSON parsing and
validation, and our token and cost recording. Nothing touches the network.

The fixtures follow each provider's documented response shape; replace them with
real recorded responses when keys are available.
"""

import json
from pathlib import Path

import httpx
import pytest
import respx
from pydantic import SecretStr

from scrapebot.llm.gateway import Budget, LiteLLMExtractor
from scrapebot.models import Page

FIXTURES = Path(__file__).parents[1] / "fixtures" / "llm"
ANSWER = {
    "store_type": "multi_brand",
    "products": [
        {
            "title": "Cable Knit Cardigan",
            "price": "$129.00",
            "currency": "USD",
            "vendor": "Wooden Ships",
            "source_url": "https://rose.com/c",
        }
    ],
    "brands_carried": ["Wooden Ships"],
    "has_wholesale_page": False,
    "confidence": 0.82,
}
PAGES = [Page(url="https://rose.com/c", text="Cable Knit Cardigan by Wooden Ships $129.00")]

# provider -> (model, URL pattern the provider's API is called at, fixture, extra settings)
PROVIDERS = {
    "openai": (
        "openai/gpt-4o-mini",
        r"https://api\.openai\.com/v1/chat/completions",
        "openai-chat.json",
        {},
    ),
    "gemini": (
        "gemini/gemini-2.5-flash",
        r"https://generativelanguage\.googleapis\.com/.*generateContent.*",
        "gemini-generate.json",
        {},
    ),
    "anthropic": (
        "anthropic/claude-haiku-4-5-20251001",
        r"https://api\.anthropic\.com/v1/messages",
        "anthropic-messages.json",
        {},
    ),
    "mistral": (
        "mistral/mistral-small-latest",
        r"https://api\.mistral\.ai/v1/chat/completions",
        "openai-chat.json",
        {},
    ),
    "groq": (
        "groq/llama-3.3-70b-versatile",
        r"https://api\.groq\.com/openai/v1/chat/completions",
        "groq-chat.json",
        {},
    ),
    "openrouter": (
        "openrouter/openai/gpt-4o-mini",
        r"https://openrouter\.ai/api/v1/chat/completions",
        "openai-chat.json",
        {},
    ),
    "azure": (
        "azure/my-gpt4o-deployment",
        r"https://rose-test\.openai\.azure\.com/openai/deployments/my-gpt4o-deployment/chat/completions.*",
        "openai-chat.json",
        {"AZURE_API_BASE": "https://rose-test.openai.azure.com", "AZURE_API_VERSION": "2024-10-21"},
    ),
    "ollama": (
        "ollama/qwen2.5:3b",
        r"http://localhost:11434/api/(generate|chat)",
        "ollama-generate.json",
        {},
    ),
}


def fixture(name: str) -> dict:
    raw = (FIXTURES / name).read_text()
    return json.loads(raw.replace("__ANSWER__", json.dumps(json.dumps(ANSWER))[1:-1]))


@pytest.mark.parametrize("provider", list(PROVIDERS))
def test_provider_response_parses_into_the_schema(provider, monkeypatch):
    model, url, fixture_name, env = PROVIDERS[provider]
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    keys = {} if provider == "ollama" else {provider: SecretStr(f"test-key-{provider}-000000")}
    with respx.mock(assert_all_called=True) as mock:
        route = mock.route(url__regex=url).mock(
            return_value=httpx.Response(200, json=fixture(fixture_name))
        )
        extractor = LiteLLMExtractor(model, keys, Budget(5.0), max_retries=0)
        result, calls = extractor.extract("rose.com", PAGES)

    assert route.called, f"{provider}: no request reached its API"
    assert result is not None, f"{provider}: {calls[-1].error}"
    assert result.products[0].title == "Cable Knit Cardigan"
    assert result.confidence == 0.82
    [call] = calls
    assert (call.status, call.model) == ("ok", model)
    assert call.input_tokens == 812
    assert call.output_tokens == 64
    sent = route.calls[0].request
    if provider not in ("ollama", "gemini"):
        assert f"test-key-{provider}" in (
            sent.headers.get("authorization", "")
            + sent.headers.get("x-api-key", "")
            + sent.headers.get("api-key", "")
        )

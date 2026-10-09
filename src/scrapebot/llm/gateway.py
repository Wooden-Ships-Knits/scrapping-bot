"""LiteLLM + instructor gateway (ADR 0004).

One interface for every provider: a model is `provider/model`, so a new one needs no
code change (PRD LM-01, LM-03). Calls go through a fallback order (LM-10), stop at a
per-run budget (LM-09), and each call is recorded with tokens, cost, model and
prompt version (LM-11). Keys are passed per call and never stored or logged.
"""

import bisect
import logging
import re
import threading
import time
from collections.abc import Callable, Mapping
from importlib import resources
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, SecretStr

from ..models import LLMCall, Page
from .schemas import StoreExtraction, StoreTypeJudgement

log = logging.getLogger(__name__)

PROMPT_VERSION = "extract-v3"  # prompts/extract_v3.md; earlier versions kept for history
JUDGE_PROMPT_VERSION = "store-type-v1"  # prompts/store_type_v1.md (ADR 0010)
MAX_PAGES = 6
MAX_CHARS_PER_PAGE = 6000
# Judging a store's type reads its home, about and brands pages, its vendors and some
# product names: enough to tell a boutique from a label, at a fraction of extraction.
JUDGE_MAX_PAGES = 3
JUDGE_CHARS_PER_PAGE = 2500
JUDGE_VENDORS = 25
JUDGE_TITLES = 30
# A price as written on a page: a currency sign, or a number with two decimals.
PRICE_MARK_RE = re.compile(r"[€$£¥₹]|\d[.,]\d{2}(?!\d)")
WINDOW_LEAD = 300  # characters kept before the first price: a heading, a product name

# Environment variable that holds each provider's key, as LiteLLM names them.
KEY_VARIABLES = {
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "groq": "GROQ_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "azure": "AZURE_API_KEY",
}

# When LiteLLM has no price for a model, cost is estimated at these rates (USD per
# million tokens) so the budget still stops the run. Deliberately pessimistic.
FALLBACK_INPUT_PER_M = 5.0
# Waits before trying the same model again after a passing failure (a busy or
# rate-limited provider, a timeout). Measured on 2026-10-06: Gemini answered 503 to two
# stores of four, and the same stores read fine a minute earlier.
RETRY_DELAYS_SECONDS = (3.0, 10.0)
FALLBACK_OUTPUT_PER_M = 15.0


def provider_of(model: str) -> str:
    return model.split("/", 1)[0].lower() if "/" in model else "openai"


def is_local(model: str) -> bool:
    return provider_of(model) in ("ollama", "ollama_chat")


def key_for(model: str, keys: Mapping[str, SecretStr]) -> str | None:
    """The key for a model's provider, from the keys given for this run."""
    secret = keys.get(provider_of(model))
    return secret.get_secret_value() if secret else None


CallRecord = LLMCall


class Budget:
    """Spending limit for one run, shared by every store visited in parallel."""

    def __init__(self, limit_usd: float):
        self.limit = limit_usd
        self.spent = 0.0
        self._lock = threading.Lock()

    def exhausted(self) -> bool:
        with self._lock:
            return self.spent >= self.limit

    def add(self, cost: float) -> None:
        with self._lock:
            self.spent += cost


Extraction = tuple[StoreExtraction | None, list[CallRecord]]
Judgement = tuple[StoreTypeJudgement | None, list[CallRecord]]
Answer = TypeVar("Answer", bound=BaseModel)


class ProductReader(Protocol):
    """Acquisition depends on this, not on LiteLLM (ADR 0004)."""

    def extract(self, domain: str, pages: list[Page]) -> Extraction: ...


class StoreTypeJudge(Protocol):
    """The final list depends on this, not on LiteLLM (ADR 0010)."""

    def judge_store_type(
        self, domain: str, pages: list[Page], vendors: list[tuple[str, int]], titles: list[str]
    ) -> Judgement: ...


class LLMExtractor(ProductReader, StoreTypeJudge, Protocol):
    """The LLM stage of a run: reads products and judges store types."""


def _prompt_template(version: str = PROMPT_VERSION) -> str:
    prompt = resources.files("scrapebot.llm").joinpath(f"prompts/{version.replace('-', '_')}.md")
    return prompt.read_text(encoding="utf-8")


def condensed_text(page: Page, limit: int = MAX_CHARS_PER_PAGE) -> str:
    """The page's main content (trafilatura) when it keeps the page's prices; else the
    stretch of its visible text with the most prices in it.

    trafilatura is made for articles: on a category page it keeps the SEO paragraph and
    drops the product grid (knitfactory.com), which is the part the model needs.
    """
    text = ""
    if page.html:
        try:
            import trafilatura

            text = trafilatura.extract(page.html, include_comments=False, include_tables=True) or ""
        except Exception:  # extraction is best effort; the visible text is always there
            text = ""
    prices_on_page = len(PRICE_MARK_RE.findall(page.text))
    if len(text) >= 200 and len(PRICE_MARK_RE.findall(text[:limit])) * 2 >= prices_on_page:
        return text[:limit]
    return densest_window(page.text, limit)


def densest_window(text: str, limit: int) -> str:
    """The `limit` characters of `text` holding the most prices, from a little before
    the first of them, so a long cookie banner or filter list cannot fill the window."""
    if len(text) <= limit:
        return text
    starts = [m.start() for m in PRICE_MARK_RE.finditer(text)]
    if not starts:
        return text[:limit]
    best = max(range(len(starts)), key=lambda i: bisect.bisect_left(starts, starts[i] + limit) - i)
    begin = max(0, starts[best] - WINDOW_LEAD)
    return text[begin : begin + limit]


def build_messages(domain: str, pages: list[Page]) -> list[dict[str, str]]:
    blocks = [f"PAGE {page.url}\n{condensed_text(page)}" for page in pages]
    content = _prompt_template().format(domain=domain, pages="\n\n".join(blocks))
    return [{"role": "user", "content": content}]


def build_judge_messages(
    domain: str, pages: list[Page], vendors: list[tuple[str, int]], titles: list[str]
) -> list[dict[str, str]]:
    vendor_lines = [f"- {name}: {n} products" for name, n in vendors[:JUDGE_VENDORS]]
    blocks = [f"PAGE {p.url}\n{p.text[:JUDGE_CHARS_PER_PAGE]}" for p in pages[:JUDGE_MAX_PAGES]]
    content = _prompt_template(JUDGE_PROMPT_VERSION).format(
        domain=domain,
        vendors="\n".join(vendor_lines) or "(the products name no vendor)",
        titles="\n".join(f"- {t}" for t in titles[:JUDGE_TITLES]) or "(none)",
        pages="\n\n".join(blocks) or "(no page text)",
    )
    return [{"role": "user", "content": content}]


def usage_of(completion: Any) -> tuple[int, int]:
    usage = getattr(completion, "usage", None)
    if usage is None:
        return 0, 0
    tokens_in = int(getattr(usage, "prompt_tokens", 0) or 0)
    return tokens_in, int(getattr(usage, "completion_tokens", 0) or 0)


def cost_of(completion: Any, model: str, tokens_in: int, tokens_out: int) -> tuple[float, bool]:
    """(cost in USD, whether it is an estimate). Local models are free."""
    import litellm

    if is_local(model):
        return 0.0, False
    try:
        cost = float(litellm.completion_cost(completion_response=completion, model=model) or 0.0)
    except Exception:
        cost = 0.0
    if cost > 0:
        return cost, False
    estimate = (tokens_in * FALLBACK_INPUT_PER_M + tokens_out * FALLBACK_OUTPUT_PER_M) / 1e6
    return estimate, True


def is_transient(exc: BaseException) -> bool:
    """A failure that may pass if the same call is made again a little later."""
    from litellm import exceptions as errors

    passing = (
        errors.ServiceUnavailableError,
        errors.InternalServerError,
        errors.RateLimitError,
        errors.Timeout,
        errors.APIConnectionError,
    )
    return isinstance(_root_cause(exc), passing)


def explain_error(exc: BaseException) -> str:
    """A provider error in plain words for the operator (PRD LM-05), never the key."""
    from litellm import exceptions as errors

    # Most specific first: ContextWindowExceededError is a BadRequestError.
    messages: list[tuple[type[BaseException], str]] = [
        (
            errors.ServiceUnavailableError,
            "Penyedia sedang sibuk (server penuh). Coba lagi nanti atau pasang model cadangan.",
        ),
        (errors.InternalServerError, "Penyedia sedang bermasalah. Coba lagi nanti."),
        (errors.AuthenticationError, "API key ditolak penyedia. Periksa key dan penyedianya."),
        (errors.PermissionDeniedError, "Key ini tidak punya akses ke model tersebut."),
        (
            errors.NotFoundError,
            "Model tidak ditemukan. Tulis sebagai penyedia/model, contoh gemini/gemini-2.5-flash.",
        ),
        (errors.RateLimitError, "Batas pemakaian penyedia tercapai (rate limit atau kuota)."),
        (errors.ContextWindowExceededError, "Teks halaman terlalu panjang untuk model ini."),
        (
            errors.APIConnectionError,
            "Penyedia tidak bisa dihubungi. Periksa koneksi atau alamat server Ollama.",
        ),
        (errors.BadRequestError, "Permintaan ditolak penyedia (model atau parameter tidak cocok)."),
    ]
    root = _root_cause(exc)
    for kind, message in messages:
        if isinstance(root, kind):
            return message
    return f"Gagal memanggil model ({type(root).__name__})."


def _root_cause(exc: BaseException) -> BaseException:
    """instructor wraps provider errors in a retry exception; the cause is what matters."""
    seen = 0
    while exc.__cause__ is not None and seen < 10:
        exc, seen = exc.__cause__, seen + 1
    return exc


Completion = Callable[..., Any]


class LiteLLMExtractor:
    def __init__(
        self,
        model: str,
        keys: Mapping[str, SecretStr],
        budget: Budget,
        fallbacks: list[str] | None = None,
        api_base: str | None = None,
        completion: Completion | None = None,
        max_retries: int = 1,
        retry_delays: tuple[float, ...] = RETRY_DELAYS_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
    ):
        import instructor
        import litellm

        litellm.suppress_debug_info = True
        self.models = [model, *(fallbacks or [])]
        self.keys = keys
        self.budget = budget
        self.api_base = api_base
        self.max_retries = max_retries
        self.retry_delays = retry_delays
        self._sleep = sleep
        self._client = instructor.from_litellm(
            completion or litellm.completion, mode=instructor.Mode.JSON
        )

    def _call(
        self, model: str, messages: list[dict[str, str]], answer: type[Answer]
    ) -> tuple[Answer, Any]:
        kwargs: dict[str, Any] = {"temperature": 0}
        key = key_for(model, self.keys)
        if key:
            kwargs["api_key"] = key
        if self.api_base and is_local(model):
            kwargs["api_base"] = self.api_base
        return self._client.chat.completions.create_with_completion(
            model=model,
            messages=messages,  # type: ignore[arg-type]
            response_model=answer,
            max_retries=self.max_retries,
            **kwargs,
        )

    def _call_with_retries(
        self,
        model: str,
        messages: list[dict[str, str]],
        answer: type[Answer],
        version: str,
        domain: str,
        records: list[CallRecord],
    ) -> tuple[Answer, Any] | None:
        """One model's answer, retried after a passing failure; every failed attempt is
        recorded. None when the model gave no answer."""
        for attempt in range(len(self.retry_delays) + 1):
            started = time.monotonic()
            try:
                return self._call(model, messages, answer)
            except Exception as exc:
                records.append(
                    CallRecord(
                        model=model,
                        prompt_version=version,
                        status="error",
                        duration_seconds=round(time.monotonic() - started, 2),
                        error=explain_error(exc),
                    )
                )
                log.warning("LLM %s failed for %s: %s", model, domain, type(exc).__name__)
                if not is_transient(exc) or attempt == len(self.retry_delays):
                    return None
                self._sleep(self.retry_delays[attempt])
        return None

    def extract(self, domain: str, pages: list[Page]) -> Extraction:
        """The products on a store's pages (PRD LM-06)."""
        messages = build_messages(domain, pages[:MAX_PAGES])
        return self._ask(domain, messages, StoreExtraction, PROMPT_VERSION)

    def judge_store_type(
        self, domain: str, pages: list[Page], vendors: list[tuple[str, int]], titles: list[str]
    ) -> Judgement:
        """Own label or multi-brand, for a store its vendors leave unclear (ADR 0010)."""
        messages = build_judge_messages(domain, pages, vendors, titles)
        return self._ask(domain, messages, StoreTypeJudgement, JUDGE_PROMPT_VERSION)

    def _ask(
        self, domain: str, messages: list[dict[str, str]], answer: type[Answer], version: str
    ) -> tuple[Answer | None, list[CallRecord]]:
        """Try each model in order until one answers; record every attempt."""
        records: list[CallRecord] = []
        if self.budget.exhausted():
            records.append(
                CallRecord(model=self.models[0], prompt_version=version, status="skipped_budget")
            )
            return None, records
        for model in self.models:
            started = time.monotonic()
            reply = self._call_with_retries(model, messages, answer, version, domain, records)
            if reply is None:
                continue  # the next model in the fallback order
            result, completion = reply
            tokens_in, tokens_out = usage_of(completion)
            cost, estimated = cost_of(completion, model, tokens_in, tokens_out)
            self.budget.add(cost)
            records.append(
                CallRecord(
                    model=model,
                    prompt_version=version,
                    status="ok",
                    input_tokens=tokens_in,
                    output_tokens=tokens_out,
                    cost_usd=round(cost, 6),
                    cost_estimated=estimated,
                    duration_seconds=round(time.monotonic() - started, 2),
                )
            )
            return result, records
        return None, records


def check_connection(
    model: str, api_key: str | None, api_base: str | None = None
) -> tuple[bool, str]:
    """A tiny call that proves the key and model work before a run (PRD LM-05)."""
    import litellm

    litellm.suppress_debug_info = True
    kwargs: dict[str, Any] = {"max_tokens": 5, "temperature": 0}
    if api_key:
        kwargs["api_key"] = api_key
    if api_base:
        kwargs["api_base"] = api_base
    try:
        ping = [{"role": "user", "content": "Reply with OK."}]
        litellm.completion(model=model, messages=ping, **kwargs)
    except Exception as exc:
        return False, explain_error(exc)
    return True, f"Terhubung ke {model}."

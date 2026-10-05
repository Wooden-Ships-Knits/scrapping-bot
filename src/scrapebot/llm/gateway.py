"""LiteLLM + instructor gateway (ADR 0004).

One interface for every provider: a model is `provider/model`, so a new one needs no
code change (PRD LM-01, LM-03). Calls go through a fallback order (LM-10), stop at a
per-run budget (LM-09), and each call is recorded with tokens, cost, model and
prompt version (LM-11). Keys are passed per call and never stored or logged.
"""

import logging
import threading
import time
from collections.abc import Callable, Mapping
from importlib import resources
from typing import Any, Protocol

from pydantic import SecretStr

from ..models import LLMCall, Page
from .schemas import StoreExtraction

log = logging.getLogger(__name__)

PROMPT_VERSION = "extract-v2"  # prompts/extract_v2.md; earlier versions kept for history
MAX_PAGES = 6
MAX_CHARS_PER_PAGE = 6000

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


class LLMExtractor(Protocol):
    """Acquisition depends on this, not on LiteLLM (ADR 0004)."""

    def extract(self, domain: str, pages: list[Page]) -> Extraction: ...


def _prompt_template() -> str:
    prompt = resources.files("scrapebot.llm").joinpath(
        f"prompts/{PROMPT_VERSION.replace('-', '_')}.md"
    )
    return prompt.read_text(encoding="utf-8")


def condensed_text(page: Page, limit: int = MAX_CHARS_PER_PAGE) -> str:
    """The page's main content (trafilatura), falling back to its full visible text."""
    text = ""
    if page.html:
        try:
            import trafilatura

            text = trafilatura.extract(page.html, include_comments=False, include_tables=True) or ""
        except Exception:  # extraction is best effort; the visible text is always there
            text = ""
    if len(text) < 200:
        text = page.text
    return text[:limit]


def build_messages(domain: str, pages: list[Page]) -> list[dict[str, str]]:
    blocks = [f"PAGE {page.url}\n{condensed_text(page)}" for page in pages]
    content = _prompt_template().format(domain=domain, pages="\n\n".join(blocks))
    return [{"role": "user", "content": content}]


def _usage(completion: Any) -> tuple[int, int]:
    usage = getattr(completion, "usage", None)
    if usage is None:
        return 0, 0
    tokens_in = int(getattr(usage, "prompt_tokens", 0) or 0)
    return tokens_in, int(getattr(usage, "completion_tokens", 0) or 0)


def _cost(completion: Any, model: str, tokens_in: int, tokens_out: int) -> tuple[float, bool]:
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


def explain_error(exc: BaseException) -> str:
    """A provider error in plain words for the operator (PRD LM-05), never the key."""
    from litellm import exceptions as errors

    # Most specific first: ContextWindowExceededError is a BadRequestError.
    messages: list[tuple[type[BaseException], str]] = [
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
    ):
        import instructor
        import litellm

        litellm.suppress_debug_info = True
        self.models = [model, *(fallbacks or [])]
        self.keys = keys
        self.budget = budget
        self.api_base = api_base
        self.max_retries = max_retries
        self._client = instructor.from_litellm(
            completion or litellm.completion, mode=instructor.Mode.JSON
        )

    def _call(self, model: str, messages: list[dict[str, str]]) -> tuple[StoreExtraction, Any]:
        kwargs: dict[str, Any] = {"temperature": 0}
        key = key_for(model, self.keys)
        if key:
            kwargs["api_key"] = key
        if self.api_base and is_local(model):
            kwargs["api_base"] = self.api_base
        return self._client.chat.completions.create_with_completion(
            model=model,
            messages=messages,  # type: ignore[arg-type]
            response_model=StoreExtraction,
            max_retries=self.max_retries,
            **kwargs,
        )

    def extract(self, domain: str, pages: list[Page]) -> Extraction:
        """Try each model in order until one answers; record every attempt."""
        records: list[CallRecord] = []
        if self.budget.exhausted():
            records.append(
                CallRecord(
                    model=self.models[0], prompt_version=PROMPT_VERSION, status="skipped_budget"
                )
            )
            return None, records
        messages = build_messages(domain, pages[:MAX_PAGES])
        for model in self.models:
            started = time.monotonic()
            try:
                result, completion = self._call(model, messages)
            except Exception as exc:
                records.append(
                    CallRecord(
                        model=model,
                        prompt_version=PROMPT_VERSION,
                        status="error",
                        duration_seconds=round(time.monotonic() - started, 2),
                        error=explain_error(exc),
                    )
                )
                log.warning("LLM %s failed for %s: %s", model, domain, type(exc).__name__)
                continue
            tokens_in, tokens_out = _usage(completion)
            cost, estimated = _cost(completion, model, tokens_in, tokens_out)
            self.budget.add(cost)
            records.append(
                CallRecord(
                    model=model,
                    prompt_version=PROMPT_VERSION,
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

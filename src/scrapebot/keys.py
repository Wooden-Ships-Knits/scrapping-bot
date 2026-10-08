"""API keys: read from the interface (memory only) or `.env`, never written anywhere.

Keys travel as `SecretStr`, so printing a config or a model never shows them, and
the logging filter below masks anything that still looks like a key (standards,
section 4). Metric: zero keys in logs or outputs (PRD section 13).
"""

import logging
import os
import re
import threading
from collections.abc import Mapping
from pathlib import Path

from pydantic import SecretStr

from .llm.gateway import KEY_VARIABLES

# Keys of the paid search APIs used by `scrapebot discover` (ADR 0008).
SEARCH_KEY_VARIABLES = {
    "google_places": "GOOGLE_MAPS_API_KEY",
    "tavily": "TAVILY_API_KEY",
}

# Shapes of real provider keys, masked even if a key was never registered here.
KEY_PATTERNS = (
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"sk-(?:proj-)?[A-Za-z0-9_\-]{16,}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),
    re.compile(r"gsk_[A-Za-z0-9]{20,}"),
    re.compile(r"tvly-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"shp(?:at|ss|ca|pa)_[A-Za-z0-9]{16,}"),  # Shopify Admin tokens and secrets
    re.compile(
        r"(?i)\b(api[_-]?key|authorization|x-api-key)(\"?\s*[:=]\s*\"?)(?:Bearer\s+)?[^\s\"',}]{8,}"
    ),
)
MASK = "[redacted]"

_known: set[str] = set()
_lock = threading.Lock()


def register(secret: str) -> None:
    """Mask this exact value wherever it appears in a log line."""
    if secret and len(secret) >= 6:
        with _lock:
            _known.add(secret)


def redact(text: str) -> str:
    with _lock:
        known = sorted(_known, key=len, reverse=True)
    for secret in known:
        text = text.replace(secret, MASK)
    for pattern in KEY_PATTERNS:
        text = pattern.sub(
            lambda m: (
                f"{m.group(1)}{m.group(2)}{MASK}" if m.lastindex and m.lastindex >= 2 else MASK
            ),
            text,
        )
    return text


class RedactingFilter(logging.Filter):
    """Masks keys in every log record, including exception text."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        cleaned = redact(message)
        if cleaned != message:
            record.msg, record.args = cleaned, None
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
        return True


# Third-party loggers that log request parameters (page text, headers) at INFO or
# DEBUG. Their warnings still show; their chatter never does.
QUIET_LOGGERS = (
    "LiteLLM",
    "LiteLLM Router",
    "LiteLLM Proxy",
    "httpx",
    "httpcore",
    "openai",
    "instructor",
)


def install_redaction() -> None:
    """Attach the filter to every handler of the root logger (call after configuring it)
    and quiet the libraries that would log request contents."""
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    flt = RedactingFilter()
    for handler in logging.getLogger().handlers:
        if not any(isinstance(f, RedactingFilter) for f in handler.filters):
            handler.addFilter(flt)


def load_keys(
    env_file: str | Path = ".env", given: Mapping[str, str] | None = None
) -> dict[str, SecretStr]:
    """LLM provider and search API keys: given ones (from the interface) win, then the
    environment, then `.env`.

    `.env` is read without touching `os.environ`, so keys never leak into child
    processes or other code.
    """
    from_file: dict[str, str | None] = {}
    if Path(env_file).exists():
        from dotenv import dotenv_values

        from_file = dict(dotenv_values(env_file))
    keys: dict[str, SecretStr] = {}
    for provider, variable in {**KEY_VARIABLES, **SEARCH_KEY_VARIABLES}.items():
        value = (given or {}).get(provider) or os.environ.get(variable) or from_file.get(variable)
        if value:
            register(value)
            keys[provider] = SecretStr(value)
    return keys

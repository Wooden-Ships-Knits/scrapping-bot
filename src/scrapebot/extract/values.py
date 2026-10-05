"""Turning source values into the text and codes the records hold."""

import re
from typing import Any

_CURRENCY_CODE_RE = re.compile(r"^[A-Za-z]{3}$")


def as_text(value: Any) -> str:
    """A source value as text. Structured data puts lists and objects where text is expected."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return as_text(value[0]) if value else ""
    if isinstance(value, dict):
        return as_text(value.get("name") or value.get("@value") or "")
    return str(value)


def currency_code(value: Any) -> str:
    """An ISO 4217-shaped code, uppercased, or "" for anything else."""
    text = as_text(value)
    return text.upper() if _CURRENCY_CODE_RE.match(text) else ""

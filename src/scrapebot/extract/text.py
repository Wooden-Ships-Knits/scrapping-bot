"""HTML to plain text."""

import html as html_lib
import re

from bs4 import BeautifulSoup

_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def clean_html(text: str) -> str:
    """Plain text from an HTML fragment: drop script/style blocks (incl. contents),
    strip remaining tags, unescape entities, collapse whitespace.

    Fast and regex-based, for short fragments such as product descriptions.
    """
    text = _SCRIPT_STYLE_RE.sub(" ", text or "")
    text = _TAG_RE.sub(" ", text)
    text = html_lib.unescape(text)
    return _WHITESPACE_RE.sub(" ", text).strip()


def html_to_text(html: str) -> str:
    """Visible text of a whole page, with scripts, styles and whitespace runs removed."""
    soup = BeautifulSoup(html or "", "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return _WHITESPACE_RE.sub(" ", soup.get_text(" ")).strip()

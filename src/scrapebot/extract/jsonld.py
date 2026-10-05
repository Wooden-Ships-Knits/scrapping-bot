"""JSON-LD blocks, read without extruct for the quick checks on every homepage."""

import json
import re
from typing import Any

_JSONLD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.S | re.I
)


def jsonld_blocks(html: str) -> list[dict[str, Any]]:
    """Every parseable JSON-LD object in the page, flattened out of @graph wrappers."""
    blocks: list[Any] = []
    for raw in _JSONLD_RE.findall(html or ""):
        try:
            parsed = json.loads(raw.strip())
        except (ValueError, TypeError):
            continue
        items = parsed if isinstance(parsed, list) else [parsed]
        for item in items:
            if isinstance(item, dict):
                blocks.extend(item.get("@graph", [item]))
    return [b for b in blocks if isinstance(b, dict)]


def first_offer(block: dict[str, Any]) -> dict[str, Any]:
    offers = block.get("offers") or {}
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    return offers if isinstance(offers, dict) else {}

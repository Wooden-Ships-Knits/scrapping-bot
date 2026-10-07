"""The product focus of a run: which kinds of items the operator is looking for.

Each item has words that mark a product as one of it. A run flags every product with
the items it matches (`products.matched_items`) and counts them per store
(`stores.focus_count`). Nothing is dropped: raw means raw (ADR 0008).
"""

import re

from ..models import Product
from .signals import is_knit, product_blob

# Item key -> (search phrase for discovery, product words). Knitwear uses the existing,
# stricter rule in `signals.is_knit`, so it has no word list here.
ITEMS: dict[str, tuple[str, tuple[str, ...]]] = {
    "knitwear": ("sweaters and knitwear", ()),
    "cashmere_wool": (
        "cashmere and wool knitwear",
        ("cashmere", "merino", "alpaca", "mohair", "lambswool", "wool", "yak", "angora"),
    ),
    "fall_winter": (
        "fall and winter collections",
        ("fall", "autumn", "winter", "holiday", "fw", "aw"),
    ),
    "spring_summer": (
        "spring and summer collections",
        ("spring", "summer", "resort", "ss"),
    ),
}
OTHER = "other"  # the operator's own words
DEFAULT_ITEMS = ("knitwear",)

# "FW25", "AW 2026", "SS26": a season code with its year.
_SEASON_CODE = r"(?:\s?'?\d{2,4})?"


def _pattern(words: tuple[str, ...] | list[str]) -> re.Pattern[str] | None:
    words = [w.strip() for w in words if w.strip()]
    if not words:
        return None
    alternatives = "|".join(re.escape(w) + _SEASON_CODE for w in words)
    return re.compile(rf"\b(?:{alternatives})s?\b", re.I)


_PATTERNS = {key: _pattern(words) for key, (_, words) in ITEMS.items()}


def matched_items(product: Product, items: list[str], terms: list[str]) -> list[str]:
    """The chosen items this product is, in the order they were chosen."""
    blob = product_blob(product)
    found = []
    for item in items:
        if item == "knitwear":
            hit = is_knit(product)
        elif item == OTHER:
            pattern = _pattern(terms)
            hit = bool(pattern and pattern.search(blob))
        else:
            pattern = _PATTERNS.get(item)
            hit = bool(pattern and pattern.search(blob))
        if hit:
            found.append(item)
    return found


def search_phrase(items: list[str], terms: list[str]) -> str:
    """What discovery searches for: 'sweaters and knitwear, cashmere and wool knitwear'."""
    parts = [ITEMS[i][0] for i in items if i in ITEMS]
    if OTHER in items:
        parts += [t.strip() for t in terms if t.strip()]
    return ", ".join(parts) or ITEMS["knitwear"][0]

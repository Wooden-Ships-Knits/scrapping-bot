"""Reading numbers out of price strings."""

import re
import statistics
from collections.abc import Iterable
from typing import Any

from ..models import Product

PRICE_RE = re.compile(r"(\d[\d,]*(?:\.\d{1,2})?)")


def parse_price(raw: Any) -> float | None:
    """First positive number in the input, or None. Handles '$1,395.00' and ranges."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, int | float):
        return float(raw) or None
    m = PRICE_RE.search(str(raw))
    if not m:
        return None
    try:
        value = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    return value if value > 0 else None


def price_stats(
    products: Iterable[Product],
) -> tuple[float | None, float | None, float | None]:
    """(min, max, median) over products that have a price. All None if none do."""
    prices = [p.price for p in products if p.price]
    if not prices:
        return (None, None, None)
    return (min(prices), max(prices), statistics.median(prices))

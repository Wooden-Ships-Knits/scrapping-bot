"""Pure extraction functions. No network, no file I/O, no global state."""
import re

from .models import Product

KNIT_TERMS = (
    "knit", "knitwear", "sweater", "cardigan", "pullover", "jumper",
    "cashmere", "merino", "wool", "crewneck", "turtleneck", "sweatshirt",
    "poncho", "shawl",
)
KNIT_RE = re.compile(r"\b(" + "|".join(KNIT_TERMS) + r")\b", re.I)


def knit_terms_in(text: str | None) -> list[str]:
    """Distinct knit terms present in text, lowercased, in first-seen order."""
    if not text:
        return []
    seen: list[str] = []
    for m in KNIT_RE.finditer(text):
        term = m.group(1).lower()
        if term not in seen:
            seen.append(term)
    return seen


def product_blob(p: Product) -> str:
    """Searchable text for one product. Tolerates null fields from Shopify feeds."""
    tags = p.tags or []
    parts = [
        p.title or "",
        p.product_type or "",
        " ".join(tags) if isinstance(tags, list) else str(tags),
        (p.description or "")[:400],
    ]
    return " ".join(part for part in parts if part).strip()


def knit_products(products: list[Product]) -> list[Product]:
    """The subset of products whose searchable text mentions a knit term."""
    return [p for p in products if knit_terms_in(product_blob(p))]

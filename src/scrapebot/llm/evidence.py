"""The evidence rule (PRD LM-07): a product the model names is kept only if it can be
found where the model says it is.

Three checks: `source_url` must be one of the pages sent; the title must appear in
that page's text; and the item must have a price that also appears on that page.
The price check was added after a live run with a small local model, which named
brand pages and blog authors as products: their names were on the page, but no
price was. One product is kept per title. Kept products are flagged `needs_review`
(LM-08).
"""

import html
import re

from ..acquire.discovery import url_key
from ..extract.prices import NUMBER_RE, parse_price, read_number
from ..extract.values import currency_code
from ..models import Page, Product
from .schemas import ExtractedProduct, StoreExtraction

_SPACE_RE = re.compile(r"\s+")


def normalise(text: str) -> str:
    """Lowercase, entities unescaped, curly quotes straightened, whitespace collapsed."""
    text = html.unescape(text or "").lower()
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return _SPACE_RE.sub(" ", text).strip()


def prices_in(text: str) -> set[float]:
    """Every price-shaped number in a text, read as parse_price reads one. A number
    joined by a space ('2 100') is also read as its parts, in case the space was not
    a thousands separator."""
    found = set()
    for token in NUMBER_RE.findall(text or ""):
        for part in {token, *token.split()}:
            found.add(round(read_number(part), 2))
    return found


def apply_evidence_rule(
    extraction: StoreExtraction, pages: list[Page], model: str, prompt_version: str
) -> tuple[list[Product], list[ExtractedProduct]]:
    """(kept products, dropped claims)."""
    texts = {url_key(p.url): normalise(p.text) for p in pages}
    numbers = {url_key(p.url): prices_in(p.text) for p in pages}
    kept: list[Product] = []
    dropped: list[ExtractedProduct] = []
    seen: set[str] = set()
    for item in extraction.products:
        key = url_key(item.source_url)
        page_text = texts.get(key)
        title = normalise(item.title)
        price = parse_price(item.price)
        price_on_page = price is not None and round(price, 2) in numbers.get(key, set())
        if title and title in seen:  # a second copy of a kept product is not a failure
            continue
        if not page_text or not title or title not in page_text or not price_on_page:
            dropped.append(item)
            continue
        seen.add(title)
        kept.append(
            Product(
                title=item.title.strip(),
                price=parse_price(item.price),
                price_raw=(item.price or "").strip(),
                currency=currency_code(item.currency),
                vendor=(item.vendor or "").strip(),
                url=item.source_url,
                source="llm",
                evidence_url=item.source_url,
                needs_review=True,
                confidence=extraction.confidence,
                raw={
                    **item.model_dump(),
                    "model": model,
                    "prompt_version": prompt_version,
                    "store_type": extraction.store_type,
                },
            )
        )
    return kept, dropped

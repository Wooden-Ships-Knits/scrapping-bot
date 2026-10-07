"""The prospect summary: one row per input link, in the v1 column layout.

It keeps the qualification view v1 users work from (knitwear share, contacts) until
the analysis phase replaces it. Original input columns come first, untouched. Unlike
the seven tables, this is a derived view: computed while page HTML is still in
memory, never re-read by the pipeline.
"""

import csv
from pathlib import Path
from typing import Any

from .extract.pages import about_snippet, find_wholesale_page
from .extract.signals import is_chain, knit_products
from .inputs.resolve import ResolvedInput
from .models import Acquired

SUMMARY_COLUMNS = [
    "input_id", "domain", "scrape_status", "ssl_bypassed", "source_used", "platform",
    "is_chain", "pages_fetched", "product_count", "knit_count", "knit_share",
    "knit_examples", "currency", "currency_mixed", "emails", "phone", "instagram",
    "facebook", "wholesale_page", "about_snippet",
]  # fmt: skip

MAX_KNIT_EXAMPLES = 5
STORE_NAME_KEYS = ("store_name", "name", "store", "business_name", "title")


def _store_name(meta: dict[str, Any]) -> str:
    lowered = {str(k).lower(): v for k, v in meta.items()}
    for key in STORE_NAME_KEYS:
        if lowered.get(key):
            return str(lowered[key])
    return ""


def summary_row(item: ResolvedInput, acquired: Acquired | None) -> dict[str, Any]:
    """One row for one input link. `acquired` is None for links that were not visited."""
    row: dict[str, Any] = dict.fromkeys(SUMMARY_COLUMNS, "")
    row.update(input_id=item.input_id, domain=item.domain)
    if acquired is None:
        row.update(scrape_status=item.status, pages_fetched=0, product_count=0, knit_count=0)
        row.update(is_chain=False, ssl_bypassed=False, currency_mixed=False)
        return row

    products = acquired.products
    knits = knit_products(products)
    currencies = {p.currency for p in products} - {""}
    all_html = " ".join(p.html for p in acquired.pages)
    first = {c.type: c.value for c in reversed(acquired.contacts)}

    row.update(
        scrape_status=acquired.status,
        ssl_bypassed=acquired.ssl_bypassed,
        source_used=acquired.source_used,
        platform=acquired.platform,
        is_chain=is_chain(_store_name(item.meta), all_html),
        pages_fetched=acquired.pages_fetched,
        product_count=len(products),
        knit_count=len(knits),
        knit_share=f"{round(100 * len(knits) / len(products))}%" if products else "",
        knit_examples="; ".join(p.title for p in knits[:MAX_KNIT_EXAMPLES]),
        currency=acquired.currency or (min(currencies) if len(currencies) == 1 else ""),
        # Prices in more than one currency cannot be compared without converting them.
        currency_mixed=len(currencies) > 1,
        emails="; ".join([c.value for c in acquired.contacts if c.type == "email"][:5]),
        phone="; ".join([c.value for c in acquired.contacts if c.type == "phone"][:3]),
        instagram=first.get("instagram", ""),
        facebook=first.get("facebook", ""),
        wholesale_page=find_wholesale_page(acquired.read_pages),
        about_snippet=about_snippet(acquired.read_pages),
    )
    return row


def write_summary_csv(items: list[ResolvedInput], rows: list[dict[str, Any]], path: Path) -> Path:
    """Input columns (first-seen order) followed by the summary columns, one row per link."""
    by_id = {item.input_id: item for item in items}
    meta_cols = list(dict.fromkeys(k for item in items for k in item.meta))
    meta_cols = [c for c in meta_cols if c not in SUMMARY_COLUMNS]
    if not meta_cols:
        meta_cols = ["link"]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=meta_cols + SUMMARY_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in sorted(rows, key=lambda r: r["input_id"]):
            item = by_id[row["input_id"]]
            original = item.meta or {"link": item.raw}
            writer.writerow({**{k: original.get(k, "") for k in meta_cols}, **row})
    return path

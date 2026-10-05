"""Roll one store's acquired data into a single flat CSV row."""

from datetime import UTC, datetime

from . import extract
from .models import Acquired, Target

ORIGINAL_COLUMNS = [
    "store_name",
    "latitude",
    "longitude",
    "website",
    "potential_conflict",
    "nearest_stockist",
    "drive_minutes",
    "distance_miles",
    "address",
    "found_near",
    "types",
    "place_id",
]

SCRAPED_COLUMNS = [
    "domain",
    "scrape_status",
    "source_used",
    "platform",
    "is_chain",
    "pages_fetched",
    "product_count",
    "knit_count",
    "knit_share",
    "knit_examples",
    "knit_price_min",
    "knit_price_max",
    "price_min",
    "price_max",
    "price_median",
    "emails",
    "phone",
    "instagram",
    "facebook",
    "wholesale_page",
    "about_snippet",
    "fetched_at",
]

OUTPUT_COLUMNS = ORIGINAL_COLUMNS + SCRAPED_COLUMNS

MAX_KNIT_EXAMPLES = 5


def _blank_record() -> dict:
    return {col: "" for col in OUTPUT_COLUMNS}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def build_skipped_record(row: dict, reason: str) -> dict:
    """A full-width row for a store that was never fetched."""
    rec = _blank_record()
    for col in ORIGINAL_COLUMNS:
        rec[col] = row.get(col, "")
    rec["domain"] = ""
    rec["scrape_status"] = reason
    rec["is_chain"] = False
    rec["pages_fetched"] = 0
    rec["product_count"] = 0
    rec["knit_count"] = 0
    rec["fetched_at"] = _now()
    return rec


def build_record(target: Target, acquired: Acquired) -> dict:
    """One output row per store."""
    rec = _blank_record()
    primary = target.rows[0] if target.rows else {}
    for col in ORIGINAL_COLUMNS:
        rec[col] = primary.get(col, "")

    all_html = " ".join(p.html for p in acquired.pages)
    knits = extract.knit_products(acquired.products)
    p_min, p_max, p_med = extract.price_stats(acquired.products)
    k_min, k_max, _ = extract.price_stats(knits)

    rec["domain"] = target.domain
    rec["scrape_status"] = acquired.status
    rec["source_used"] = acquired.source_used
    rec["platform"] = extract.detect_platform(all_html)
    rec["is_chain"] = extract.is_chain(primary.get("store_name", ""), all_html)
    rec["pages_fetched"] = acquired.pages_fetched
    rec["product_count"] = len(acquired.products)
    rec["knit_count"] = len(knits)
    rec["knit_share"] = (
        f"{round(100 * len(knits) / len(acquired.products))}%" if acquired.products else ""
    )
    rec["knit_examples"] = "; ".join(p.title for p in knits[:MAX_KNIT_EXAMPLES])
    rec["knit_price_min"] = k_min if k_min is not None else ""
    rec["knit_price_max"] = k_max if k_max is not None else ""
    rec["price_min"] = p_min if p_min is not None else ""
    rec["price_max"] = p_max if p_max is not None else ""
    rec["price_median"] = p_med if p_med is not None else ""
    rec["emails"] = "; ".join(extract.extract_emails(all_html)[:5])
    rec["phone"] = "; ".join(extract.extract_phones(all_html)[:3])

    socials = extract.extract_socials(all_html)
    rec["instagram"] = socials["instagram"]
    rec["facebook"] = socials["facebook"]
    rec["wholesale_page"] = extract.find_wholesale_page(acquired.pages)
    rec["about_snippet"] = extract.about_snippet(acquired.pages)
    rec["fetched_at"] = _now()
    return rec

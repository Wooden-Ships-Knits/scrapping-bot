"""The final list (ADR 0010): multi-brand stores that sell knitwear, with their knitwear.

The raw tables keep every store and every product (raw means raw). The final list
is a view derived from them, so changing the criteria never needs a new scrape:

- a store qualifies when it was read (`ok`), resells other brands (`multi_brand`), and
  has at least one product that is a knitted garment or accessory (`knit_kind`);
- its row carries the brands, knitwear counts and contacts an analyst needs, and
  `final_products` holds only its knitwear.

`judge_store` decides the store type while the store is visited: the vendor rule
first (`extract.brands`), then the LLM for a knitwear store the rule leaves unclear.
"""

import logging
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping
from itertools import islice
from typing import TYPE_CHECKING, Any

from .extract.brands import brand_mix
from .extract.knitwear import knit_kind
from .models import Acquired, Page
from .outputs import Table
from .tables import FINAL_TABLES, FinalProductRow, FinalStoreRow, columns

if TYPE_CHECKING:
    from .llm.gateway import StoreTypeJudge
    from .store import RunStore

log = logging.getLogger(__name__)

FINAL_STORE_TYPE = "multi_brand"
# The LLM's answer counts only when it is at least this sure; below, the store stays
# `unknown` and is listed in the report for a person to check.
MIN_JUDGE_CONFIDENCE = 0.6
JUDGE_PAGE_ORDER = ("about", "brands", "home")
CONTACTS_KEPT = 5  # per type, per store
NAME_COLUMNS = ("name", "store_name", "Account name", "title", "company")
BATCH_ROWS = 5000

# Why a store is not on the final list, for the report.
EXCLUSIONS = {
    "not_read": "not read (status other than ok)",
    "no_knitwear": "read, but no knitted garment or accessory",
    "own_brand": "sells its own label",
    "not_judged": "sells knitwear, store type unclear (check by hand)",
}


def qualifies(store: Mapping[str, Any]) -> bool:
    """Whether a `stores` row belongs on the final list."""
    return (
        store.get("status") == "ok"
        and store.get("store_type") == FINAL_STORE_TYPE
        and store.get("knit_kind_count", 0) > 0
    )


def exclusion(store: Mapping[str, Any]) -> str:
    """Why a store is not on the final list (a key of EXCLUSIONS), or "" if it is."""
    if qualifies(store):
        return ""
    if store.get("status") != "ok":
        return "not_read"
    if not store.get("knit_kind_count", 0):
        return "no_knitwear"
    return "own_brand" if store.get("store_type") == "own_brand" else "not_judged"


def judge_store(got: Acquired, llm: "StoreTypeJudge | None" = None) -> None:
    """Set the store type of a readable store: the vendors, then the LLM if unclear.

    The extraction stage may already have judged a store it read products for; a
    multi-brand verdict from the vendors still wins, being read from the catalogue.
    """
    if got.status != "ok":
        return
    mix = brand_mix(got.domain, got.products)
    got.brands, got.brand_count = mix.brands, mix.brand_count
    if mix.store_type == FINAL_STORE_TYPE:
        got.store_type, got.store_type_source = mix.store_type, "vendors"
        return
    if got.store_type:  # the extraction call already judged it; asking again adds nothing
        got.store_type_source = "llm" if got.store_type != "unknown" else ""
        return
    got.store_type = "unknown"
    if llm is None or not any(knit_kind(p) for p in got.products):
        return  # a store without knitwear cannot qualify, so it is not worth a call
    vendors = Counter(p.vendor.strip() for p in got.products if p.vendor and p.vendor.strip())
    judgement, calls = llm.judge_store_type(
        got.domain,
        _judge_pages(got.read_pages),
        vendors.most_common(),
        [p.title for p in got.products],
    )
    got.llm_calls += calls
    if judgement is None or judgement.confidence < MIN_JUDGE_CONFIDENCE:
        return
    got.store_type, got.store_type_source = judgement.store_type, "llm"
    if not got.brands:
        got.brands = judgement.brands_carried[:10]


def _judge_pages(pages: list[Page]) -> list[Page]:
    order = {kind: i for i, kind in enumerate(JUDGE_PAGE_ORDER)}
    chosen = sorted((p for p in pages if p.kind in order), key=lambda p: order[p.kind])
    return chosen or pages[:1]


def build_final(store: "RunStore") -> list[Table]:
    """Write `final_stores` and `final_products` from the run's tables; return them for
    the writers. Streams the large tables once each."""
    stores = {s["domain"]: s for s in store.rows("stores") if qualifies(s)}
    names = _input_names(store.rows("inputs"))
    contacts = _contacts(store.rows("contacts"), stores)
    wholesale = _wholesale_pages(store.rows("pages"), stores)
    for name in FINAL_TABLES:
        store.path(name).write_text("", encoding="utf-8")  # a rerun of the end rewrites them

    kinds: dict[str, Counter[str]] = {d: Counter() for d in stores}
    for batch in _batches(_final_products(store.rows("products"), stores, kinds)):
        store.append(batch)
    store.append(
        FinalStoreRow(
            run_id=s["run_id"],
            domain=domain,
            url=s["url"],
            store_name=next((names[i] for i in s.get("input_ids", []) if names.get(i)), ""),
            platform=s.get("platform", ""),
            currency=s.get("currency", ""),
            store_type=s["store_type"],
            store_type_source=s.get("store_type_source", ""),
            brand_count=s.get("brand_count", 0),
            brands=s.get("brands", []),
            product_count=s.get("product_count", 0),
            knit_products=sum(kinds[domain].values()),
            knit_garments=kinds[domain]["garment"],
            knit_accessories=kinds[domain]["accessory"],
            emails=contacts[domain]["email"],
            phones=contacts[domain]["phone"],
            instagram=contacts[domain]["instagram"],
            facebook=contacts[domain]["facebook"],
            wholesale_pages=wholesale[domain],
        )
        for domain, s in stores.items()
    )
    log.info("Final list: %d stores, %d knitwear products", len(stores), _total(kinds))
    return [
        Table(name=name, columns=columns(model), rows=store.rows(name))
        for name, model in FINAL_TABLES.items()
    ]


def _final_products(
    products: Iterable[dict[str, Any]],
    stores: Mapping[str, Any],
    kinds: dict[str, Counter[str]],
) -> Iterator[FinalProductRow]:
    for p in products:
        kind = p.get("knit_kind", "")
        if p["domain"] not in stores or not kind:
            continue
        kinds[p["domain"]][kind] += 1
        yield FinalProductRow(
            run_id=p["run_id"],
            domain=p["domain"],
            knit_kind=kind,
            title=p["title"],
            price_raw=p.get("price_raw", ""),
            currency=p.get("currency", ""),
            vendor=p.get("vendor", ""),
            product_type=p.get("product_type", ""),
            url=p.get("url", ""),
            evidence_url=p.get("evidence_url", ""),
            source=p["source"],
            needs_review=p.get("needs_review", False),
        )


def _input_names(inputs: Iterable[dict[str, Any]]) -> dict[int, str]:
    """The store name an input row carried (a discovery file, an account list)."""
    names = {}
    for row in inputs:
        meta = row.get("meta") or {}
        name = next((str(meta[c]).strip() for c in NAME_COLUMNS if meta.get(c)), "")
        if name:
            names[row["input_id"]] = name
    return names


def _contacts(
    rows: Iterable[dict[str, Any]], stores: Mapping[str, Any]
) -> dict[str, dict[str, list[str]]]:
    found: dict[str, dict[str, list[str]]] = {
        d: {t: [] for t in ("email", "phone", "instagram", "facebook")} for d in stores
    }
    for c in rows:
        kept = found.get(c["domain"], {}).get(c["type"])
        if kept is not None and c["value"] not in kept and len(kept) < CONTACTS_KEPT:
            kept.append(c["value"])
    return found


def _wholesale_pages(
    rows: Iterable[dict[str, Any]], stores: Mapping[str, Any]
) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {d: [] for d in stores}
    for page in rows:
        if (
            page["domain"] in found
            and page.get("page_kind") in ("wholesale", "stockist")
            and not page.get("error")
        ):
            found[page["domain"]].append(page["url"])
    return found


def _batches(rows: Iterable[FinalProductRow]) -> Iterator[list[FinalProductRow]]:
    it = iter(rows)
    while batch := list(islice(it, BATCH_ROWS)):
        yield batch


def _total(kinds: dict[str, Counter[str]]) -> int:
    return sum(sum(c.values()) for c in kinds.values())

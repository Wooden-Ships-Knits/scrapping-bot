"""The tidy tables every run produces (ADR 0006, PRD section 8): the seven of the PRD
plus `llm_calls`, which records every model call (PRD LM-11), and three derived at the end
of a run (ADR 0010): the two tables of the final list (`FINAL_TABLES`) and every knitwear
product of every store that was read (`KNIT_TABLES`).

Each table is a Pydantic model whose fields are its columns, in order. Writers
derive column types from the annotations, so a new column is added here and
nowhere else. Tables join on `run_id` and `domain`.
"""

import types
from dataclasses import dataclass
from typing import Any, ClassVar, Literal, Union, get_args, get_origin

from pydantic import BaseModel, ConfigDict, Field

ColumnKind = Literal["str", "int", "float", "bool", "json"]


class Row(BaseModel):
    model_config = ConfigDict(extra="forbid")
    table: ClassVar[str]


class RunRow(Row):
    table: ClassVar[str] = "runs"
    run_id: str
    started_at: str
    finished_at: str = ""
    scrapebot_version: str
    config: dict[str, Any]  # never holds secrets
    input_count: int = 0
    store_count: int = 0
    limit: int | None = None
    llm_cost_usd: float = 0.0
    llm_skipped: str = ""  # why the LLM stage was on but could not run, e.g. no key


class InputRow(Row):
    table: ClassVar[str] = "inputs"
    run_id: str
    input_id: int
    raw: str  # the link exactly as supplied
    url: str = ""
    domain: str = ""
    # processed, or why the link was skipped:
    # duplicate | over_limit | no_website | invalid_url | social_only | marketplace
    status: str
    is_deep_link: bool = False
    meta: dict[str, Any] = Field(default_factory=dict)  # the input row, untouched


class StoreRow(Row):
    table: ClassVar[str] = "stores"
    run_id: str
    domain: str
    url: str
    status: str  # ok | no_products | js_required | blocked | error
    error: str = ""
    platform: str = ""
    currency: str = ""
    currency_source: str = ""
    source_used: str = ""
    layers_tried: list[str] = Field(default_factory=list)
    product_count: int = 0
    knit_count: int = 0  # products that are knitwear (`products.is_knitwear`)
    focus_count: int = 0  # products matching any item the run looks for
    page_count: int = 0  # pages read
    failed_page_count: int = 0  # pages that could not be read; see `pages.error`
    contact_count: int = 0
    ssl_bypassed: bool = False
    llm_used: bool = False  # a model was called for this store (products or store type)
    llm_products_dropped: int = 0  # products the LLM named that failed the evidence rule
    # own_brand | multi_brand | unknown for a readable store; "" otherwise (ADR 0010)
    store_type: str = ""
    store_type_source: str = ""  # vendors | llm: what decided `store_type`
    brand_count: int = 0  # distinct outside brands among the product vendors
    brands: list[str] = Field(default_factory=list)  # the first ten, most products first
    knit_kind_count: int = 0  # products that are knitted garments or accessories (`knit_kind`)
    input_ids: list[int] = Field(default_factory=list)
    fetched_at: str


class ProductRow(Row):
    table: ClassVar[str] = "products"
    run_id: str
    domain: str
    title: str
    price_raw: str = ""  # as the source wrote it; never read into a number here
    currency: str = ""
    vendor: str = ""
    product_type: str = ""
    tags: list[str] = Field(default_factory=list)
    url: str = ""
    description: str = ""
    source: str
    evidence_url: str = ""
    needs_review: bool = False
    confidence: float | None = None
    # Knit terms in the title, type, tags or description (`extract.signals.is_knit`).
    # A flag beside the raw values, never a filter: every product is kept.
    is_knitwear: bool = False
    # Strict: the title or product type names a knitted garment or accessory
    # (`extract.knitwear`). garment | accessory | "". The final list reads this one.
    knit_kind: str = ""
    # The run's chosen items this product matches (`config.focus`), e.g. ["knitwear"].
    matched_items: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class PageRow(Row):
    table: ClassVar[str] = "pages"
    run_id: str
    domain: str
    url: str
    page_kind: str
    http_status: int | None = None
    error: str = ""  # why the page could not be read; "" when it was
    via: str = "http"
    language: str = ""
    text: str = ""


class ContactRow(Row):
    table: ClassVar[str] = "contacts"
    run_id: str
    domain: str
    type: str
    value: str
    source_url: str


class ChangeRow(Row):
    table: ClassVar[str] = "changes"
    run_id: str
    domain: str
    change_type: str
    key: str
    old_value: str = ""
    new_value: str = ""


class LLMCallRow(Row):
    """One call to a model: tokens, cost, model and prompt version (PRD LM-11)."""

    table: ClassVar[str] = "llm_calls"
    run_id: str
    domain: str
    model: str
    prompt_version: str
    status: str  # ok | error | skipped_budget
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    cost_estimated: bool = False
    duration_seconds: float = 0.0
    error: str = ""


class FinalStoreRow(Row):
    """A store on the final list: multi-brand and selling knitwear (ADR 0010)."""

    table: ClassVar[str] = "final_stores"
    run_id: str
    domain: str
    url: str
    store_name: str = ""  # from the input row, when it had one
    platform: str = ""
    currency: str = ""
    store_type: str
    store_type_source: str
    brand_count: int = 0
    brands: list[str] = Field(default_factory=list)
    product_count: int = 0
    knit_products: int = 0
    knit_garments: int = 0
    knit_accessories: int = 0
    emails: list[str] = Field(default_factory=list)
    phones: list[str] = Field(default_factory=list)
    instagram: list[str] = Field(default_factory=list)
    facebook: list[str] = Field(default_factory=list)
    wholesale_pages: list[str] = Field(default_factory=list)


class FinalProductRow(Row):
    """A knitwear product of a store on the final list (ADR 0010)."""

    table: ClassVar[str] = "final_products"
    run_id: str
    domain: str
    knit_kind: str  # garment | accessory
    title: str
    price_raw: str = ""
    currency: str = ""
    vendor: str = ""
    product_type: str = ""
    url: str = ""
    evidence_url: str = ""
    source: str
    needs_review: bool = False


TABLES: dict[str, type[Row]] = {
    model.table: model
    for model in (
        RunRow,
        InputRow,
        StoreRow,
        ProductRow,
        PageRow,
        ContactRow,
        ChangeRow,
        LLMCallRow,
    )
}


class KnitProductRow(Row):
    """A knitwear product of any store that was read, final list or not (ADR 0010)."""

    table: ClassVar[str] = "knit_products"
    run_id: str
    domain: str
    store_name: str = ""  # from the input row, when it had one
    store_type: str = ""  # multi_brand | own_brand | unknown
    on_final_list: bool = False  # the store is in `final_stores`
    knit_kind: str  # garment | accessory
    title: str
    price_raw: str = ""
    currency: str = ""
    vendor: str = ""
    product_type: str = ""
    url: str = ""
    evidence_url: str = ""
    source: str
    needs_review: bool = False


# Derived at the end of a run from the tables above; never part of the raw export.
FINAL_TABLES: dict[str, type[Row]] = {m.table: m for m in (FinalStoreRow, FinalProductRow)}
KNIT_TABLES: dict[str, type[Row]] = {KnitProductRow.table: KnitProductRow}


@dataclass(frozen=True)
class Column:
    name: str
    kind: ColumnKind
    nullable: bool


_SCALAR_KINDS: dict[Any, ColumnKind] = {str: "str", int: "int", float: "float", bool: "bool"}


def _column_kind(annotation: Any) -> tuple[ColumnKind, bool]:
    nullable = False
    if get_origin(annotation) in (Union, types.UnionType):
        members = [a for a in get_args(annotation) if a is not type(None)]
        nullable = len(members) < len(get_args(annotation))
        annotation = members[0]
    if get_origin(annotation) in (list, dict) or annotation in (list, dict):
        return "json", nullable
    return _SCALAR_KINDS[annotation], nullable


def columns(model: type[Row]) -> list[Column]:
    """The model's columns, in field order, with the kind each writer stores."""
    out = []
    for name, field in model.model_fields.items():
        kind, nullable = _column_kind(field.annotation)
        out.append(Column(name=name, kind=kind, nullable=nullable))
    return out

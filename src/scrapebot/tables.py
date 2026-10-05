"""The seven tidy tables every run produces (ADR 0006, PRD section 8).

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
    page_count: int = 0  # pages read
    failed_page_count: int = 0  # pages that could not be read; see `pages.error`
    contact_count: int = 0
    ssl_bypassed: bool = False
    input_ids: list[int] = Field(default_factory=list)
    fetched_at: str


class ProductRow(Row):
    table: ClassVar[str] = "products"
    run_id: str
    domain: str
    title: str
    price_raw: str = ""
    price: float | None = None
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


TABLES: dict[str, type[Row]] = {
    model.table: model
    for model in (RunRow, InputRow, StoreRow, ProductRow, PageRow, ContactRow, ChangeRow)
}


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

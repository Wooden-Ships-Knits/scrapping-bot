"""Records passed between pipeline stages.

These live in memory during a run. What is written out is defined separately in
`tables.py`, so internal fields (such as a page's HTML) never reach the output.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FetchResult(_Record):
    """One HTTP response, or the record of why there wasn't one."""

    url: str
    status_code: int | None
    body: str
    final_url: str
    error: str = ""
    ssl_bypassed: bool = False
    from_cache: bool = False

    @property
    def ok(self) -> bool:
        return self.status_code == 200 and not self.error


class Product(_Record):
    """One product as its source declared it. Values are not cleaned or converted."""

    title: str = ""
    price: float | None = None  # first positive number in `price_raw`
    price_raw: str = ""  # the price exactly as the source gave it
    currency: str = ""  # ISO 4217 as declared by the source; "" when unknown
    vendor: str = ""
    product_type: str = ""
    tags: list[str] = Field(default_factory=list)
    description: str = ""  # plain text, never HTML
    url: str = ""
    source: str = ""  # shopify_feed | jsonld
    evidence_url: str = ""  # the page or feed response it was read from
    raw: dict[str, Any] = Field(default_factory=dict)  # the full source object

    @field_validator(
        "title", "price_raw", "currency", "vendor", "product_type", "description", "url",
        mode="before",
    )  # fmt: skip
    @classmethod
    def _null_text_is_empty(cls, value: Any) -> Any:
        # Shopify feeds return null for empty fields; this crashed v1's recon run.
        return "" if value is None else value

    @field_validator("tags", mode="before")
    @classmethod
    def _null_tags_are_empty(cls, value: Any) -> Any:
        return [] if value is None else value


class Page(_Record):
    """A fetched page. `html` is kept in memory for extraction and never written out."""

    url: str
    html: str = Field(default="", exclude=True, repr=False)
    text: str = ""
    kind: str = "other"  # home | about | contact | wholesale | stockist | product | ...
    http_status: int | None = None


class Contact(_Record):
    type: str  # email | phone | instagram | facebook | tiktok | linkedin | pinterest
    value: str
    source_url: str


class Target(_Record):
    """One store to visit, built from one or more input links on the same domain."""

    domain: str  # registrable domain: the grouping key
    url: str  # where the visit starts: the origin of the first link
    input_ids: list[int] = Field(default_factory=list)
    deep_links: list[str] = Field(default_factory=list)  # product or page links from input


class Acquired(_Record):
    """Everything gathered for one store."""

    domain: str
    url: str = ""
    status: str = "ok"  # ok | no_products | js_required | blocked | error
    error: str = ""
    ssl_bypassed: bool = False  # TLS verification was disabled to read the site
    platform: str = ""
    currency: str = ""  # store currency, ISO 4217; "" when the site does not declare one
    currency_source: str = ""  # shopify_js | meta | jsonld
    source_used: str = "none"  # shopify_feed | sitemap | crawl | none
    layers_tried: list[str] = Field(default_factory=list)
    products: list[Product] = Field(default_factory=list)
    pages: list[Page] = Field(default_factory=list)
    contacts: list[Contact] = Field(default_factory=list)

    @property
    def pages_fetched(self) -> int:
        return len(self.pages)

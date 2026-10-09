"""The tables of the wholesale analysis, written to `<run>/analysis/` in every chosen format.
Like the run's own tables, each is a Pydantic model whose fields are its columns."""

from typing import ClassVar

from pydantic import Field

from ..tables import Row


class StoreAnalysisRow(Row):
    """One store: who it is, where, what it sells, and which segment it falls in."""

    table: ClassVar[str] = "stores"
    run_id: str
    domain: str
    url: str
    store_name: str = ""
    status: str  # the run's status: only `ok` stores were read
    # existing_customer | retail_partner | b2b_partner | competitor | not_a_fit |
    # not_relevant | not_read | unknown
    segment: str
    score: int | None = None  # 0-100 for retail and B2B partners: how good a fit
    reasons: list[str] = Field(default_factory=list)  # what decided the segment and score

    business_type: str = ""
    business_reason: str = ""
    b2b_hints: list[str] = Field(default_factory=list)  # phrases to check by hand
    store_type: str = ""  # multi_brand | own_brand | unknown

    relationship: str = ""  # existing_stockist | existing_account | carries_wooden_ships | ""
    matched_customer: str = ""
    match_method: str = ""  # domain | phone | name
    rep: str = ""
    territory: str = ""
    account_status: str = ""

    address: str = ""
    city: str = ""
    state: str = ""
    postal: str = ""
    country: str = ""
    location_source: str = ""  # input | site
    lat: float | None = None
    lng: float | None = None
    nearest_stockist: str = ""
    nearest_stockist_miles: float | None = None
    stockists_nearby: int | None = None  # within the territory radius

    platform: str = ""
    currency: str = ""
    product_count: int = 0
    knit_products: int = 0
    knit_garments: int = 0
    knit_accessories: int = 0
    knit_share: float | None = None  # knit_products / product_count
    knit_price_low: float | None = None  # 25th percentile, in the store's currency
    knit_price_median: float | None = None
    knit_price_high: float | None = None  # 75th percentile
    price_fit: str = ""  # below | fits | above | "" (unknown, or not in US dollars)
    price_ratio: float | None = None  # store's knit median / Wooden Ships retail
    brand_count: int = 0
    brands: list[str] = Field(default_factory=list)
    peer_brands: list[str] = Field(default_factory=list)  # from brands.csv
    competitor_brands: list[str] = Field(default_factory=list)
    carries_wooden_ships: bool = False
    on_sale_share: float | None = None
    in_stock_share: float | None = None
    newest_launch: str = ""
    main_materials: list[str] = Field(default_factory=list)  # in its knitwear, most first
    genders: list[str] = Field(default_factory=list)  # in its knitwear, most first

    emails: list[str] = Field(default_factory=list)
    phones: list[str] = Field(default_factory=list)
    instagram: list[str] = Field(default_factory=list)
    facebook: list[str] = Field(default_factory=list)
    wholesale_pages: list[str] = Field(default_factory=list)


class KnitAnalysisRow(Row):
    """One knitwear product of a readable store, with what it is made of and costs."""

    table: ClassVar[str] = "knit_products"
    run_id: str
    domain: str
    segment: str
    title: str
    vendor: str = ""
    knit_kind: str  # garment | accessory
    category: str = ""
    main_material: str = ""
    materials: list[str] = Field(default_factory=list)
    gender: str = ""
    price: float | None = None
    currency: str = ""
    compare_at: float | None = None
    on_sale: bool | None = None
    in_stock: bool | None = None
    launched: str = ""
    product_type: str = ""
    url: str = ""


class CompetitorRow(Row):
    """A store that sells its own label of knitwear."""

    table: ClassVar[str] = "competitors"
    run_id: str
    domain: str
    store_name: str = ""
    label: str = ""  # the vendor on most of its products
    city: str = ""
    state: str = ""
    knit_products: int = 0
    knit_price_low: float | None = None
    knit_price_median: float | None = None
    knit_price_high: float | None = None
    currency: str = ""
    price_ratio: float | None = None  # vs Wooden Ships retail
    main_materials: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    on_sale_share: float | None = None
    newest_launch: str = ""
    url: str = ""


class BrandRow(Row):
    """A brand and the stores that carry it: who stocks the peers of Wooden Ships."""

    table: ClassVar[str] = "brands"
    brand: str
    relation: str = ""  # peer | competitor | wooden_ships | ""
    stores: int = 0
    products: int = 0
    knit_products: int = 0
    store_domains: list[str] = Field(default_factory=list)


ANALYSIS_TABLES: dict[str, type[Row]] = {
    m.table: m for m in (StoreAnalysisRow, KnitAnalysisRow, CompetitorRow, BrandRow)
}

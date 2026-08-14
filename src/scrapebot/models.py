"""Shared data structures. No logic beyond trivial derived properties."""
from dataclasses import dataclass, field


@dataclass
class FetchResult:
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


@dataclass
class Product:
    title: str
    price: float | None
    product_type: str = ""
    tags: list[str] = field(default_factory=list)
    description: str = ""


@dataclass
class Page:
    url: str
    html: str
    text: str


@dataclass
class Target:
    """One store to scrape. `rows` are the original CSV rows sharing this domain."""
    domain: str
    url: str
    rows: list[dict] = field(default_factory=list)


@dataclass
class Acquired:
    """Everything gathered for one store."""
    domain: str
    source_used: str = "none"          # shopify_feed | sitemap | crawl | none
    products: list[Product] = field(default_factory=list)
    pages: list[Page] = field(default_factory=list)
    status: str = "ok"                 # ok | blocked | ssl_bypassed | error | js_required
    error: str = ""
    pages_fetched: int = 0

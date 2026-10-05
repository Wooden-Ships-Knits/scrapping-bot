"""What the model must return. instructor validates it and re-asks when it does not."""

from typing import Literal

from pydantic import BaseModel, Field


class ExtractedProduct(BaseModel):
    title: str = Field(description="The product name exactly as written on the page")
    price: str | None = Field(
        default=None, description="The price exactly as shown, e.g. '$98.00'; null if none"
    )
    currency: str | None = Field(
        default=None, description="ISO 4217 code only if the page states it; otherwise null"
    )
    vendor: str | None = Field(default=None, description="Brand or maker if shown; else null")
    source_url: str = Field(description="The URL of the page the product appears on")


class StoreExtraction(BaseModel):
    store_type: Literal["own_brand", "multi_brand", "unknown"] = Field(
        description="own_brand: sells mostly its own label; multi_brand: resells other brands"
    )
    products: list[ExtractedProduct] = Field(
        default_factory=list, description="Products for sale; empty if the pages list none"
    )
    brands_carried: list[str] = Field(default_factory=list)
    has_wholesale_page: bool = False
    confidence: float = Field(ge=0, le=1, description="How sure you are, 0 to 1")

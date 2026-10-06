import json
from pathlib import Path

from scrapebot.extract.feeds import (
    bigcartel_products,
    lightspeed_next_page,
    lightspeed_products,
    squarespace_products,
    woocommerce_products,
)
from scrapebot.extract.feeds import (
    shopify_products as products_from_shopify_feed,
)

FIXTURES = Path(__file__).parents[1] / "fixtures"
HTTP = FIXTURES / "http"


def test_products_from_shopify_feed_parses_real_response():
    data = json.loads((FIXTURES / "shopify_products.json").read_text())
    products = products_from_shopify_feed(data)

    assert len(products) == len(data["products"])
    first = products[0]
    assert first.title == data["products"][0]["title"]
    assert first.price is not None
    assert first.price > 0
    assert isinstance(first.tags, list)


def test_products_from_shopify_feed_uses_lowest_variant_price():
    data = {
        "products": [
            {
                "title": "Sweater",
                "product_type": "Knitwear",
                "tags": ["fall"],
                "body_html": "<p>Warm</p>",
                "variants": [{"price": "180.00"}, {"price": "120.00"}],
            }
        ]
    }
    p = products_from_shopify_feed(data)[0]
    assert p.price == 120.0
    assert p.price_raw == "120.00"


def test_shopify_feed_products_keep_text_and_the_full_source_object():
    """HTML is never stored as data (ADR 0006); the feed object is kept whole in `raw`."""
    raw = {
        "title": "Sweater",
        "handle": "cher-sweater",
        "vendor": "Wooden Ships",
        "body_html": "<p>Warm &amp; soft</p>",
        "variants": [{"price": "139.00"}],
    }
    p = products_from_shopify_feed(
        {"products": [raw]},
        base_url="https://x.com",
        evidence_url="https://x.com/products.json?limit=250&page=1",
    )[0]
    assert p.description == "Warm & soft"
    assert p.vendor == "Wooden Ships"
    assert p.url == "https://x.com/products/cher-sweater"
    assert p.source == "shopify_feed"
    assert p.evidence_url == "https://x.com/products.json?limit=250&page=1"
    assert p.raw == raw


def test_products_from_shopify_feed_tolerates_nulls_and_no_variants():
    data = {
        "products": [
            {"title": "No body", "body_html": None, "tags": None, "variants": []},
            {"title": None, "variants": [{"price": "10.00"}]},
        ]
    }
    products = products_from_shopify_feed(data)
    assert products[0].title == "No body"
    assert products[0].price is None
    assert products[1].title == ""


def test_products_from_shopify_feed_handles_empty_payload():
    assert products_from_shopify_feed({}) == []
    assert products_from_shopify_feed({"products": []}) == []


def test_woocommerce_store_api_real_response():
    """marilynhellman.com: prices in minor units, names with HTML entities."""
    data = json.loads(
        (HTTP / "marilynhellman.com-2026-10-05-woocommerce-products.json").read_text()
    )
    products = woocommerce_products(
        data, evidence_url="https://marilynhellman.com/wp-json/wc/store/v1/products"
    )
    assert len(products) == 3
    first = products[0]
    assert first.title == "Marilyn\u2019s Medium Size Pearl  Necklace", "entities are unescaped"
    assert (first.price_raw, first.price, first.currency) == ("22900", 229.0, "USD")
    assert first.url.startswith("https://marilynhellman.com/product/")
    assert "Accessories" in first.tags
    assert first.source == "woocommerce_feed"
    assert first.raw == data[0]


def test_squarespace_collection_real_response():
    """aaksonline.com: the cheapest priced variant gives the price, with its currency."""
    data = json.loads((HTTP / "aaksonline.com-2026-10-05-squarespace-shop.json").read_text())
    products = squarespace_products(data, "https://www.aaksonline.com", evidence_url="x")
    assert len(products) == len(data["items"])
    first = products[0]
    assert first.title == "LISI STRIPE"
    assert (first.price_raw, first.price, first.currency) == ("152.00", 152.0, "GBP")
    assert first.url == "https://www.aaksonline.com/shop/p/lisi-stripe"
    assert first.source == "squarespace_feed"


def test_squarespace_ignores_collections_that_are_not_stores():
    assert (
        squarespace_products({"collection": {"typeName": "page"}, "items": [{"title": "x"}]}, "o")
        == []
    )


def test_lightspeed_collection_real_response():
    """shopluxboutique.com: numeric prices, currency from the shop object, relative URLs."""
    data = json.loads(
        (HTTP / "shopluxboutique.com-2026-10-05-lightspeed-collection.json").read_text()
    )
    products = lightspeed_products(data, "https://www.shopluxboutique.com", evidence_url="x")
    assert len(products) == 16
    first = products[0]
    assert (first.title, first.price, first.currency) == ("Oz Stretch Belt", 98.0, "USD")
    assert first.url == "https://www.shopluxboutique.com/oz-stretch-belt.html"
    assert first.source == "lightspeed_feed"
    assert lightspeed_next_page(data) == 2


def test_bigcartel_products_real_response():
    """saysayboutique.bigcartel.com: one unpaged list, numeric prices, relative URLs."""
    data = json.loads((HTTP / "saysayboutique.bigcartel.com-2026-10-06-products.json").read_text())
    products = bigcartel_products(data, "https://saysayboutique.bigcartel.com", evidence_url="x")
    assert len(products) == len(data) == 320
    first = products[0]
    assert (first.title, first.price, first.price_raw) == (
        "Leopard Print Sheer Tights",
        24.0,
        "24.0",
    )
    assert first.url == "https://saysayboutique.bigcartel.com/product/leopard-print-sheer-tights"
    assert first.product_type == "Socks / Tights"
    assert first.currency == "", "the feed has no currency; the store's is stamped later"
    assert first.source == "bigcartel_feed"


def test_shopify_parser_ignores_a_list_payload():
    """bigcartel.com crashed the run: Big Cartel answers /products.json with a list."""
    data = json.loads((HTTP / "saysayboutique.bigcartel.com-2026-10-06-products.json").read_text())
    assert products_from_shopify_feed(data) == []


def test_every_feed_tolerates_garbage():
    for parse in (woocommerce_products,):
        assert parse(None) == []
        assert parse({"not": "a list"}) == []
    assert squarespace_products(None, "o") == []
    assert lightspeed_products({"collection": {"products": None}}, "o") == []
    assert bigcartel_products({"not": "a list"}, "o") == []
    assert bigcartel_products([None, {"price": 1}], "o") == []

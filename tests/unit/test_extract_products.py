import json
from pathlib import Path

from scrapebot.extract.products import products_from_jsonld, products_from_shopify_feed

FIXTURES = Path(__file__).parents[1] / "fixtures"


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


def test_products_from_jsonld_picks_product_blocks_only():
    html = (FIXTURES / "jsonld_product.html").read_text()
    products = products_from_jsonld(html)
    assert len(products) == 1
    assert products[0].title == "Ribbed Wool Cardigan"
    assert products[0].price == 248.0
    assert products[0].price_raw == "248.00"
    assert products[0].currency == "USD"
    assert products[0].source == "jsonld"


def test_jsonld_values_that_are_lists_or_objects_become_text():
    html = (
        '<script type="application/ld+json">{"@type": "Product", "name": ["Cardigan"], '
        '"brand": {"@type": "Brand", "name": "Acme"}, '
        '"offers": {"@type": "AggregateOffer", "lowPrice": 80, "priceCurrency": "usd"}}</script>'
    )
    [p] = products_from_jsonld(html, evidence_url="https://x.com/p/1")
    assert p.title == "Cardigan"
    assert p.vendor == "Acme"
    assert p.price == 80.0
    assert p.currency == "USD"
    assert p.evidence_url == "https://x.com/p/1"


def test_products_from_jsonld_survives_malformed_json():
    html = '<script type="application/ld+json">{not valid json</script>'
    assert products_from_jsonld(html) == []

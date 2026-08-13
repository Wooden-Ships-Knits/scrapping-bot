import json
from pathlib import Path

from scrapebot.extract import products_from_shopify_feed, products_from_jsonld

FIXTURES = Path(__file__).parent / "fixtures"


def test_products_from_shopify_feed_parses_real_response():
    data = json.loads((FIXTURES / "shopify_products.json").read_text())
    products = products_from_shopify_feed(data)

    assert len(products) == len(data["products"])
    first = products[0]
    assert first.title == data["products"][0]["title"]
    assert first.price is not None and first.price > 0
    assert isinstance(first.tags, list)


def test_products_from_shopify_feed_uses_lowest_variant_price():
    data = {"products": [{
        "title": "Sweater", "product_type": "Knitwear", "tags": ["fall"],
        "body_html": "<p>Warm</p>",
        "variants": [{"price": "180.00"}, {"price": "120.00"}],
    }]}
    p = products_from_shopify_feed(data)[0]
    assert p.price == 120.0
    assert p.description == "<p>Warm</p>"


def test_products_from_shopify_feed_tolerates_nulls_and_no_variants():
    data = {"products": [
        {"title": "No body", "body_html": None, "tags": None, "variants": []},
        {"title": None, "variants": [{"price": "10.00"}]},
    ]}
    products = products_from_shopify_feed(data)
    assert products[0].title == "No body" and products[0].price is None
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


def test_products_from_jsonld_survives_malformed_json():
    html = '<script type="application/ld+json">{not valid json</script>'
    assert products_from_jsonld(html) == []

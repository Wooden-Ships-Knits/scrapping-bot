import json
from pathlib import Path

from scrapebot.extract.structured import (
    app_state_products,
    bigcommerce_cards,
    opengraph_product,
    page_products,
    schema_products,
)

FIXTURES = Path(__file__).parents[1] / "fixtures"
HTTP = FIXTURES / "http"


def test_jsonld_picks_product_blocks_only():
    html = (FIXTURES / "jsonld_product.html").read_text()
    [product] = schema_products(html, "https://x.com/p/cardigan")
    assert product.title == "Ribbed Wool Cardigan"
    assert (product.price, product.price_raw, product.currency) == (248.0, "248.00", "USD")
    assert product.source == "jsonld"
    assert product.evidence_url == "https://x.com/p/cardigan"


def test_jsonld_survives_malformed_json():
    html = '<script type="application/ld+json">{not valid json</script>'
    assert schema_products(html, "https://x.com") == []


def test_jsonld_values_that_are_lists_or_objects_become_text():
    html = (
        '<script type="application/ld+json">{"@type": "Product", "name": ["Cardigan"], '
        '"brand": {"@type": "Brand", "name": "Acme"}, '
        '"offers": {"@type": "AggregateOffer", "lowPrice": 80, "priceCurrency": "usd"}}</script>'
    )
    [p] = schema_products(html, "https://x.com/p/1")
    assert (p.title, p.vendor, p.price, p.currency) == ("Cardigan", "Acme", 80.0, "USD")


def test_jsonld_products_nested_in_an_item_list():
    html = (
        '<script type="application/ld+json">{"@type": "ItemList", "itemListElement": ['
        '{"@type": "ListItem", "item": {"@type": "Product", "name": "A", "offers": {"price": "10"}}},'
        '{"@type": "ListItem", "item": {"@type": "Product", "name": "B", "offers": {"price": "20"}}}]}</script>'
    )
    assert [p.title for p in schema_products(html, "https://x.com")] == ["A", "B"]


def test_microdata_real_product_page():
    """wooloverslondon.com publishes Microdata only; v1 read nothing here."""
    html = (HTTP / "wooloverslondon.com-2026-10-05-product-microdata.html").read_text()
    products = page_products(html, "https://www.wooloverslondon.com/womens/cardigan/x")
    assert {p.source for p in products} == {"microdata"}
    titles = [p.title for p in products]
    assert "Pure Wool Aran Coatigan" in titles
    priced = next(p for p in products if p.title == "Cashmere Ruffle Cardigan")
    assert priced.price_raw == "85.00"


def test_rdfa_product():
    # No store in the 2026-10 sample used RDFa; this is the schema.org RDFa example form.
    html = """<div vocab="https://schema.org/" typeof="Product">
      <span property="name">Lambswool Crew</span>
      <div property="offers" typeof="Offer">
        <span property="price" content="120.00">$120</span>
        <meta property="priceCurrency" content="USD">
      </div></div>"""
    [p] = schema_products(html, "https://x.com/p/crew")
    assert (p.title, p.price_raw, p.currency, p.source) == (
        "Lambswool Crew",
        "120.00",
        "USD",
        "rdfa",
    )


def test_opengraph_real_shopify_product_page():
    html = (HTTP / "monkeesofnaples.com-2026-10-05-product-opengraph.html").read_text()
    url = "https://monkeesofnaples.com/products/london-dress-in-paisley"
    og = opengraph_product(html, url)
    assert og is not None
    assert (og.title, og.price_raw, og.currency, og.source) == (
        "London Dress in Paisley",
        "278.00",
        "USD",
        "opengraph",
    )
    assert [p.source for p in page_products(html, url)] == ["jsonld"], (
        "schema.org wins over OpenGraph"
    )


def test_opengraph_without_a_price_is_not_a_product():
    html = '<meta property="og:type" content="product"><meta property="og:title" content="X">'
    assert opengraph_product(html, "https://x.com") is None


NEXT_DATA = {
    "props": {
        "pageProps": {
            "products": [
                {
                    "id": 1,
                    "name": "Merino Crew",
                    "price": {"amount": "98.00", "currencyCode": "USD"},
                    "url": "https://x.com/p/merino-crew",
                },
                {"id": 2, "title": "Alpaca Cardigan", "price": 145, "slug": "alpaca-cardigan"},
                {"name": "Free shipping", "price": 0, "id": 3},
                {"name": "No id", "price": 10},
            ]
        }
    }
}


def test_app_state_next_data_products_are_flagged_for_review():
    # Synthetic: the stores that embed Next.js state all answered 403 to the bot.
    html = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(NEXT_DATA)}</script>'
    products = app_state_products(html, "https://x.com/collections/knit")
    assert [(p.title, p.price, p.currency) for p in products] == [
        ("Merino Crew", 98.0, "USD"),
        ("Alpaca Cardigan", 145.0, ""),
    ]
    assert all(p.needs_review and p.source == "app_state" for p in products)
    assert products[0].url == "https://x.com/p/merino-crew"
    assert products[1].url == "https://x.com/collections/knit", (
        "no absolute url: the page is the evidence"
    )


def test_wix_warmup_data_products_and_their_store_urls():
    """aldomartins.com (Wix Stores): the collection grid is in wix-warmup-data. Shape
    copied from the real page, trimmed to the fields that matter."""
    warmup = {
        "appsWarmupData": {
            "stores": {
                "category": {
                    "productsWithMetaData": {
                        "list": [
                            {
                                "id": "23a77f1d",
                                "name": "CHAQUETA JACQUARD FLORAL CUELLO MAO",
                                "price": 298,
                                "formattedPrice": "298,00€",
                                "sku": "80828",
                                "urlPart": "chaqueta-jacquard-floral-cuello-mao",
                            },
                            {
                                "id": "9b1c",
                                "name": "CHALECO JACQUARD FLORAL",
                                "price": 198,
                                "formattedPrice": "198,00€",
                                "sku": "80830",
                                "urlPart": "chaleco-jacquard-floral",
                            },
                        ]
                    }
                }
            }
        }
    }
    html = f'<script type="application/json" id="wix-warmup-data">{json.dumps(warmup)}</script>'
    products = page_products(html, "https://www.aldomartins.com/collection")
    assert [(p.title, p.price, p.source) for p in products] == [
        ("CHAQUETA JACQUARD FLORAL CUELLO MAO", 298.0, "app_state"),
        ("CHALECO JACQUARD FLORAL", 198.0, "app_state"),
    ]
    assert products[0].url == (
        "https://www.aldomartins.com/product-page/chaqueta-jacquard-floral-cuello-mao"
    )


def test_app_state_window_assignment():
    html = "<script>window.__INITIAL_STATE__ = {catalog: {items: [{sku: 'A1', title: 'Wool Hat', price: '35.00'}]}};</script>"
    assert [p.title for p in app_state_products(html, "https://x.com")] == ["Wool Hat"]


def test_page_without_structured_data_has_no_products():
    assert page_products("<html><body><h1>Shop</h1></body></html>", "https://x.com") == []


def test_bigcommerce_cornerstone_cards():
    """brocks.ca: a brand page with no structured data, only Stencil product cards."""
    html = (HTTP / "brocks.ca-2026-10-06-brand-page.html").read_text()
    products = page_products(html, "https://www.brocks.ca/brands/Birkenstock.html")
    assert len(products) == 12
    first = products[0]
    assert (first.title, first.price, first.price_raw, first.vendor) == (
        "ARIZONA BIG BUCKLE NARROW BF SANDCASTLE 1031429",
        170.0,
        "$170.00",
        "Birkenstock",
    )
    assert first.url == "https://www.brocks.ca/arizona-big-buckle-narrow-bf-sandcastle-1031429/"
    assert (first.source, first.currency) == ("bigcommerce_card", "")


def test_bigcommerce_cards_take_the_brand_not_the_location():
    """style-encore.com: brandName holds the franchise location; product-brand the brand."""
    html = (HTTP / "style-encore.com-2026-10-06-category.html").read_text()
    products = bigcommerce_cards(html, "https://style-encore.com/womens-tops/sweaters/")
    assert len(products) == 12
    first = products[0]
    assert (first.vendor, first.price, first.price_raw) == ("Tommy Hilfiger", 14.0, "$14.00")


def test_pages_without_bigcommerce_prices_have_no_cards():
    html = '<div class="card"><h3 class="card-title"><a href="/x">Team</a></h3></div>'
    assert bigcommerce_cards(html, "https://x.com") == []

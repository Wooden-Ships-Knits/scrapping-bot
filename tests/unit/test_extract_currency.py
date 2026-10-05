import json

from scrapebot.extract import detect_currency, products_from_jsonld

SHOPIFY_HOME = """<html><head><script>
Shopify.shop = "monkees.myshopify.com";
Shopify.locale = "en";
Shopify.currency = {"active":"USD","rate":"1.0"};
</script></head><body></body></html>"""


def jsonld(block):
    return f'<script type="application/ld+json">{json.dumps(block)}</script>'


def test_shopify_active_currency_is_read_from_the_theme_script():
    assert detect_currency(SHOPIFY_HOME) == ("USD", "shopify_js")


def test_opengraph_price_currency_meta():
    html = '<meta property="og:price:currency" content="cad">'
    assert detect_currency(html) == ("CAD", "meta")


def test_jsonld_offer_price_currency():
    html = jsonld(
        {"@type": "Product", "name": "Cardigan", "offers": {"price": "98", "priceCurrency": "EUR"}}
    )
    assert detect_currency(html) == ("EUR", "jsonld")


def test_unknown_currency_is_empty_not_guessed():
    assert detect_currency("<html><p>$98.00</p></html>") == ("", "")


def test_jsonld_products_carry_their_own_currency():
    html = jsonld(
        {"@type": "Product", "name": "Cardigan", "offers": {"price": "98", "priceCurrency": "GBP"}}
    )
    [product] = products_from_jsonld(html)
    assert product.currency == "GBP"

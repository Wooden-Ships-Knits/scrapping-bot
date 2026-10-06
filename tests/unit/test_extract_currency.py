import json

from scrapebot.extract.profile import detect_currency
from scrapebot.extract.structured import schema_products

SHOPIFY_HOME = """<html><head><script>
Shopify.shop = "monkees.myshopify.com";
Shopify.locale = "en";
Shopify.currency = {"active":"USD","rate":"1.0"};
</script></head><body></body></html>"""

BIGCARTEL_HOME = """<html><head><meta name="generator" content="Big Cartel" />
<script>
bigcartel.account = window.bigcartel.account || {}
bigcartel.account.currency = window.bigcartel.account.currency || "USD"
bigcartel.account.moneyFormat = "sign"
</script></head><body></body></html>"""


def jsonld(block):
    return f'<script type="application/ld+json">{json.dumps(block)}</script>'


def test_shopify_active_currency_is_read_from_the_theme_script():
    assert detect_currency(SHOPIFY_HOME) == ("USD", "shopify_js")


def test_bigcartel_account_currency_is_read_from_the_theme_script():
    assert detect_currency(BIGCARTEL_HOME) == ("USD", "bigcartel_js")


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
    [product] = schema_products(html, "https://x.com/p/1")
    assert product.currency == "GBP"

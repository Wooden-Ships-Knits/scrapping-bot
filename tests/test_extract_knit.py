from scrapebot.models import Product
from scrapebot.extract import knit_terms_in, product_blob, knit_products


def test_knit_terms_matches_whole_words_case_insensitively():
    assert knit_terms_in("Cher Sweater in Eggnog") == ["sweater"]
    assert knit_terms_in("Pop Posh Cotton CASHMERE Polo") == ["cashmere"]
    assert knit_terms_in("Ribbed Knit Cardigan") == ["knit", "cardigan"]


def test_knit_terms_does_not_match_substrings():
    # 'wool' must not fire on 'woolworths'; 'knit' must not fire on 'unknitted'
    # Regression: must still hold after the plural-matching fix below.
    assert knit_terms_in("Woolworths gift card") == []
    assert knit_terms_in("Unknitted") == []


def test_knit_terms_deduplicates_and_preserves_order():
    assert knit_terms_in("Knit sweater, knit cardigan") == ["knit", "sweater", "cardigan"]


def test_knit_terms_handles_empty_and_none():
    assert knit_terms_in("") == []
    assert knit_terms_in(None) == []


def test_product_blob_combines_fields_and_truncates_description():
    p = Product(
        title="Kailyn Dress",
        price=298.0,
        product_type="Dresses",
        tags=["spring", "knitwear"],
        description="x" * 900,
    )
    blob = product_blob(p)
    assert "Kailyn Dress" in blob and "Dresses" in blob and "knitwear" in blob
    assert len(blob) < 700, "description is truncated to 400 chars"


def test_product_blob_survives_none_fields():
    # Shopify feeds return null body_html — this crashed during reconnaissance.
    p = Product(title="Tee", price=20.0, description=None, tags=None, product_type=None)
    assert product_blob(p) == "Tee"


def test_knit_products_filters_and_keeps_the_product():
    items = [
        Product(title="Cher Sweater in Eggnog", price=139.0),
        Product(title="Leather Handbag", price=450.0),
        Product(title="Plain Tee", price=20.0, description="A soft merino blend."),
    ]
    hits = knit_products(items)
    assert [p.title for p in hits] == ["Cher Sweater in Eggnog", "Plain Tee"]


def test_knit_terms_matches_plural_product_type_categories():
    # Real Shopify product_type values are plural ("Sweaters", not "Sweater").
    # The regex must not undercount knitwear because of a missing trailing 's'.
    assert knit_terms_in("Sweaters") == ["sweater"]
    assert knit_terms_in("Cardigans") == ["cardigan"]
    assert knit_terms_in("Pullovers") == ["pullover"]
    assert knit_terms_in("SWEATERS") == ["sweater"]
    assert knit_terms_in("Sweaters & Sweatshirts") == ["sweater", "sweatshirt"]
    assert knit_terms_in("Sweater and sweaters") == ["sweater"]


def test_knit_terms_matches_real_world_plural_product_type_string():
    # Observed live on a prospect's Shopify feed.
    assert knit_terms_in("Shop All;Clothing/Tops; Clothing/Sweaters") == ["sweater"]


def test_knit_terms_does_not_match_substrings_after_plural_fix():
    assert knit_terms_in("Woolworths gift card") == []
    assert knit_terms_in("Unknitted") == []

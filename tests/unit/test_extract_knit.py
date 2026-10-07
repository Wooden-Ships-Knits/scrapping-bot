from scrapebot.extract.signals import knit_products, knit_terms_in, product_blob
from scrapebot.models import Product


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
    assert "Kailyn Dress" in blob
    assert "Dresses" in blob
    assert "knitwear" in blob
    assert len(blob) < 700, "description is truncated to 400 chars"


def test_product_blob_survives_none_fields():
    # Shopify feeds return null body_html — this crashed during reconnaissance.
    p = Product(title="Tee", price=20.0, description=None, tags=None, product_type=None)  # pyright: ignore[reportArgumentType]
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


# --- Fix A: description is raw body_html; strip markup before truncating ---


def test_product_blob_strips_html_tags_from_description():
    p = Product(title="Tee", price=None, description="<p>A soft <b>merino</b> blend.</p>")
    blob = product_blob(p)
    assert "merino" in blob
    assert "<" not in blob


def test_product_blob_unescapes_html_entities():
    p = Product(title="Tee", price=None, description="<p>Wool &amp; silk</p>")
    blob = product_blob(p)
    assert "Wool & silk" in blob


def test_product_blob_collapses_whitespace_runs():
    p = Product(title="Tee", price=None, description="<p>a</p>\n\n   <p>b</p>")
    blob = product_blob(p)
    assert "  " not in blob
    assert "a b" in blob


def test_product_blob_finds_knit_terms_hidden_behind_leading_markup():
    # First 400 RAW characters are entirely markup/attributes; the fabric line
    # ("92% merino wool") only appears after them. The OLD raw-truncation
    # behaviour would truncate before ever reaching the fabric line.
    filler_attr = "x" * 450
    raw_description = f'<div data-info="{filler_attr}">92% merino wool</div>'
    assert len(raw_description) > 400
    # Prove the old (broken) approach found nothing.
    assert knit_terms_in(raw_description[:400]) == []

    p = Product(title="Tee", price=None, description=raw_description)
    terms = knit_terms_in(product_blob(p))
    assert "merino" in terms
    assert "wool" in terms


def test_product_blob_still_truncates_plain_text_description_to_400():
    p = Product(title="", price=None, description="z" * 900)
    blob = product_blob(p)
    assert len(blob) == 400


# --- Fix B: weak terms ("wool", "shawl") alone on a woven-garment title don't count ---


def test_knit_products_rejects_weak_term_on_woven_coat():
    items = [Product(title="Wool Blend Plaid Reversible Coat", price=None)]
    assert knit_products(items) == []


def test_knit_products_rejects_weak_term_on_woven_pant():
    items = [Product(title="Avenue Pant - Hazelnut", price=None, description="wool blend")]
    assert knit_products(items) == []


def test_knit_products_keeps_strong_term_even_with_woven_style_title():
    items = [Product(title="Shawl Collar Cardigan", price=None)]
    hits = knit_products(items)
    assert [p.title for p in hits] == ["Shawl Collar Cardigan"]


def test_knit_products_keeps_strong_term_alongside_weak_term():
    items = [Product(title="Merino Wool Sweater", price=None)]
    hits = knit_products(items)
    assert [p.title for p in hits] == ["Merino Wool Sweater"]


def test_knit_products_keeps_weak_term_when_title_is_not_woven():
    items = [Product(title="Wool Wrap", price=None)]
    hits = knit_products(items)
    assert [p.title for p in hits] == ["Wool Wrap"]


# --- Fix A (round 2): "hat", "glove(s)", "sock(s)" were over-suppressing knit accessories ---


def test_knit_products_keeps_wool_gloves():
    items = [Product(title="Wool Gloves", price=None)]
    hits = knit_products(items)
    assert [p.title for p in hits] == ["Wool Gloves"]


def test_knit_products_keeps_wool_hat():
    items = [Product(title="Wool Hat", price=None)]
    hits = knit_products(items)
    assert [p.title for p in hits] == ["Wool Hat"]


def test_knit_products_keeps_wool_socks():
    items = [Product(title="Wool Socks", price=None)]
    hits = knit_products(items)
    assert [p.title for p in hits] == ["Wool Socks"]


def test_knit_products_still_rejects_genuinely_woven_titles():
    # Regression: removing hat/glove/sock must not weaken the rest of the guard.
    assert knit_products([Product(title="Wool Blend Plaid Reversible Coat", price=None)]) == []
    assert knit_products([Product(title="Avenue Pant - Hazelnut", price=None)]) == []
    # "vest" is deliberately KEPT in the woven list.
    assert knit_products([Product(title="Quilted Nylon Shawl-Neck Boxy Vest", price=None)]) == []


def test_knit_products_still_keeps_genuine_knitwear_regression():
    for title in ("Shawl Collar Cardigan", "Merino Wool Sweater", "Wool Wrap"):
        hits = knit_products([Product(title=title, price=None)])
        assert [p.title for p in hits] == [title]


# --- Fix B: <script>/<style> CONTENT must not leak into the searchable blob ---


def test_product_blob_excludes_script_content():
    p = Product(
        title="Plain Cotton Tee",
        price=None,
        description='<script>dataLayer.push({item_name:"Wool Peacoat"});</script><p>Soft cotton tee.</p>',
    )
    assert knit_terms_in(product_blob(p)) == []


def test_product_blob_excludes_style_content():
    p = Product(
        title="Plain Cotton Tee",
        price=None,
        description="<style>.sweater-badge{color:red}</style><p>Plain tee</p>",
    )
    assert knit_terms_in(product_blob(p)) == []


def test_product_blob_multiple_script_blocks_dont_swallow_real_text():
    p = Product(
        title="Tee",
        price=None,
        description="<script>a</script><p>Merino wool jumper</p><script>b</script>",
    )
    terms = knit_terms_in(product_blob(p))
    assert "merino" in terms
    assert "wool" in terms
    assert "jumper" in terms


def test_product_blob_still_cleans_genuine_description_text():
    p = Product(
        title="Tee", price=None, description="<p>A soft <b>merino</b> blend &amp; more.</p>"
    )
    blob = product_blob(p)
    assert "merino" in knit_terms_in(blob)
    assert "&" in blob


def test_is_knit_agrees_with_knit_products():
    from scrapebot.extract.signals import is_knit

    sweater = Product(title="Cher Sweater")
    wool_coat = Product(title="Wool Coat", tags=["wool"])
    dress = Product(title="Linen Dress")
    assert [is_knit(p) for p in (sweater, wool_coat, dress)] == [True, False, False]
    assert knit_products([sweater, wool_coat, dress]) == [sweater]

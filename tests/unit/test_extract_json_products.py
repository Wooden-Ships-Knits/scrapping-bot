from scrapebot.extract.json_products import captured_products

PAGE = "https://shop.com/women"


def test_a_list_of_named_priced_objects_is_a_catalogue():
    data = {
        "hits": [
            {"title": "Scarf", "price": "45.00", "url": "/p/scarf"},
            {"title": "Hat", "price": 20},
        ]
    }
    products = captured_products(data, "https://api.shop.com/search", PAGE)
    assert [(p.title, p.price, p.price_raw, p.url) for p in products] == [
        ("Scarf", 45.0, "45.00", "https://shop.com/p/scarf"),
        ("Hat", 20.0, "20", ""),
    ]
    assert all(p.needs_review and p.source == "render_json" for p in products)


def test_nested_price_objects_and_their_currency():
    data = [
        {"name": "Coat", "priceRange": {"min": {"amount": "310.00", "currency": "CAD"}}},
        {"name": "Vest", "priceRange": {"min": {"amount": "150.00", "currency": "CAD"}}},
    ]
    products = captured_products(data, "x", PAGE)
    assert [(p.title, p.price, p.currency) for p in products] == [
        ("Coat", 310.0, "CAD"),
        ("Vest", 150.0, "CAD"),
    ]


def test_one_priced_object_or_unpriced_lists_are_not_a_catalogue():
    assert captured_products({"cart": [{"name": "Scarf", "price": 45}]}, "x", PAGE) == []
    menu = {"menu": [{"name": "Women", "url": "/women"}, {"name": "Men", "url": "/men"}]}
    assert captured_products(menu, "x", PAGE) == []
    assert captured_products(None, "x", PAGE) == []
    assert captured_products("text", "x", PAGE) == []


def test_a_shopify_shaped_answer_uses_the_shopify_parser():
    data = {"products": [{"title": "Tee", "handle": "tee", "variants": [{"price": "25.00"}]}]}
    (product,) = captured_products(data, "https://shop.com/products.json", PAGE)
    assert (product.source, product.url, product.needs_review) == (
        "shopify_feed",
        "https://shop.com/products/tee",
        False,
    )


def test_prices_in_cents_on_the_variants():
    """ashleyhittboutique.com (CommentSold): /api/products prices each variant in cents."""
    data = {
        "data": [
            {
                "name": "Just On The Sunny Side Sweater",
                "url": "/product/38354",
                "variants": [
                    {"size": "S/M", "priceCents": 4600, "salePriceCents": None},
                    {"size": "L/XL", "priceCents": 4800, "salePriceCents": None},
                ],
            },
            {"name": "Mama Knit Hats", "variants": [{"priceCents": 1499}]},
        ]
    }
    products = captured_products(data, "https://ashleyhittboutique.com/api/products", PAGE)
    assert [(p.title, p.price, p.price_raw) for p in products] == [
        ("Just On The Sunny Side Sweater", 46.0, "4600"),
        ("Mama Knit Hats", 14.99, "1499"),
    ]

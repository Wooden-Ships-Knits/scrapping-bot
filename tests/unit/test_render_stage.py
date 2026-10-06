"""The browser stage of acquisition (ADR 0002), with a fake browser."""

import json

from scrapebot.acquire import acquire
from scrapebot.models import Target
from tests.fakes import FakeFetcher, FakeRenderer

ORIGIN = "https://spa.com"
SHELL = '<html><body><div id="root"></div><noscript>Enable JavaScript</noscript></body></html>'
WORDS = "Our boutique sells knitwear from small makers. " * 10


def rendered_home(*links):
    anchors = "".join(f'<a href="{href}">{text}</a>' for href, text in links)
    return f"<html><body><h1>Spa boutique</h1><p>{WORDS}</p>{anchors}</body></html>"


def product_page(name, price):
    block = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": name,
        "offers": {"@type": "Offer", "price": price, "priceCurrency": "EUR"},
    }
    return (
        f'<html><head><script type="application/ld+json">{json.dumps(block)}</script></head>'
        f"<body><h1>{name}</h1><p>{WORDS}</p></body></html>"
    )


def visit(fetcher_pages, renderer, **kwargs):
    return acquire(
        Target(domain="spa.com", url=ORIGIN),
        FakeFetcher(fetcher_pages),
        renderer=renderer,
        **kwargs,
    )


def test_a_javascript_shell_is_rendered_and_its_catalogue_followed():
    renderer = FakeRenderer(
        {
            ORIGIN: (
                200,
                rendered_home(("/collections/all", "Shop"), ("/products/scarf", "Scarf")),
            ),
            f"{ORIGIN}/collections/all": (200, rendered_home()),
            f"{ORIGIN}/products/scarf": (200, product_page("Wool scarf", "45.00")),
        }
    )
    got = visit({ORIGIN: (200, SHELL)}, renderer)

    assert renderer.calls[0] == ORIGIN
    assert set(renderer.calls) == {ORIGIN, f"{ORIGIN}/collections/all", f"{ORIGIN}/products/scarf"}
    assert (got.status, got.source_used) == ("ok", "render")
    assert [(p.title, p.price, p.currency) for p in got.products] == [("Wool scarf", 45.0, "EUR")]
    assert got.pages[0].via == "browser"
    assert "knitwear" in got.pages[0].text
    assert "render" in got.layers_tried


def test_products_are_read_from_the_json_the_page_loaded():
    items = [
        {"name": f"Cardigan {i}", "price": {"amount": "120.00", "currencyCode": "USD"}}
        for i in range(3)
    ]
    renderer = FakeRenderer(
        {ORIGIN: (200, rendered_home(), [(f"{ORIGIN}/api/products", {"data": {"list": items}})])}
    )
    got = visit({ORIGIN: (200, SHELL)}, renderer)

    assert got.status == "ok"
    assert [p.title for p in got.products] == ["Cardigan 0", "Cardigan 1", "Cardigan 2"]
    first = got.products[0]
    assert (first.price, first.currency, first.source) == (120.0, "USD", "render_json")
    assert first.needs_review, "a heuristic reading is marked for review"
    assert first.evidence_url == f"{ORIGIN}/api/products"


def test_a_known_feed_in_the_loaded_json_beats_the_heuristic():
    graphql = {
        "data": {
            "products": {
                "items": [
                    {
                        "name": "Merino jumper",
                        "url_key": "merino-jumper",
                        "price_range": {
                            "minimum_price": {"final_price": {"value": 99, "currency": "GBP"}}
                        },
                    }
                ]
            }
        }
    }
    renderer = FakeRenderer({ORIGIN: (200, rendered_home(), [(f"{ORIGIN}/graphql", graphql)])})
    got = visit({ORIGIN: (200, SHELL)}, renderer)

    (product,) = got.products
    assert (product.title, product.source, product.needs_review) == (
        "Merino jumper",
        "magento_feed",
        False,
    )


def test_a_challenge_in_the_browser_is_blocked_not_bypassed():
    renderer = FakeRenderer({}, challenge={ORIGIN: "cloudflare"})
    got = visit({ORIGIN: (200, SHELL)}, renderer)

    assert got.status == "blocked"
    assert got.error == "challenge page (cloudflare) in the browser"
    assert renderer.calls == [ORIGIN], "nothing else is tried after a refusal"
    assert got.pages[0].via == "http"


def test_a_browser_failure_leaves_the_store_js_required():
    got = visit({ORIGIN: (200, SHELL)}, FakeRenderer({}))
    assert got.status == "js_required"
    assert got.pages[0].via == "http"


def test_without_a_browser_a_shell_is_js_required():
    got = visit({ORIGIN: (200, SHELL)}, None)
    assert got.status == "js_required"
    assert "render" not in got.layers_tried


def test_a_store_with_a_feed_never_opens_the_browser():
    feed = json.dumps({"products": [{"title": "Hat", "variants": [{"price": "20.00"}]}]})
    renderer = FakeRenderer({})
    got = visit(
        {ORIGIN: (200, SHELL), f"{ORIGIN}/products.json?limit=250&page=1": (200, feed)}, renderer
    )
    assert got.source_used == "shopify_feed"
    assert renderer.calls == []


def test_a_readable_store_without_products_gets_a_few_listing_pages_rendered():
    links = "".join(f'<a href="/collections/c{i}">C{i}</a>' for i in range(6))
    home = f"<html><body><p>{WORDS}</p>{links}</body></html>"
    listing = f"<html><body><p>{WORDS}</p></body></html>"
    pages = {ORIGIN: (200, home)} | {f"{ORIGIN}/collections/c{i}": (200, listing) for i in range(6)}
    items = [{"title": "Beret", "price": 30}, {"title": "Mittens", "price": 25}]
    renderer = FakeRenderer(
        {f"{ORIGIN}/collections/c0": (200, listing, [(f"{ORIGIN}/api/grid", {"items": items})])}
    )
    got = visit(pages, renderer)

    assert len(renderer.calls) == 3, "a probe, not the whole site"
    assert [p.title for p in got.products] == ["Beret", "Mittens"]
    assert got.status == "ok"


def test_a_readable_homepage_without_links_is_rendered_for_the_links_scripts_add():
    home = f"<html><body><p>{WORDS}</p></body></html>"
    renderer = FakeRenderer(
        {
            ORIGIN: (200, rendered_home(("/products/scarf", "Scarf"))),
            f"{ORIGIN}/products/scarf": (200, product_page("Wool scarf", "45.00")),
        }
    )
    got = visit({ORIGIN: (200, home)}, renderer)
    assert renderer.calls == [ORIGIN, f"{ORIGIN}/products/scarf"]
    assert [p.title for p in got.products] == ["Wool scarf"]


def test_the_render_budget_is_respected():
    links = [(f"/products/p{i}", f"P{i}") for i in range(20)]
    renderer = FakeRenderer({ORIGIN: (200, rendered_home(*links))})
    visit({ORIGIN: (200, SHELL)}, renderer, render_pages=4)
    assert len(renderer.calls) == 4

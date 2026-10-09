import json
from pathlib import Path

from scrapebot.acquire import acquire
from scrapebot.acquire.discovery import link_role, rank_links, sitemap_urls
from scrapebot.acquire.feeds import shopify_feed as shopify_products
from scrapebot.models import Target
from tests.fakes import FakeFetcher

FIXTURES = Path(__file__).parents[1] / "fixtures" / "http"


def feed_page(n, start=0):
    return json.dumps(
        {
            "products": [
                {"title": f"Item {start + i}", "variants": [{"price": "10.00"}]} for i in range(n)
            ]
        }
    )


def test_shopify_products_paginates_until_empty():
    f = FakeFetcher(
        {
            "https://x.com/products.json?limit=250&page=1": (200, feed_page(250)),
            "https://x.com/products.json?limit=250&page=2": (200, feed_page(40, 250)),
            "https://x.com/products.json?limit=250&page=3": (200, json.dumps({"products": []})),
        }
    )
    products = shopify_products("https://x.com", f)
    assert len(products) == 290
    assert products[0].title == "Item 0"


def test_shopify_products_stops_at_page_cap():
    responses = {
        f"https://x.com/products.json?limit=250&page={p}": (200, feed_page(250, 250 * (p - 1)))
        for p in range(1, 12)
    }
    products = shopify_products("https://x.com", FakeFetcher(responses))
    assert len(products) == 2000, "2,000 products is the cap for every feed"


def test_shopify_products_returns_empty_for_non_shopify():
    assert shopify_products("https://x.com", FakeFetcher({})) == []


def test_shopify_products_ignores_html_served_at_the_feed_url():
    f = FakeFetcher({"https://x.com/products.json?limit=250&page=1": (200, "<html>404</html>")})
    assert shopify_products("https://x.com", f) == []


def test_sitemap_urls_follows_a_sitemap_index_and_reads_product_sitemaps_first():
    index = """<?xml version="1.0"?><sitemapindex>
      <sitemap><loc>https://x.com/sitemap_pages_1.xml</loc></sitemap>
      <sitemap><loc>https://x.com/sitemap_blogs_1.xml</loc></sitemap>
      <sitemap><loc>https://x.com/sitemap_products_1.xml</loc></sitemap>
    </sitemapindex>"""
    products = """<?xml version="1.0"?><urlset>
      <url><loc>https://x.com/products/knit-top</loc></url>
    </urlset>"""
    pages = """<?xml version="1.0"?><urlset>
      <url><loc>https://x.com/pages/about</loc></url>
      <url><loc>https://x.com/blogs/news/post</loc></url>
    </urlset>"""
    f = FakeFetcher(
        {
            "https://x.com/sitemap.xml": (200, index),
            "https://x.com/sitemap_products_1.xml": (200, products),
            "https://x.com/sitemap_pages_1.xml": (200, pages),
        }
    )
    found = sitemap_urls("https://x.com", f)
    assert found.products == ["https://x.com/products/knit-top"]
    assert found.pages.priority == ["https://x.com/pages/about"]
    assert "https://x.com/sitemap_blogs_1.xml" not in f.calls, "blog sitemaps are skipped"
    assert f.calls.index("https://x.com/sitemap_products_1.xml") < f.calls.index(
        "https://x.com/sitemap_pages_1.xml"
    )


def test_sitemap_urls_reads_a_urlset_that_lists_other_sitemaps():
    """Seen on wooloverslondon.com and purecollection.com."""
    fixture = (FIXTURES / "wooloverslondon.com-2026-10-05-sitemap.xml").read_text()
    child = "<urlset><url><loc>https://www.wooloverslondon.com/womens/cardigan/aran-41518</loc></url></urlset>"
    f = FakeFetcher(
        {
            "https://www.wooloverslondon.com/sitemap.xml": (200, fixture),
            "https://www.wooloverslondon.com/products-sitemap.xml": (200, child),
        }
    )
    found = sitemap_urls("https://www.wooloverslondon.com", f)
    assert found.products == ["https://www.wooloverslondon.com/womens/cardigan/aran-41518"]


def test_sitemap_urls_ignores_an_html_page_served_as_the_sitemap():
    """Seen on tracynegoshian.com and yesirosefashion.com: status 200, but HTML."""
    f = FakeFetcher(
        {"https://x.com/sitemap.xml": (200, "<!DOCTYPE html><html>Page not found</html>")}
    )
    assert sitemap_urls("https://x.com", f).found is False


def test_sitemaps_declared_in_robots_are_read_first():
    body = "<urlset><url><loc>https://x.com/products/a</loc></url></urlset>"
    f = FakeFetcher({"https://x.com/custom-products.xml": (200, body)})
    found = sitemap_urls("https://x.com", f, declared=["https://x.com/custom-products.xml"])
    assert found.products == ["https://x.com/products/a"]
    assert f.calls[0] == "https://x.com/custom-products.xml"


def test_rank_links_uses_url_and_link_text_and_drops_irrelevant_links():
    home = """<html><body>
      <a href="/collections/sweaters">Shop Sweaters</a>
      <a href="/pages/about">About</a>
      <a href="/blogs/news/hello">Blog</a>
      <a href="/info/hello">Get in touch: Contact us</a>
      <a href="/products/cher-sweater">Cher</a>
      <a href="/gift-guide">Gift guide</a>
    </body></html>"""
    ranked = rank_links(home, "https://x.com", "x.com")
    assert ranked.priority == ["https://x.com/pages/about", "https://x.com/info/hello"]
    assert ranked.product == ["https://x.com/products/cher-sweater"]
    assert ranked.collection == ["https://x.com/collections/sweaters"]
    assert ranked.other == ["https://x.com/gift-guide"]
    assert link_role("https://x.com/blogs/news/hello") == "skip"


def test_acquire_caps_pages_per_store():
    links = "".join(f'<a href="/products/p{i}">p{i}</a>' for i in range(60))
    home = f"<html><body>{links}</body></html>"
    responses = {"https://x.com": (200, home)}
    responses.update({f"https://x.com/products/p{i}": (200, "<p>p</p>") for i in range(60)})
    got = acquire(Target(domain="x.com", url="https://x.com"), FakeFetcher(responses))
    assert got.pages_fetched == 25


def test_acquire_prefers_the_shopify_feed_and_skips_crawling():
    f = FakeFetcher(
        {
            "https://x.com": (200, "<html>cdn.shopify.com</html>"),
            "https://x.com/products.json?limit=250&page=1": (200, feed_page(3)),
            "https://x.com/products.json?limit=250&page=2": (200, json.dumps({"products": []})),
        }
    )
    got = acquire(Target(domain="x.com", url="https://x.com"), f)
    assert got.source_used == "shopify_feed"
    assert len(got.products) == 3
    assert got.status == "ok"


def test_acquire_marks_blocked_when_homepage_is_403():
    f = FakeFetcher({"https://x.com": (403, "")})
    got = acquire(Target(domain="x.com", url="https://x.com"), f)
    assert got.status == "blocked"


def test_acquire_marks_js_required_when_pages_load_but_no_products_found():
    f = FakeFetcher({"https://x.com": (200, "<html><body><div id='root'></div></body></html>")})
    got = acquire(Target(domain="x.com", url="https://x.com"), f)
    assert got.status == "js_required"
    assert got.pages_fetched >= 1


def test_acquire_keeps_ssl_bypassed_as_a_flag_beside_the_read_status():
    """A site fetched with TLS verification disabled must stay visibly flagged,
    while the status still says what reading the site produced."""

    class SslFetcher(FakeFetcher):
        def get(self, url):
            res = super().get(url)
            if url == "https://x.com":
                res.ssl_bypassed = True
            return res

    f = SslFetcher({"https://x.com": (200, "<html><body><div id='root'></div></body></html>")})
    got = acquire(Target(domain="x.com", url="https://x.com"), f)
    assert got.ssl_bypassed is True
    assert got.status == "js_required"


def test_acquire_marks_no_products_when_a_readable_site_has_no_catalogue():
    """Issue 2: a readable site without products must not look like `ok`."""
    home = "<html><body><h1>Welcome</h1><p>" + "A boutique in Naples. " * 30 + "</p></body></html>"
    got = acquire(
        Target(domain="x.com", url="https://x.com"), FakeFetcher({"https://x.com": (200, home)})
    )
    assert got.status == "no_products"
    assert got.products == []


def test_acquire_never_reports_ok_with_zero_products():
    pages = {
        "https://x.com": (
            200,
            "<html><body><p>" + "Hand-picked gifts. " * 40 + "</p></body></html>",
        ),
    }
    got = acquire(Target(domain="x.com", url="https://x.com"), FakeFetcher(pages))
    assert not (got.status == "ok" and not got.products)


def test_acquire_records_store_currency_and_stamps_feed_products():
    """Issue 3: a price without a currency lets a localised price in silently."""
    home = '<html><script>Shopify.currency = {"active":"CAD","rate":"1.0"};</script>cdn.shopify.com</html>'
    f = FakeFetcher(
        {
            "https://x.com": (200, home),
            "https://x.com/products.json?limit=250&page=1": (200, feed_page(2)),
        }
    )
    got = acquire(Target(domain="x.com", url="https://x.com"), f)
    assert (got.currency, got.currency_source) == ("CAD", "shopify_js")
    assert {p.currency for p in got.products} == {"CAD"}


def test_acquire_fetches_deep_links_from_the_input_as_priority_pages():
    """PRD IN-05: a product link marks the store and its page is fetched too."""
    product_page = (
        '<script type="application/ld+json">{"@type": "Product", "name": "Fisherman Sweater", '
        '"offers": {"price": "210.00", "priceCurrency": "USD"}}</script>'
    )
    f = FakeFetcher(
        {
            "https://x.com": (200, "<html><body><p>" + "Boutique. " * 40 + "</p></body></html>"),
            "https://x.com/p/fisherman": (200, product_page),
        }
    )
    target = Target(domain="x.com", url="https://x.com", deep_links=["https://x.com/p/fisherman"])
    got = acquire(target, f)
    assert "https://x.com/p/fisherman" in [p.url for p in got.pages]
    assert [p.title for p in got.products] == ["Fisherman Sweater"]
    assert got.products[0].evidence_url == "https://x.com/p/fisherman"
    assert got.layers_tried[:3] == ["homepage", "shopify_feed", "priority_pages"]


def test_acquire_records_every_layer_it_tried():
    f = FakeFetcher(
        {"https://x.com": (200, "<html><body><p>" + "Hi. " * 80 + "</p></body></html>")}
    )
    got = acquire(Target(domain="x.com", url="https://x.com"), f)
    assert got.layers_tried == ["homepage", "shopify_feed", "sitemap", "crawl", "structured"]


def test_acquire_keeps_contacts_with_the_page_they_were_found_on():
    home = (
        '<html><body><a href="/pages/contact">Contact</a>'
        + "<p>Boutique.</p>" * 40
        + "</body></html>"
    )
    contact = '<a href="mailto:hello@x.com">Mail</a> <a href="https://instagram.com/xshop">IG</a>'
    f = FakeFetcher({"https://x.com": (200, home), "https://x.com/pages/contact": (200, contact)})
    got = acquire(Target(domain="x.com", url="https://x.com"), f)
    found = {(c.type, c.value, c.source_url) for c in got.contacts}
    assert ("email", "hello@x.com", "https://x.com/pages/contact") in found
    assert ("instagram", "https://instagram.com/xshop", "https://x.com/pages/contact") in found
    kinds = {p.url: p.kind for p in got.pages}
    assert kinds == {"https://x.com": "home", "https://x.com/pages/contact": "contact"}


def test_acquire_reports_the_http_status_when_blocked():
    got = acquire(
        Target(domain="x.com", url="https://x.com"), FakeFetcher({"https://x.com": (429, "")})
    )
    assert (got.status, got.error) == ("blocked", "HTTP 429")


def test_acquire_does_not_fetch_www_and_bare_host_variants_twice():
    """Seen on a real store: links to www. and bare hosts wasted the page budget on repeats."""
    home = (
        '<html><body><a href="https://yesi.com/">Home</a>'
        '<a href="https://www.yesi.com/collections">All</a>'
        '<a href="https://yesi.com/collections/">All again</a>'
        "<p>" + "Boutique. " * 40 + "</p></body></html>"
    )
    f = FakeFetcher(
        {
            "https://www.yesi.com": (200, home),
            "https://www.yesi.com/collections": (200, "<p>c</p>"),
            "https://yesi.com/collections": (200, "<p>c</p>"),
            "https://yesi.com": (200, home),
        }
    )
    got = acquire(Target(domain="yesi.com", url="https://www.yesi.com"), f)
    assert [p.url for p in got.pages] == [
        "https://www.yesi.com",
        "https://www.yesi.com/collections",
    ]


def test_acquire_uses_the_woocommerce_store_api_on_woocommerce_sites():
    data = (FIXTURES / "marilynhellman.com-2026-10-05-woocommerce-products.json").read_text()
    home = (
        '<html><link href="/wp-content/plugins/woocommerce/x.css">'
        + "<p>Shop.</p>" * 50
        + "</html>"
    )
    f = FakeFetcher(
        {
            "https://marilynhellman.com": (200, home),
            "https://marilynhellman.com/wp-json/wc/store/v1/products?per_page=100&page=1": (
                200,
                data,
            ),
        }
    )
    got = acquire(Target(domain="marilynhellman.com", url="https://marilynhellman.com"), f)
    assert (got.platform, got.source_used, got.status) == ("woocommerce", "woocommerce_feed", "ok")
    assert len(got.products) == 3
    assert {p.currency for p in got.products} == {"USD"}
    assert not any("products.json" in url for url in f.calls), "no Shopify probe on WooCommerce"


def test_acquire_uses_the_squarespace_collection_json():
    data = (FIXTURES / "aaksonline.com-2026-10-05-squarespace-shop.json").read_text()
    home = '<html><script src="https://static1.squarespace.com/x.js"></script><a href="/shop/p/lisi-stripe">Lisi</a></html>'
    f = FakeFetcher(
        {
            "https://www.aaksonline.com": (200, home),
            "https://www.aaksonline.com/shop?format=json": (200, data),
        }
    )
    got = acquire(Target(domain="aaksonline.com", url="https://www.aaksonline.com"), f)
    assert (got.source_used, got.status) == ("squarespace_feed", "ok")
    assert got.products[0].currency == "GBP"
    assert got.currency == "GBP", "the store currency follows the feed when the page has none"


def test_acquire_uses_the_lightspeed_collection_json():
    data = (FIXTURES / "shopluxboutique.com-2026-10-05-lightspeed-collection.json").read_text()
    home = '<html><script src="https://cdn.shoplightspeed.com/assets/gui.js"></script></html>'
    f = FakeFetcher(
        {
            "https://www.shopluxboutique.com": (200, home),
            "https://www.shopluxboutique.com/collection/?format=json&limit=100": (200, data),
        }
    )
    got = acquire(Target(domain="shopluxboutique.com", url="https://www.shopluxboutique.com"), f)
    assert (got.platform, got.source_used) == ("lightspeed", "lightspeed_feed")
    assert len(got.products) == 16


BIGCARTEL_FEED = FIXTURES / "saysayboutique.bigcartel.com-2026-10-06-products.json"


def test_acquire_uses_the_bigcartel_feed_with_the_store_currency():
    home = (
        '<meta name="generator" content="Big Cartel" /><script>'
        'bigcartel.account.currency = window.bigcartel.account.currency || "USD"</script>'
    )
    origin = "https://saysayboutique.bigcartel.com"
    f = FakeFetcher(
        {origin: (200, home), f"{origin}/products.json": (200, BIGCARTEL_FEED.read_text())}
    )
    got = acquire(Target(domain="saysayboutique.bigcartel.com", url=origin), f)
    assert (got.platform, got.source_used, got.status) == ("bigcartel", "bigcartel_feed", "ok")
    assert len(got.products) == 320
    assert (got.currency, got.currency_source) == ("USD", "bigcartel_js")
    assert {p.currency for p in got.products} == {"USD"}


def test_a_list_at_the_shopify_feed_path_is_not_an_error():
    """An undetected Big Cartel store gets the Shopify probe; it must not crash."""
    origin = "https://shop.example.com"
    f = FakeFetcher(
        {
            origin: (200, "<html><body>" + "words " * 100 + "</body></html>"),
            f"{origin}/products.json?limit=250&page=1": (200, BIGCARTEL_FEED.read_text()),
        }
    )
    got = acquire(Target(domain="example.com", url=origin), f)
    assert got.status != "error"
    assert "shopify_feed" in got.layers_tried


def test_acquire_reads_a_magento_pwa_through_its_graphql_api():
    """plazafashionstore.com was `js_required`: its pages are an empty React shell."""
    from urllib.parse import urlencode

    from scrapebot.acquire.feeds import MAGENTO_PAGE_SIZE, MAGENTO_QUERY

    origin = "https://plazafashionstore.com"
    page1 = f"{origin}/graphql?" + urlencode({"query": MAGENTO_QUERY % (MAGENTO_PAGE_SIZE, 1)})
    f = FakeFetcher(
        {
            origin: (200, (FIXTURES / "plazafashionstore.com-2026-10-06-home.html").read_text()),
            page1: (
                200,
                (FIXTURES / "plazafashionstore.com-2026-10-06-magento-graphql.json").read_text(),
            ),
        }
    )
    got = acquire(Target(domain="plazafashionstore.com", url=origin), f)
    assert (got.platform, got.source_used, got.status) == ("magento", "magento_feed", "ok")
    assert len(got.products) == 100, "page 2 is missing here, so the feed stops after page 1"
    assert got.currency == "EUR"


def test_feed_stores_still_get_their_contact_and_wholesale_pages():
    """Issue 7: v1 visited only the homepage of a Shopify store."""
    home = (
        "<html>cdn.shopify.com<a href='/pages/contact'>Contact</a>"
        "<a href='/pages/wholesale'>Wholesale</a><a href='/collections/all'>Shop</a></html>"
    )
    f = FakeFetcher(
        {
            "https://x.com": (200, home),
            "https://x.com/products.json?limit=250&page=1": (200, feed_page(3)),
            "https://x.com/pages/contact": (200, '<a href="mailto:hi@x.com">mail</a>'),
            "https://x.com/pages/wholesale": (200, "<p>Wholesale enquiries welcome</p>"),
        }
    )
    got = acquire(Target(domain="x.com", url="https://x.com"), f)
    assert got.source_used == "shopify_feed"
    assert {p.kind for p in got.read_pages} == {"home", "contact", "wholesale"}
    assert ("email", "hi@x.com") in {(c.type, c.value) for c in got.contacts}
    assert "https://x.com/collections/all" not in f.calls, "no discovery once the feed answered"


def test_pages_that_fail_are_recorded_with_the_reason():
    """Issue 8: a broken contact page must be visible, not silently dropped."""
    home = "<html><a href='/pages/contact'>Contact</a>" + "<p>Boutique.</p>" * 40 + "</html>"
    f = FakeFetcher({"https://x.com": (200, home)})
    got = acquire(Target(domain="x.com", url="https://x.com"), f)
    failed = [p for p in got.pages if not p.ok]
    assert [(p.url, p.http_status, p.error) for p in failed] == [
        ("https://x.com/pages/contact", 404, "HTTP 404")
    ]
    assert got.pages_fetched == 1


def test_a_challenge_page_on_the_homepage_means_blocked():
    class ChallengeFetcher(FakeFetcher):
        def get(self, url):
            res = super().get(url)
            res.challenge = "cloudflare"
            return res

    got = acquire(
        Target(domain="x.com", url="https://x.com"), ChallengeFetcher({"https://x.com": (403, "")})
    )
    assert (got.status, got.error) == ("blocked", "challenge page (cloudflare)")


def test_crawl_goes_two_levels_to_reach_product_pages():
    home = (
        "<html><a href='/collections/knitwear'>Knitwear</a>" + "<p>Boutique.</p>" * 40 + "</html>"
    )
    collection = "<html><a href='/products/fisherman'>Fisherman</a></html>"
    product = (
        '<script type="application/ld+json">{"@type": "Product", "name": "Fisherman Sweater", '
        '"offers": {"price": "210.00", "priceCurrency": "USD"}}</script>'
    )
    f = FakeFetcher(
        {
            "https://x.com": (200, home),
            "https://x.com/collections/knitwear": (200, collection),
            "https://x.com/products/fisherman": (200, product),
        }
    )
    got = acquire(Target(domain="x.com", url="https://x.com"), f)
    assert "crawl_depth_2" in got.layers_tried
    assert [p.title for p in got.products] == ["Fisherman Sweater"]


def test_microdata_store_reached_through_its_product_sitemap():
    """wooloverslondon.com: v1 found nothing; M2 reads its product sitemap and Microdata."""
    sitemap = (FIXTURES / "wooloverslondon.com-2026-10-05-sitemap.xml").read_text()
    products_sitemap = "<urlset><url><loc>https://www.wooloverslondon.com/womens/cardigan/aran-41518</loc></url></urlset>"
    page = (FIXTURES / "wooloverslondon.com-2026-10-05-product-microdata.html").read_text()
    f = FakeFetcher(
        {
            "https://www.wooloverslondon.com": (
                200,
                "<html>" + "<p>Knitwear.</p>" * 40 + "</html>",
            ),
            "https://www.wooloverslondon.com/sitemap.xml": (200, sitemap),
            "https://www.wooloverslondon.com/products-sitemap.xml": (200, products_sitemap),
            "https://www.wooloverslondon.com/womens/cardigan/aran-41518": (200, page),
        }
    )
    got = acquire(Target(domain="wooloverslondon.com", url="https://www.wooloverslondon.com"), f)
    assert (got.status, got.source_used) == ("ok", "sitemap")
    assert {p.source for p in got.products} == {"microdata"}
    assert got.currency == "", "this page leaves priceCurrency empty: unknown, never guessed"


def test_exact_repeats_of_a_product_are_dropped_but_sources_are_not_merged():
    from scrapebot.acquire import dedupe_products
    from scrapebot.models import Product

    a = Product(title="Crew", price_raw="98", url="https://x.com/p/crew", source="jsonld")
    b = Product(title="Crew", price_raw="98", url="https://x.com/p/crew", source="microdata")
    assert dedupe_products([a, a.model_copy(), b]) == [a, b]


def test_a_rate_limited_feed_page_makes_the_store_rate_limited():
    """Roadmap issue 16: what was read is incomplete, so the store is visited again."""
    from scrapebot.models import FetchResult

    class Limited(FakeFetcher):
        def get(self, url):
            if "products.json" in url:
                return FetchResult(
                    url=url,
                    status_code=None,
                    body="",
                    final_url=url,
                    error="rate_limited: cooling down",
                    rate_limited=True,
                )
            return super().get(url)

    shopify_home = '<script>Shopify.currency = {"active":"USD"};</script>cdn.shopify.com'
    got = acquire(
        Target(domain="x.com", url="https://x.com"), Limited({"https://x.com": (200, shopify_home)})
    )
    assert got.status == "rate_limited"

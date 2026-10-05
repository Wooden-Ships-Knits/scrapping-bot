import json

from scrapebot.acquire import acquire
from scrapebot.acquire.discovery import crawl_urls, sitemap_urls
from scrapebot.acquire.feeds import shopify_products
from scrapebot.models import Target
from tests.fakes import FakeFetcher


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
    assert len(products) == 2000, "8 pages x 250 is the cap"


def test_shopify_products_returns_empty_for_non_shopify():
    assert shopify_products("https://x.com", FakeFetcher({})) == []


def test_shopify_products_ignores_html_served_at_the_feed_url():
    f = FakeFetcher({"https://x.com/products.json?limit=250&page=1": (200, "<html>404</html>")})
    assert shopify_products("https://x.com", f) == []


def test_sitemap_urls_follows_a_sitemap_index_one_level():
    index = """<?xml version="1.0"?><sitemapindex>
      <sitemap><loc>https://x.com/sitemap_products_1.xml</loc></sitemap>
    </sitemapindex>"""
    child = """<?xml version="1.0"?><urlset>
      <url><loc>https://x.com/products/knit-top</loc></url>
      <url><loc>https://x.com/pages/about</loc></url>
      <url><loc>https://x.com/blogs/news/post</loc></url>
    </urlset>"""
    f = FakeFetcher(
        {
            "https://x.com/sitemap.xml": (200, index),
            "https://x.com/sitemap_products_1.xml": (200, child),
        }
    )
    urls = sitemap_urls("https://x.com", f)
    assert "https://x.com/products/knit-top" in urls
    assert "https://x.com/pages/about" in urls
    assert "https://x.com/blogs/news/post" not in urls, "blog posts are not relevant"


def test_sitemap_urls_caps_the_result():
    body = (
        "<urlset>"
        + "".join(f"<url><loc>https://x.com/products/p{i}</loc></url>" for i in range(200))
        + "</urlset>"
    )
    urls = sitemap_urls("https://x.com", FakeFetcher({"https://x.com/sitemap.xml": (200, body)}))
    assert len(urls) <= 25


def test_sitemap_urls_puts_contact_pages_before_bulk_product_pages():
    """A store with thousands of product URLs must not crowd out its contact page."""
    locs = "".join(f"<url><loc>https://x.com/products/p{i}</loc></url>" for i in range(300))
    locs += "<url><loc>https://x.com/pages/contact</loc></url>"
    locs += "<url><loc>https://x.com/pages/about</loc></url>"
    body = f"<urlset>{locs}</urlset>"
    urls = sitemap_urls("https://x.com", FakeFetcher({"https://x.com/sitemap.xml": (200, body)}))
    assert "https://x.com/pages/contact" in urls, "contact page must survive the cap"
    assert "https://x.com/pages/about" in urls
    assert urls.index("https://x.com/pages/contact") < urls.index("https://x.com/products/p0")


def test_crawl_urls_prioritises_relevant_links_and_drops_irrelevant_ones():
    home = """<html><body>
      <a href="/collections/sweaters">Shop Sweaters</a>
      <a href="/pages/about">About</a>
      <a href="/blogs/news/hello">Blog</a>
      <a href="/pages/contact">Contact</a>
      <a href="/gift-guide">Gift guide</a>
    </body></html>"""
    urls = crawl_urls(home, "https://x.com", "x.com")
    assert urls[:2] == ["https://x.com/pages/about", "https://x.com/pages/contact"]
    assert "https://x.com/blogs/news/hello" not in urls, "blogs are dropped"
    assert urls[-1] == "https://x.com/gift-guide", "other links come last"


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
    assert got.layers_tried[:3] == ["homepage", "deep_links", "shopify_feed"]


def test_acquire_records_every_layer_it_tried():
    f = FakeFetcher(
        {"https://x.com": (200, "<html><body><p>" + "Hi. " * 80 + "</p></body></html>")}
    )
    got = acquire(Target(domain="x.com", url="https://x.com"), f)
    assert got.layers_tried == ["homepage", "shopify_feed", "sitemap", "crawl", "jsonld"]


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

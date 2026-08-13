import json

from scrapebot.models import FetchResult, Target
from scrapebot.sources import shopify_products, sitemap_urls, crawl_pages, acquire


class FakeFetcher:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        entry = self.responses.get(url)
        if entry is None:
            return FetchResult(url=url, status_code=404, body="", final_url=url)
        status, body = entry
        return FetchResult(url=url, status_code=status, body=body, final_url=url)


def feed_page(n, start=0):
    return json.dumps({"products": [
        {"title": f"Item {start+i}", "variants": [{"price": "10.00"}]} for i in range(n)
    ]})


def test_shopify_products_paginates_until_empty():
    f = FakeFetcher({
        "https://x.com/products.json?limit=250&page=1": (200, feed_page(250)),
        "https://x.com/products.json?limit=250&page=2": (200, feed_page(40, 250)),
        "https://x.com/products.json?limit=250&page=3": (200, json.dumps({"products": []})),
    })
    products = shopify_products("x.com", f)
    assert len(products) == 290
    assert products[0].title == "Item 0"


def test_shopify_products_stops_at_page_cap():
    responses = {
        f"https://x.com/products.json?limit=250&page={p}": (200, feed_page(250, 250 * (p - 1)))
        for p in range(1, 12)
    }
    products = shopify_products("x.com", FakeFetcher(responses))
    assert len(products) == 2000, "8 pages x 250 is the cap"


def test_shopify_products_returns_empty_for_non_shopify():
    assert shopify_products("x.com", FakeFetcher({})) == []


def test_shopify_products_ignores_html_served_at_the_feed_url():
    f = FakeFetcher({"https://x.com/products.json?limit=250&page=1": (200, "<html>404</html>")})
    assert shopify_products("x.com", f) == []


def test_sitemap_urls_follows_a_sitemap_index_one_level():
    index = """<?xml version="1.0"?><sitemapindex>
      <sitemap><loc>https://x.com/sitemap_products_1.xml</loc></sitemap>
    </sitemapindex>"""
    child = """<?xml version="1.0"?><urlset>
      <url><loc>https://x.com/products/knit-top</loc></url>
      <url><loc>https://x.com/pages/about</loc></url>
      <url><loc>https://x.com/blogs/news/post</loc></url>
    </urlset>"""
    f = FakeFetcher({
        "https://x.com/sitemap.xml": (200, index),
        "https://x.com/sitemap_products_1.xml": (200, child),
    })
    urls = sitemap_urls("x.com", f)
    assert "https://x.com/products/knit-top" in urls
    assert "https://x.com/pages/about" in urls
    assert "https://x.com/blogs/news/post" not in urls, "blog posts are not relevant"


def test_sitemap_urls_caps_the_result():
    body = "<urlset>" + "".join(
        f"<url><loc>https://x.com/products/p{i}</loc></url>" for i in range(200)
    ) + "</urlset>"
    urls = sitemap_urls("x.com", FakeFetcher({"https://x.com/sitemap.xml": (200, body)}))
    assert len(urls) <= 25


def test_sitemap_urls_puts_contact_pages_before_bulk_product_pages():
    """A store with thousands of product URLs must not crowd out its contact page."""
    locs = "".join(f"<url><loc>https://x.com/products/p{i}</loc></url>" for i in range(300))
    locs += "<url><loc>https://x.com/pages/contact</loc></url>"
    locs += "<url><loc>https://x.com/pages/about</loc></url>"
    body = f"<urlset>{locs}</urlset>"
    urls = sitemap_urls("x.com", FakeFetcher({"https://x.com/sitemap.xml": (200, body)}))
    assert "https://x.com/pages/contact" in urls, "contact page must survive the cap"
    assert "https://x.com/pages/about" in urls
    assert urls.index("https://x.com/pages/contact") < urls.index("https://x.com/products/p0")


def test_crawl_pages_prioritises_relevant_links_and_caps_pages():
    home = """<html><body>
      <a href="/pages/about">About</a>
      <a href="/collections/sweaters">Shop Sweaters</a>
      <a href="/blogs/news/hello">Blog</a>
      <a href="/pages/contact">Contact</a>
    </body></html>"""
    f = FakeFetcher({
        "https://x.com": (200, home),
        "https://x.com/pages/about": (200, "<p>About us</p>"),
        "https://x.com/collections/sweaters": (200, "<p>Sweaters</p>"),
        "https://x.com/pages/contact": (200, "<p>Contact</p>"),
        "https://x.com/blogs/news/hello": (200, "<p>Blog</p>"),
    })
    pages = crawl_pages("x.com", "https://x.com", f, max_pages=4)
    urls = [p.url for p in pages]
    assert len(pages) == 4
    assert "https://x.com" in urls
    assert "https://x.com/pages/about" in urls
    assert "https://x.com/blogs/news/hello" not in urls, "blogs are deprioritised"


def test_acquire_prefers_the_shopify_feed_and_skips_crawling():
    f = FakeFetcher({
        "https://x.com": (200, "<html>cdn.shopify.com</html>"),
        "https://x.com/products.json?limit=250&page=1": (200, feed_page(3)),
        "https://x.com/products.json?limit=250&page=2": (200, json.dumps({"products": []})),
    })
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


def test_acquire_preserves_ssl_bypassed_status():
    """A site fetched with TLS verification disabled must stay visibly flagged."""
    class SslFetcher(FakeFetcher):
        def get(self, url):
            res = super().get(url)
            if url == "https://x.com":
                res.ssl_bypassed = True
            return res

    f = SslFetcher({"https://x.com": (200, "<html><body><div id='root'></div></body></html>")})
    got = acquire(Target(domain="x.com", url="https://x.com"), f)
    assert got.status == "ssl_bypassed", "must not be overwritten by js_required/ok"

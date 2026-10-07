import pytest

from scrapebot.extract.pages import about_snippet, find_wholesale_page, internal_links, page_kind
from scrapebot.extract.text import html_to_text
from scrapebot.models import Page


def test_html_to_text_strips_tags_scripts_and_styles():
    html = """
      <html><head><style>.a{color:red}</style><script>var x=1;</script></head>
      <body><h1>Hello</h1><p>World  of   knits</p></body></html>
    """
    text = html_to_text(html)
    assert text == "Hello World of knits"
    assert "var x" not in text
    assert "color:red" not in text


def test_about_snippet_prefers_an_about_page():
    pages = [
        Page(url="https://x.com", html="", text="Home page text"),
        Page(
            url="https://x.com/pages/about-us", html="", text="We are a family boutique in Naples."
        ),
    ]
    assert about_snippet(pages).startswith("We are a family boutique")


def test_about_snippet_falls_back_to_meta_description():
    pages = [
        Page(
            url="https://x.com",
            html='<meta name="description" content="Curated womenswear since 1998.">',
            text="nav home shop",
        )
    ]
    assert about_snippet(pages) == "Curated womenswear since 1998."


def test_about_snippet_truncates_to_300_chars():
    pages = [Page(url="https://x.com/about", html="", text="y" * 900)]
    assert len(about_snippet(pages)) <= 303


def test_about_snippet_empty_when_nothing_found():
    assert about_snippet([]) == ""


def test_find_wholesale_page_matches_path_or_link_text():
    pages = [
        Page(url="https://x.com", html='<a href="/pages/stockists">Our Stockists</a>', text=""),
        Page(url="https://x.com/pages/wholesale", html="", text=""),
    ]
    assert find_wholesale_page(pages) == "https://x.com/pages/wholesale"


def test_find_wholesale_page_returns_empty_when_absent():
    assert (
        find_wholesale_page([Page(url="https://x.com", html="<a href='/cart'>Cart</a>", text="")])
        == ""
    )


def test_internal_links_are_absolute_same_domain_and_deduped():
    html = """
      <a href="/shop">Shop</a><a href="/shop">Shop again</a>
      <a href="https://x.com/about">About</a>
      <a href="https://other.com/x">Other</a>
      <a href="mailto:a@b.com">Mail</a><a href="#top">Top</a>
    """
    links = internal_links(html, base_url="https://x.com", domain="x.com")
    assert links == ["https://x.com/shop", "https://x.com/about"]


def test_about_snippet_unescapes_entities_in_the_meta_description():
    """Seen on a real store: "women&#39;s clothing" reached the summary as-is."""
    pages = [
        Page(url="https://x.com", html='<meta name="description" content="Women&#39;s &amp; kids">')
    ]
    assert about_snippet(pages) == "Women's & kids"


@pytest.mark.parametrize(
    "url",
    [
        "https://www.knitfactory.com/en/women/clothing/pullover-sweaters",
        "https://www.knitfactory.com/en/women",
        "https://www.knitfactory.com/en/sale",
        "https://www.herrlicher.com/en/women/clothing/knitwear/",
    ],
)
def test_category_pages_are_collections(url):
    """knitfactory.com, 7 Oct 2026: these pages list products with prices, but were
    `other`, so the LLM was sent the customer-service and trade-fair pages instead."""
    assert page_kind(url, "https://www.knitfactory.com") == "collection"


def test_a_language_root_is_the_home_page():
    assert page_kind("https://www.knitfactory.com/en", "https://www.knitfactory.com") == "home"
    assert page_kind("https://x.com/en-gb/", "https://x.com") == "home"


def test_pages_that_list_nothing_stay_other():
    assert page_kind("https://www.knitfactory.com/en/customer-service") == "other"
    assert page_kind("https://www.knitfactory.com/en/trade-fairs") == "other"

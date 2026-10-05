import csv
import json
from pathlib import Path

from scrapebot.config import RunConfig
from scrapebot.models import Target
from scrapebot.survey import BROWSER_GATE, run_survey, survey_store
from tests.fakes import FakeFetcher

HTTP = Path(__file__).parents[1] / "fixtures" / "http"
READABLE = "<html><body><p>" + "A boutique. " * 40 + "</p></body></html>"
FEED = json.dumps({"products": [{"title": "Sweater", "variants": [{"price": "98.00"}]}]})


def test_every_stage_is_tried_even_after_one_works():
    """Unlike a run, the survey does not stop at the first stage that answers."""
    home = (
        "<html>cdn.shopify.com<a href='/products/sweater'>Sweater</a>"
        + "<p>Knit.</p>" * 40
        + "</html>"
    )
    product = '<script type="application/ld+json">{"@type": "Product", "name": "Sweater", "offers": {"price": "98"}}</script>'
    f = FakeFetcher(
        {
            "https://x.com": (200, home),
            "https://x.com/products.json?limit=250&page=1": (200, FEED),
            "https://x.com/products/sweater": (200, product),
        }
    )
    row = survey_store(Target(domain="x.com", url="https://x.com"), f)
    assert (row.platform, row.shopify_feed, row.jsonld) == ("shopify", 1, 1)
    assert "https://x.com/wp-json/wc/store/v1/products?per_page=100&page=1" in f.calls, (
        "all feeds probed"
    )
    assert row.readable_without_browser


def test_microdata_store_found_through_its_product_sitemap():
    sitemap = (HTTP / "wooloverslondon.com-2026-10-05-sitemap.xml").read_text()
    child = "<urlset><url><loc>https://www.wooloverslondon.com/womens/cardigan/aran-41518</loc></url></urlset>"
    f = FakeFetcher(
        {
            "https://www.wooloverslondon.com": (200, READABLE),
            "https://www.wooloverslondon.com/sitemap.xml": (200, sitemap),
            "https://www.wooloverslondon.com/products-sitemap.xml": (200, child),
            "https://www.wooloverslondon.com/womens/cardigan/aran-41518": (
                200,
                (HTTP / "wooloverslondon.com-2026-10-05-product-microdata.html").read_text(),
            ),
        }
    )
    row = survey_store(
        Target(domain="wooloverslondon.com", url="https://www.wooloverslondon.com"), f
    )
    assert row.sitemap_found
    assert row.sitemap_product_urls == 1
    assert row.microdata > 0
    assert row.feed_products == 0


def test_a_js_shell_is_a_browser_candidate_and_a_blocked_store_is_not():
    shell = survey_store(
        Target(domain="s.com", url="https://s.com"),
        FakeFetcher({"https://s.com": (200, "<html><div id='root'></div></html>")}),
    )
    assert shell.js_shell
    assert shell.browser_candidate
    blocked = survey_store(
        Target(domain="b.com", url="https://b.com"), FakeFetcher({"https://b.com": (403, "")})
    )
    assert (blocked.homepage, blocked.detail) == ("blocked", "HTTP 403")
    assert not blocked.browser_candidate


def test_survey_writes_the_matrix_and_the_browser_decision(tmp_path):
    src = tmp_path / "in.csv"
    shells = [f"https://shell{i}.com" for i in range(BROWSER_GATE)]
    src.write_text("website\nhttps://feed.com\n" + "\n".join(shells) + "\n")
    responses = {
        "https://feed.com": (200, "<html>cdn.shopify.com" + "<p>x</p>" * 50 + "</html>"),
        "https://feed.com/products.json?limit=250&page=1": (200, FEED),
    }
    responses.update({u: (200, "<html><div id='app'></div></html>") for u in shells})
    cfg = RunConfig.model_validate({"input": {"source": src}})
    result = run_survey(cfg, tmp_path / "survey", fetcher=FakeFetcher(responses))

    assert len(result.rows) == 1 + BROWSER_GATE
    assert len(result.browser_candidates) == BROWSER_GATE
    report = result.report_path.read_text()
    assert "| Shopify feed | 1 | 1 |" in report
    assert "build the browser render stage (M4)" in report
    with result.csv_path.open() as fh:
        rows = list(csv.DictReader(fh))
    assert {r["domain"] for r in rows if r["browser_candidate"] == "True"} == {
        u[8:] for u in shells
    }

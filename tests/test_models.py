from scrapebot.models import FetchResult, Product, Page, Target, Acquired


def test_fetch_result_ok_requires_200_and_no_error():
    assert FetchResult(url="u", status_code=200, body="hi", final_url="u").ok is True
    assert FetchResult(url="u", status_code=404, body="", final_url="u").ok is False
    assert FetchResult(url="u", status_code=200, body="", final_url="u", error="boom").ok is False


def test_product_defaults():
    p = Product(title="Cher Sweater in Eggnog", price=139.0)
    assert p.product_type == ""
    assert p.tags == []
    assert p.description == ""


def test_target_and_acquired_defaults():
    t = Target(domain="monkeesofnaples.com", url="https://www.monkeesofnaples.com", rows=[{"a": 1}])
    assert t.rows[0]["a"] == 1
    a = Acquired(domain=t.domain)
    assert a.source_used == "none"
    assert a.products == [] and a.pages == []
    assert a.status == "ok"


def test_page_holds_url_and_text():
    pg = Page(url="https://x.com/about", html="<p>Hi</p>", text="Hi")
    assert pg.text == "Hi"

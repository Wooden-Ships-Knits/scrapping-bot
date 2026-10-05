from scrapebot.models import Acquired, FetchResult, Page, Product, Target


def test_fetch_result_ok_requires_200_and_no_error():
    assert FetchResult(url="u", status_code=200, body="hi", final_url="u").ok is True
    assert FetchResult(url="u", status_code=404, body="", final_url="u").ok is False
    assert FetchResult(url="u", status_code=200, body="", final_url="u", error="boom").ok is False


def test_product_defaults():
    p = Product(title="Cher Sweater in Eggnog", price=139.0)
    assert p.product_type == ""
    assert p.tags == []
    assert p.description == ""
    assert p.currency == ""


def test_product_turns_source_nulls_into_empty_values():
    p = Product(title=None, description=None, tags=None, product_type=None)  # pyright: ignore[reportArgumentType]
    assert (p.title, p.description, p.tags, p.product_type) == ("", "", [], "")


def test_target_and_acquired_defaults():
    t = Target(domain="monkeesofnaples.com", url="https://www.monkeesofnaples.com", input_ids=[1])
    assert t.deep_links == []
    a = Acquired(domain=t.domain)
    assert a.source_used == "none"
    assert a.products == []
    assert a.pages == []
    assert a.pages_fetched == 0
    assert a.status == "ok"


def test_page_html_is_never_serialised():
    pg = Page(url="https://x.com/about", html="<p>Hi</p>", text="Hi")
    assert pg.text == "Hi"
    assert "html" not in pg.model_dump()
    assert "<p>" not in pg.model_dump_json()

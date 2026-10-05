import csv

from scrapebot.inputs.resolve import ResolvedInput
from scrapebot.models import Acquired, Contact, Page, Product
from scrapebot.summary import SUMMARY_COLUMNS, summary_row, write_summary_csv

HOME = "https://monkeesofnaples.com"


def item(input_id=1, status="processed", **meta):
    return ResolvedInput(
        input_id=input_id,
        raw=meta.get("website", HOME),
        url=HOME,
        domain="monkeesofnaples.com",
        status=status,
        meta=meta,
    )


def sample_acquired():
    return Acquired(
        domain="monkeesofnaples.com",
        source_used="shopify_feed",
        platform="shopify",
        currency="USD",
        products=[
            Product(title="Cher Sweater in Eggnog", price=139.0, currency="USD"),
            Product(title="Quinn Cardigan in Chocolate", price=698.0, currency="USD"),
            Product(title="Leather Handbag", price=450.0, currency="USD"),
            Product(title="Silk Scarf", price=39.0, currency="USD"),
        ],
        pages=[Page(url=HOME, html="<p>Boutique</p>", text="Boutique in Naples")],
        contacts=[
            Contact(type="email", value="hi@monkeesofnaples.com", source_url=HOME),
            Contact(
                type="instagram",
                value="https://www.instagram.com/monkeesofnaples/",
                source_url=HOME,
            ),
            Contact(type="instagram", value="https://www.instagram.com/other/", source_url=HOME),
        ],
    )


def test_summary_computes_knit_signals():
    row = summary_row(item(store_name="Monkee's of Naples"), sample_acquired())
    assert row["knit_count"] == 2
    assert row["product_count"] == 4
    assert row["knit_share"] == "50%"
    assert "Cher Sweater in Eggnog" in row["knit_examples"]
    assert (row["knit_price_min"], row["knit_price_max"]) == (139.0, 698.0)
    assert (row["price_min"], row["price_max"]) == (39.0, 698.0)
    assert row["currency"] == "USD"


def test_summary_carries_contacts_and_store_facts():
    row = summary_row(item(store_name="Monkee's of Naples"), sample_acquired())
    assert row["emails"] == "hi@monkeesofnaples.com"
    assert row["instagram"] == "https://www.instagram.com/monkeesofnaples/", "first one found wins"
    assert row["platform"] == "shopify"
    assert row["is_chain"] is False
    assert row["scrape_status"] == "ok"
    assert row["source_used"] == "shopify_feed"


def test_summary_handles_a_store_with_no_products():
    row = summary_row(item(store_name="X"), Acquired(domain="x.com", status="js_required"))
    assert (row["product_count"], row["knit_count"]) == (0, 0)
    assert row["knit_share"] == ""
    assert row["knit_examples"] == ""
    assert row["price_min"] == ""
    assert row["knit_price_min"] == ""


def test_summary_flags_chains_by_store_name():
    row = summary_row(item(store_name="Macy's"), Acquired(domain="macys.com", status="blocked"))
    assert row["is_chain"] is True
    assert row["scrape_status"] == "blocked"


def test_summary_caps_knit_examples_at_five():
    acq = Acquired(
        domain="x.com", products=[Product(title=f"Sweater {i}", price=10.0) for i in range(9)]
    )
    row = summary_row(item(store_name="X"), acq)
    assert row["knit_count"] == 9
    assert len(row["knit_examples"].split("; ")) == 5


def test_summary_for_a_skipped_link_uses_the_skip_reason():
    row = summary_row(item(status="no_website", store_name="No Site", website=""), None)
    assert row["scrape_status"] == "no_website"
    assert set(row) == set(SUMMARY_COLUMNS), "skipped rows have every summary column"


def test_summary_reports_ssl_bypassed_beside_the_status():
    row = summary_row(item(), Acquired(domain="x.com", status="no_products", ssl_bypassed=True))
    assert row["scrape_status"] == "no_products"
    assert row["ssl_bypassed"] is True


def test_summary_flags_mixed_currencies():
    acquired = Acquired(
        domain="x.com",
        products=[
            Product(title="A", price=98.0, currency="USD"),
            Product(title="B", price=90.0, currency="EUR"),
        ],
    )
    row = summary_row(item(), acquired)
    assert row["currency_mixed"] is True
    assert row["currency"] == ""


def test_summary_csv_puts_input_columns_first_in_input_order(tmp_path):
    items = [
        item(1, store_name="Monkees", website=HOME, address="Naples FL"),
        item(2, status="no_website", store_name="No Site", website="", address="Naples FL"),
    ]
    rows = [summary_row(items[1], None), summary_row(items[0], sample_acquired())]
    path = write_summary_csv(items, rows, tmp_path / "summary.csv")
    with path.open() as fh:
        out = list(csv.DictReader(fh))
    assert list(out[0])[:3] == ["store_name", "website", "address"]
    assert [r["store_name"] for r in out] == ["Monkees", "No Site"]
    assert out[1]["scrape_status"] == "no_website"


def test_summary_csv_for_pasted_links_has_a_link_column(tmp_path):
    pasted = ResolvedInput(
        input_id=1, raw="a.com", url="https://a.com", domain="a.com", status="processed"
    )
    path = write_summary_csv(
        [pasted], [summary_row(pasted, Acquired(domain="a.com"))], tmp_path / "s.csv"
    )
    with path.open() as fh:
        assert next(csv.DictReader(fh))["link"] == "a.com"

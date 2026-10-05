from scrapebot.aggregate import OUTPUT_COLUMNS, build_record, build_skipped_record
from scrapebot.models import Acquired, Page, Product, Target


def sample_acquired():
    return Acquired(
        domain="monkeesofnaples.com",
        source_used="shopify_feed",
        status="ok",
        pages_fetched=1,
        products=[
            Product(title="Cher Sweater in Eggnog", price=139.0),
            Product(title="Quinn Cardigan in Chocolate", price=698.0),
            Product(title="Leather Handbag", price=450.0),
            Product(title="Silk Scarf", price=39.0),
        ],
        pages=[
            Page(
                url="https://monkeesofnaples.com",
                html='<a href="mailto:hi@monkeesofnaples.com">Mail</a>'
                '<a href="https://www.instagram.com/monkeesofnaples/">IG</a>'
                '<script src="https://cdn.shopify.com/x.js"></script>',
                text="Boutique in Naples",
            )
        ],
    )


def test_build_record_computes_knit_signals():
    target = Target(
        domain="monkeesofnaples.com",
        url="https://monkeesofnaples.com",
        rows=[{"store_name": "Monkee's of Naples", "website": "https://monkeesofnaples.com"}],
    )
    rec = build_record(target, sample_acquired())

    assert rec["knit_count"] == 2
    assert rec["product_count"] == 4
    assert rec["knit_share"] == "50%"
    assert "Cher Sweater in Eggnog" in rec["knit_examples"]
    assert rec["knit_price_min"] == 139.0
    assert rec["knit_price_max"] == 698.0
    assert rec["price_min"] == 39.0
    assert rec["price_max"] == 698.0


def test_build_record_carries_original_columns_and_contacts():
    target = Target(
        domain="monkeesofnaples.com",
        url="https://monkeesofnaples.com",
        rows=[
            {
                "store_name": "Monkee's of Naples",
                "address": "Naples FL",
                "website": "https://monkeesofnaples.com",
            }
        ],
    )
    rec = build_record(target, sample_acquired())

    assert rec["store_name"] == "Monkee's of Naples"
    assert rec["address"] == "Naples FL"
    assert rec["emails"] == "hi@monkeesofnaples.com"
    assert rec["instagram"] == "https://www.instagram.com/monkeesofnaples/"
    assert rec["platform"] == "shopify"
    assert rec["is_chain"] is False
    assert rec["scrape_status"] == "ok"
    assert rec["source_used"] == "shopify_feed"
    assert rec["fetched_at"]


def test_build_record_handles_a_store_with_no_products():
    target = Target(domain="x.com", url="https://x.com", rows=[{"store_name": "X"}])
    rec = build_record(target, Acquired(domain="x.com", status="js_required"))
    assert rec["product_count"] == 0
    assert rec["knit_count"] == 0
    assert rec["knit_share"] == ""
    assert rec["knit_examples"] == ""
    assert rec["price_min"] == ""
    assert rec["knit_price_min"] == ""


def test_build_record_flags_chains():
    target = Target(domain="macys.com", url="https://macys.com", rows=[{"store_name": "Macy's"}])
    rec = build_record(target, Acquired(domain="macys.com", status="blocked"))
    assert rec["is_chain"] is True
    assert rec["scrape_status"] == "blocked"


def test_build_record_caps_knit_examples_at_five():
    target = Target(domain="x.com", url="https://x.com", rows=[{"store_name": "X"}])
    acq = Acquired(
        domain="x.com", products=[Product(title=f"Sweater {i}", price=10.0) for i in range(9)]
    )
    rec = build_record(target, acq)
    assert rec["knit_count"] == 9
    assert len(rec["knit_examples"].split("; ")) == 5


def test_build_skipped_record_produces_a_full_row():
    rec = build_skipped_record({"store_name": "No Site", "website": ""}, "no_website")
    assert rec["scrape_status"] == "no_website"
    assert rec["store_name"] == "No Site"
    assert set(rec) == set(OUTPUT_COLUMNS), "skipped rows have every output column"


def test_every_record_has_exactly_the_output_columns():
    target = Target(domain="x.com", url="https://x.com", rows=[{"store_name": "X"}])
    rec = build_record(target, Acquired(domain="x.com"))
    assert set(rec) == set(OUTPUT_COLUMNS)

import pytest

from scrapebot.inputs.readers import InputRecord
from scrapebot.inputs.resolve import (
    DUPLICATE,
    INVALID_URL,
    MARKETPLACE,
    NO_WEBSITE,
    OVER_LIMIT,
    PROCESSED,
    SOCIAL_ONLY,
    canonical_domain,
    classify,
    normalize_url,
    resolve,
)


def records(*values: str) -> list[InputRecord]:
    return [InputRecord(value=v, meta={"website": v}) for v in values]


def test_normalize_url_adds_scheme_and_strips_trailing_slash():
    assert normalize_url("example.com") == "https://example.com"
    assert normalize_url("https://example.com/") == "https://example.com"
    assert normalize_url("  https://example.com/shop/  ") == "https://example.com/shop"


def test_canonical_domain_is_the_registrable_domain():
    assert canonical_domain("https://www.SaraCampbell.com/shop") == "saracampbell.com"
    assert canonical_domain("https://saracampbell.com/") == "saracampbell.com"
    assert canonical_domain("http://Shop.Example.CO.UK/x") == "example.co.uk"


def test_canonical_domain_keeps_stores_on_shared_platform_hosts_apart():
    assert canonical_domain("https://brand-a.myshopify.com") == "brand-a.myshopify.com"
    assert canonical_domain("https://brand-b.wixsite.com/shop") == "brand-b.wixsite.com"


def test_canonical_domain_keeps_stores_on_hosts_the_suffix_list_misses_apart():
    """saysayboutique.bigcartel.com was grouped as bigcartel.com: a second Big Cartel
    store in the same list would have been skipped as a duplicate."""
    assert (
        canonical_domain("https://saysayboutique.bigcartel.com") == "saysayboutique.bigcartel.com"
    )
    assert canonical_domain("https://shop.brand.bigcartel.com/x") == "brand.bigcartel.com"
    assert canonical_domain("https://brand.squarespace.com") == "brand.squarespace.com"
    assert canonical_domain("https://www.bigcartel.com") == "bigcartel.com"


def test_canonical_domain_scheme_detection_is_case_insensitive():
    assert canonical_domain("HTTP://WWW.EXAMPLE.COM/Shop") == "example.com"


def test_canonical_domain_resolves_protocol_relative_urls():
    assert canonical_domain("//example.com/path") == "example.com"


def test_canonical_domain_strips_userinfo_and_port():
    assert canonical_domain("https://user:pass@example.com:8080/shop") == "example.com"


@pytest.mark.parametrize(
    ("value", "status"),
    [
        ("", NO_WEBSITE),
        ("   ", NO_WEBSITE),
        ("/somepath", NO_WEBSITE),
        ("https://monkeesofnaples.com", PROCESSED),
        ("https://www.instagram.com/somestore/", SOCIAL_ONLY),
        ("https://m.facebook.com/store", SOCIAL_ONLY),
        ("https://x.com/store", SOCIAL_ONLY),
        ("https://linktr.ee/store", SOCIAL_ONLY),
        ("https://www.etsy.com/shop/KnitStudio", MARKETPLACE),
        ("https://www.amazon.co.uk/stores/x", MARKETPLACE),
        ("ftp://files.example.com", INVALID_URL),
        ("http://192.168.1.10", INVALID_URL),
        ("https://localhost", INVALID_URL),
        ("not a website", INVALID_URL),
    ],
)
def test_classify(value, status):
    assert classify(value)[0] == status


@pytest.mark.parametrize(
    "value", ["https://apex.com", "https://onyx.com", "https://fedex.com", "https://shopmax.com"]
)
def test_classify_does_not_false_positive_on_lookalike_domains(value):
    assert classify(value)[0] == PROCESSED


def test_resolve_groups_links_by_domain_and_keeps_input_order():
    res = resolve(
        records(
            "https://www.saracampbell.com/",
            "https://saracampbell.com/pages/naples",
            "",
            "https://www.instagram.com/insta_store/",
            "https://www.monkeesofnaples.com",
        )
    )
    assert [t.domain for t in res.targets] == ["saracampbell.com", "monkeesofnaples.com"]
    sara = res.targets[0]
    assert sara.url == "https://www.saracampbell.com", "the first link's origin starts the visit"
    assert sara.input_ids == [1, 2]
    assert sara.deep_links == ["https://saracampbell.com/pages/naples"]
    assert [i.status for i in res.inputs] == [
        PROCESSED,
        DUPLICATE,
        NO_WEBSITE,
        SOCIAL_ONLY,
        PROCESSED,
    ]


def test_resolve_accounts_for_every_link():
    values = [
        "https://www.saracampbell.com/",
        "https://saracampbell.com/pages/naples",
        "",
        "   ",
        "https://www.instagram.com/insta_store/",
        "https://m.facebook.com/fb_store",
        "https://www.monkeesofnaples.com",
        "https://onyx.com",
        "/somepath",
        "HTTP://WWW.LOUDSTORE.COM",
        "https://user:pass@portedstore.com:8080/shop",
        "https://etsy.com/shop/x",
    ]
    res = resolve(records(*values))
    assert len(res.inputs) == len(values)
    assert len(res.processed) + len(res.skipped) == len(values)
    assert [i.input_id for i in res.inputs] == list(range(1, len(values) + 1))


def test_resolve_keeps_the_input_row_as_metadata():
    rows = [InputRecord(value="https://a.com", meta={"store_name": "A", "address": "Naples FL"})]
    assert resolve(rows).inputs[0].meta == {"store_name": "A", "address": "Naples FL"}


def test_resolve_marks_deep_links():
    res = resolve(
        records("https://a.com", "https://b.com/products/sweater", "https://c.com/?ref=x")
    )
    assert [i.is_deep_link for i in res.inputs] == [False, True, True]


def test_limit_keeps_the_first_stores_and_marks_the_rest_over_limit():
    res = resolve(
        records("https://a.com", "https://b.com", "https://a.com/shop", "https://c.com"), limit=1
    )
    assert [t.domain for t in res.targets] == ["a.com"]
    assert [i.status for i in res.inputs] == [PROCESSED, OVER_LIMIT, DUPLICATE, OVER_LIMIT]

from scrapebot.resolve import canonical_domain, normalize_url, classify_row, load_targets


def test_canonical_domain_strips_www_and_lowercases():
    assert canonical_domain("https://www.SaraCampbell.com/shop") == "saracampbell.com"
    assert canonical_domain("https://saracampbell.com/") == "saracampbell.com"
    assert canonical_domain("http://Shop.Example.CO.UK/x") == "shop.example.co.uk"


def test_normalize_url_adds_scheme_and_strips_trailing_slash():
    assert normalize_url("example.com") == "https://example.com"
    assert normalize_url("https://example.com/") == "https://example.com"
    assert normalize_url("  https://example.com/shop/  ") == "https://example.com/shop"


def test_classify_row_detects_blank_and_social():
    assert classify_row({"website": ""}) == "no_website"
    assert classify_row({"website": "   "}) == "no_website"
    assert classify_row({"website": "https://www.instagram.com/somestore/"}) == "social_only"
    assert classify_row({"website": "https://www.facebook.com/somestore"}) == "social_only"
    assert classify_row({"website": "https://monkeesofnaples.com"}) == "ok"


def test_load_targets_collapses_www_duplicates(tmp_path):
    csv_path = tmp_path / "in.csv"
    csv_path.write_text(
        "store_name,website\n"
        "Sara Campbell,https://www.saracampbell.com/\n"
        "Sara Campbell Naples,https://saracampbell.com/pages/naples\n"
        "No Site Store,\n"
        "Insta Store,https://www.instagram.com/insta_store/\n"
        "Monkees,https://www.monkeesofnaples.com\n"
    )
    targets, skipped = load_targets(str(csv_path))

    assert [t.domain for t in targets] == ["saracampbell.com", "monkeesofnaples.com"]
    sara = targets[0]
    assert len(sara.rows) == 2, "both Sara Campbell rows collapse into one target"
    assert sara.url == "https://www.saracampbell.com", "first-seen URL wins"

    assert len(skipped) == 2
    assert {s[1] for s in skipped} == {"no_website", "social_only"}

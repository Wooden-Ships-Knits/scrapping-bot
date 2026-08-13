from scrapebot.extract import extract_emails, extract_phones, extract_socials

HTML = """
<html><body>
  <a href="mailto:hello@monkeesofnaples.com">Email us</a>
  <a href="mailto:buyer@monkeesofnaples.com?subject=Wholesale">Wholesale</a>
  <p>Or reach us at info@monkeesofnaples.com or call (239) 555-0142.</p>
  <a href="tel:+12395550142">Call</a>
  <a href="https://www.instagram.com/monkeesofnaples/">IG</a>
  <a href="https://www.facebook.com/monkeesofnaples">FB</a>
  <img src="https://cdn.shopify.com/logo@2x.png">
</body></html>
"""


def test_extract_emails_finds_mailto_and_text_and_dedupes():
    emails = extract_emails(HTML)
    assert emails == [
        "hello@monkeesofnaples.com",
        "buyer@monkeesofnaples.com",
        "info@monkeesofnaples.com",
    ]


def test_extract_emails_ignores_image_and_asset_filenames():
    assert extract_emails('<img src="logo@2x.png"> sprite@3x.jpg') == []


def test_extract_emails_strips_mailto_query_params():
    assert extract_emails('<a href="mailto:a@b.com?subject=Hi&body=x">m</a>') == ["a@b.com"]


def test_extract_phones_finds_tel_links_and_text():
    phones = extract_phones(HTML)
    assert "+12395550142" in phones
    assert any("239" in p and "555" in p for p in phones)


def test_extract_socials_returns_profile_urls():
    s = extract_socials(HTML)
    assert s["instagram"] == "https://www.instagram.com/monkeesofnaples/"
    assert s["facebook"] == "https://www.facebook.com/monkeesofnaples"


def test_extract_socials_missing_returns_empty_strings():
    s = extract_socials("<html><body>nothing here</body></html>")
    assert s == {"instagram": "", "facebook": ""}


def test_extract_socials_ignores_share_intent_links():
    html = '<a href="https://www.facebook.com/sharer/sharer.php?u=x">Share</a>'
    assert extract_socials(html)["facebook"] == ""

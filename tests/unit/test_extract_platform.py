from scrapebot.extract import detect_platform, is_chain


def test_detect_platform_recognises_each_stack():
    assert detect_platform('<script src="https://cdn.shopify.com/s/x.js">') == "shopify"
    assert detect_platform('<div id="siteWrapper" data-squarespace>') == "squarespace"
    assert detect_platform('<img src="https://static.wixstatic.com/a.png">') == "wix"
    assert detect_platform('<link href="/wp-content/plugins/woocommerce/x.css">') == "woocommerce"
    assert detect_platform("<script>var BCData={};</script> bigcommerce") == "bigcommerce"


def test_detect_platform_prefers_shopify_over_generic_wordpress():
    html = '<link href="/wp-content/x.css"><script src="https://cdn.shopify.com/y.js">'
    assert detect_platform(html) == "shopify"


def test_detect_platform_falls_back_to_unknown():
    assert detect_platform("<html><body>plain</body></html>") == "custom/unknown"
    assert detect_platform("") == "custom/unknown"


def test_is_chain_matches_known_national_retailers():
    assert is_chain("H&M", "") is True
    assert is_chain("Macy's", "") is True
    assert is_chain("Charlotte Russe", "") is True
    assert is_chain("Windsor", "") is True
    assert is_chain("Bealls Florida", "") is True
    assert is_chain("Brandy Melville", "") is True


def test_is_chain_is_case_and_punctuation_insensitive():
    assert is_chain("MACYS", "") is True
    assert is_chain("macy s", "") is True


def test_is_chain_false_for_independent_boutiques():
    assert is_chain("Monkee's of Naples", "") is False
    assert is_chain("Purple Poppy", "") is False


def test_is_chain_heuristic_on_many_store_locations():
    html = "Find a store near you" + "".join(f"<li>Store {i}</li>" for i in range(40))
    assert is_chain("Some Boutique", html) is True

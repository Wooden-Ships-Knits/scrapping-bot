import pytest

from scrapebot.fetch import Fetcher


def make_transport(responses, calls=None):
    """responses: {url: (status, body)} or an Exception to raise."""

    def transport(url, headers, verify, timeout):
        if calls is not None:
            calls.append((url, verify))
        r = responses.get(url, (404, ""))
        if isinstance(r, Exception):
            raise r
        return (r[0], r[1], url)

    return transport


def test_get_returns_body_on_success(tmp_path):
    f = Fetcher(
        cache_dir=tmp_path,
        delay=0,
        transport=make_transport({"https://x.com": (200, "<html>hi</html>")}),
    )
    res = f.get("https://x.com")
    assert res.ok
    assert res.body == "<html>hi</html>"
    assert res.status_code == 200


def test_get_caches_and_does_not_refetch(tmp_path):
    calls = []
    f = Fetcher(
        cache_dir=tmp_path,
        delay=0,
        transport=make_transport({"https://x.com": (200, "body")}, calls),
    )
    f.get("https://x.com")
    second = f.get("https://x.com")
    # Filtered to the page URL: a robots.txt probe is expected once per
    # origin (see test_robots_disallow_blocks_the_request) and is not what
    # this test is about.
    page_calls = [c for c in calls if c[0] == "https://x.com"]
    assert len(page_calls) == 1, "second call must be served from cache"
    assert second.from_cache is True
    assert second.body == "body"


def test_get_records_403_without_raising(tmp_path):
    f = Fetcher(cache_dir=tmp_path, delay=0, transport=make_transport({"https://x.com": (403, "")}))
    res = f.get("https://x.com")
    assert res.ok is False
    assert res.status_code == 403


def test_get_retries_then_records_error(tmp_path):
    calls = []
    f = Fetcher(
        cache_dir=tmp_path,
        delay=0,
        retries=2,
        transport=make_transport({"https://x.com": TimeoutError("timed out")}, calls),
    )
    res = f.get("https://x.com")
    assert res.ok is False
    assert "TimeoutError" in res.error
    # Filtered to the page URL: a robots.txt probe is expected once per
    # origin and is not retried, so it must not count toward this budget.
    page_calls = [c for c in calls if c[0] == "https://x.com"]
    assert len(page_calls) == 3, "initial attempt plus 2 retries"


def test_ssl_failure_retries_with_verification_disabled(tmp_path):
    calls = []

    def transport(url, headers, verify, timeout):
        calls.append((url, verify))
        if verify:
            raise Exception("SSLV3_ALERT_HANDSHAKE_FAILURE")
        return (200, "insecure body", url)

    f = Fetcher(cache_dir=tmp_path, delay=0, retries=0, transport=transport)
    res = f.get("https://badssl.com")
    assert res.ok
    assert res.body == "insecure body"
    assert res.ssl_bypassed is True, "the weakened check must be visible in the result"
    assert calls[-1][1] is False


def test_robots_disallow_blocks_the_request(tmp_path):
    responses = {
        "https://x.com/robots.txt": (200, "User-agent: *\nDisallow: /private"),
        "https://x.com/private/page": (200, "secret"),
    }
    f = Fetcher(cache_dir=tmp_path, delay=0, transport=make_transport(responses))
    res = f.get("https://x.com/private/page")
    assert res.ok is False
    assert res.error == "robots_disallowed"


def test_robots_allows_when_file_is_missing(tmp_path):
    f = Fetcher(
        cache_dir=tmp_path, delay=0, transport=make_transport({"https://x.com/page": (200, "fine")})
    )
    assert f.get("https://x.com/page").ok is True


def test_no_accept_language_header_is_sent(tmp_path):
    """Accept-Language makes Shopify Markets localise prices to the requester's geo.

    Measured on a real prospect site: with the header the feed returned
    "2757000.00" (Indonesian Rupiah); without it, "98.00" (store base currency).
    Prices must arrive in the store's own currency to be comparable.
    """
    seen = {}

    def transport(url, headers, verify, timeout):
        seen.update(headers)
        return (200, "ok", url)

    f = Fetcher(cache_dir=tmp_path, delay=0, transport=transport)
    f.get("https://x.com/products.json")

    assert "User-Agent" in seen
    assert not any(k.lower() == "accept-language" for k in seen), (
        "Accept-Language must not be sent: it triggers currency localisation"
    )


def test_failed_fetch_is_not_cached_so_a_rerun_retries(tmp_path):
    """Issue 1: a temporary failure must not stick until data/.cache is deleted."""
    calls = []
    failing = Fetcher(
        cache_dir=tmp_path,
        delay=0,
        retries=0,
        transport=make_transport({"https://x.com": TimeoutError("timed out")}, calls),
    )
    assert failing.get("https://x.com").ok is False

    recovered = Fetcher(
        cache_dir=tmp_path,
        delay=0,
        transport=make_transport({"https://x.com": (200, "back")}, calls),
    )
    res = recovered.get("https://x.com")
    assert res.ok
    assert res.from_cache is False
    assert res.body == "back"


@pytest.mark.parametrize("status", [404, 429, 500, 503])
def test_unsuccessful_status_is_not_cached(tmp_path, status):
    calls = []
    f = Fetcher(
        cache_dir=tmp_path,
        delay=0,
        transport=make_transport({"https://x.com": (status, "")}, calls),
    )
    f.get("https://x.com")
    f.get("https://x.com")
    page_calls = [c for c in calls if c[0] == "https://x.com"]
    assert len(page_calls) == 2, "an unsuccessful response must be fetched again"


def test_failure_cached_by_an_older_version_is_ignored(tmp_path):
    """Caches written before the fix hold failures; they must heal on the next run."""
    calls = []
    old = Fetcher(cache_dir=tmp_path, delay=0)
    old._cache_path("https://x.com").write_text(
        '{"url": "https://x.com", "status_code": null, "body": "", '
        '"final_url": "https://x.com", "error": "TimeoutError", "ssl_bypassed": false}'
    )
    f = Fetcher(
        cache_dir=tmp_path,
        delay=0,
        transport=make_transport({"https://x.com": (200, "fresh")}, calls),
    )
    assert f.get("https://x.com").body == "fresh"

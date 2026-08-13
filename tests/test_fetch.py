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
    f = Fetcher(cache_dir=tmp_path, delay=0,
                transport=make_transport({"https://x.com": (200, "<html>hi</html>")}))
    res = f.get("https://x.com")
    assert res.ok and res.body == "<html>hi</html>" and res.status_code == 200


def test_get_caches_and_does_not_refetch(tmp_path):
    calls = []
    f = Fetcher(cache_dir=tmp_path, delay=0,
                transport=make_transport({"https://x.com": (200, "body")}, calls))
    f.get("https://x.com")
    second = f.get("https://x.com")
    # Filtered to the page URL: a robots.txt probe is expected once per
    # origin (see test_robots_disallow_blocks_the_request) and is not what
    # this test is about.
    page_calls = [c for c in calls if c[0] == "https://x.com"]
    assert len(page_calls) == 1, "second call must be served from cache"
    assert second.from_cache is True and second.body == "body"


def test_get_records_403_without_raising(tmp_path):
    f = Fetcher(cache_dir=tmp_path, delay=0,
                transport=make_transport({"https://x.com": (403, "")}))
    res = f.get("https://x.com")
    assert res.ok is False and res.status_code == 403


def test_get_retries_then_records_error(tmp_path):
    calls = []
    f = Fetcher(cache_dir=tmp_path, delay=0, retries=2,
                transport=make_transport({"https://x.com": TimeoutError("timed out")}, calls))
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
    assert res.ok and res.body == "insecure body"
    assert res.ssl_bypassed is True, "the weakened check must be visible in the result"
    assert calls[-1][1] is False


def test_robots_disallow_blocks_the_request(tmp_path):
    responses = {
        "https://x.com/robots.txt": (200, "User-agent: *\nDisallow: /private"),
        "https://x.com/private/page": (200, "secret"),
    }
    f = Fetcher(cache_dir=tmp_path, delay=0, transport=make_transport(responses))
    res = f.get("https://x.com/private/page")
    assert res.ok is False and res.error == "robots_disallowed"


def test_robots_allows_when_file_is_missing(tmp_path):
    f = Fetcher(cache_dir=tmp_path, delay=0,
                transport=make_transport({"https://x.com/page": (200, "fine")}))
    assert f.get("https://x.com/page").ok is True

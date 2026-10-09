import gzip
import threading
import time
from itertools import pairwise
from pathlib import Path

import pytest

from scrapebot.fetch import HttpFetcher as Fetcher
from scrapebot.fetch import _decode, detect_challenge


def _no_dns(host):
    return None


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
        backoff_seconds=0,
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
        backoff_seconds=0,
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
    f = Fetcher(
        cache_dir=tmp_path,
        delay=0,
        backoff_seconds=0,
        transport=make_transport({"https://x.com": (403, "")}),
    )
    res = f.get("https://x.com")
    assert res.ok is False
    assert res.status_code == 403


def test_get_retries_then_records_error(tmp_path):
    calls = []
    f = Fetcher(
        cache_dir=tmp_path,
        delay=0,
        backoff_seconds=0,
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

    f = Fetcher(
        cache_dir=tmp_path,
        delay=0,
        backoff_seconds=0,
        resolver=_no_dns,
        retries=0,
        transport=transport,
    )
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
    f = Fetcher(
        cache_dir=tmp_path,
        delay=0,
        backoff_seconds=0,
        resolver=_no_dns,
        transport=make_transport(responses),
    )
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

    f = Fetcher(
        cache_dir=tmp_path, delay=0, backoff_seconds=0, resolver=_no_dns, transport=transport
    )
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
        backoff_seconds=0,
        retries=0,
        transport=make_transport({"https://x.com": TimeoutError("timed out")}, calls),
    )
    assert failing.get("https://x.com").ok is False

    recovered = Fetcher(
        cache_dir=tmp_path,
        delay=0,
        backoff_seconds=0,
        transport=make_transport({"https://x.com": (200, "back")}, calls),
    )
    res = recovered.get("https://x.com")
    assert res.ok
    assert res.from_cache is False
    assert res.body == "back"


@pytest.mark.parametrize("status", [404, 500, 503])
def test_unsuccessful_status_is_not_cached(tmp_path, status):
    calls = []
    f = Fetcher(
        cache_dir=tmp_path,
        delay=0,
        retries=0,
        transport=make_transport({"https://x.com": (status, "")}, calls),
    )
    f.get("https://x.com")
    f.get("https://x.com")
    page_calls = [c for c in calls if c[0] == "https://x.com"]
    assert len(page_calls) == 2, "an unsuccessful response must be fetched again"


def test_failure_cached_by_an_older_version_is_ignored(tmp_path):
    """Caches written before the fix hold failures; they must heal on the next run."""
    calls = []
    old = Fetcher(cache_dir=tmp_path, delay=0, backoff_seconds=0, resolver=_no_dns)
    old._cache_path("https://x.com").write_text(
        '{"url": "https://x.com", "status_code": null, "body": "", '
        '"final_url": "https://x.com", "error": "TimeoutError", "ssl_bypassed": false}'
    )
    f = Fetcher(
        cache_dir=tmp_path,
        delay=0,
        backoff_seconds=0,
        transport=make_transport({"https://x.com": (200, "fresh")}, calls),
    )
    assert f.get("https://x.com").body == "fresh"


def test_429_and_5xx_are_retried_with_backoff_then_returned(tmp_path):
    calls = []
    f = Fetcher(
        cache_dir=tmp_path,
        delay=0,
        retries=2,
        backoff_seconds=0,
        transport=make_transport({"https://x.com": (503, "busy")}, calls),
    )
    res = f.get("https://x.com")
    assert res.status_code == 503
    assert len([c for c in calls if c[0] == "https://x.com"]) == 3


def test_a_retry_that_succeeds_returns_the_page(tmp_path):
    answers = iter([(429, ""), (200, "<p>ok</p>")])

    def transport(url, headers, verify, timeout):
        if url.endswith("robots.txt"):
            return (404, "", url)
        status, body = next(answers)
        return (status, body, url)

    f = Fetcher(
        cache_dir=tmp_path, delay=0, backoff_seconds=0, resolver=_no_dns, transport=transport
    )
    assert f.get("https://x.com").body == "<p>ok</p>"


CLOUDFLARE = "<html><head><title>Just a moment...</title></head><body>/cdn-cgi/challenge-platform/h/b</body></html>"


@pytest.mark.parametrize("status", [200, 403, 503])
def test_challenge_pages_are_flagged_never_retried_and_never_cached(tmp_path, status):
    """PRD AQ-03: a challenge page means blocked; it is not worked around."""
    calls = []
    f = Fetcher(
        cache_dir=tmp_path,
        delay=0,
        backoff_seconds=0,
        transport=make_transport({"https://x.com": (status, CLOUDFLARE)}, calls),
    )
    res = f.get("https://x.com")
    assert res.challenge == "cloudflare"
    assert res.ok is False
    assert len([c for c in calls if c[0] == "https://x.com"]) == 1, "no retry"
    f.get("https://x.com")
    assert len([c for c in calls if c[0] == "https://x.com"]) == 2, "not cached"


def test_a_block_page_sent_as_a_redirect_is_a_challenge():
    """ralphlauren.com: PerimeterX's block page with status 307 and no Location."""
    from pathlib import Path

    body = (
        Path(__file__).parents[1] / "fixtures/http/ralphlauren.com-2026-10-06-perimeterx-307.html"
    ).read_text()
    assert detect_challenge(307, body) == "perimeterx"


def test_an_ordinary_page_mentioning_captcha_words_is_not_a_challenge():
    long_page = "<html>" + "<p>We sell cardigans.</p>" * 5000 + "datadome</html>"
    assert detect_challenge(200, long_page) == ""
    assert detect_challenge(404, CLOUDFLARE) == ""


def test_gzipped_bodies_are_decoded():
    assert _decode(gzip.compress(b"<urlset></urlset>"), None) == "<urlset></urlset>"


JITTER = 0.003  # seconds


def test_requests_to_one_host_never_overlap_and_keep_the_delay(tmp_path):
    """PRD AQ-11: parallel stores, but each host still sees one request at a time."""
    active, overlaps, starts = [0], [0], []
    lock = threading.Lock()

    def transport(url, headers, verify, timeout):
        if url.endswith("robots.txt"):
            return (404, "", url)
        started = time.monotonic()  # before the lock, so waiting for it adds no jitter
        with lock:
            active[0] += 1
            overlaps[0] = max(overlaps[0], active[0])
            starts.append(started)
        time.sleep(0.02)
        with lock:
            active[0] -= 1
        return (200, "ok", url)

    f = Fetcher(cache_dir=tmp_path, delay=0.05, transport=transport, resolver=_no_dns)
    threads = [threading.Thread(target=f.get, args=(f"https://x.com/p{i}",)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert overlaps[0] == 1
    gaps = [b - a for a, b in pairwise(starts)]
    # The fetcher stamps each request just before calling the transport; the moment
    # between that stamp and this one varies by a few microseconds per thread, so a
    # gap can read as 0.0499 under load. The delay itself is kept.
    assert min(gaps) >= 0.05 - JITTER


def test_sitemaps_declared_in_robots_txt(tmp_path):
    robots = "User-agent: *\nAllow: /\nSitemap: https://x.com/sitemap_index.xml\n"
    f = Fetcher(
        cache_dir=tmp_path,
        delay=0,
        transport=make_transport({"https://x.com/robots.txt": (200, robots)}),
    )
    assert f.sitemaps("https://x.com") == ["https://x.com/sitemap_index.xml"]


def test_hosts_on_one_server_network_share_the_delay(tmp_path):
    """Seen live: six Shopify stores in parallel all hit Shopify's shared edge
    (23.227.38.x), which answered with a challenge. Politeness is per server."""
    starts: dict[str, list[float]] = {"shop": [], "other": []}
    lock = threading.Lock()

    def transport(url, headers, verify, timeout):
        if url.endswith("robots.txt"):
            return (404, "", url)
        with lock:
            starts["other" if "other" in url else "shop"].append(time.monotonic())
        return (200, "ok", url)

    networks = {
        "a-shop.com": "23.227.38.65",
        "b-shop.com": "23.227.38.74",
        "other.com": "198.185.159.144",
    }
    f = Fetcher(
        cache_dir=tmp_path,
        delay=0.1,
        transport=transport,
        resolver=lambda host: networks.get(host),
    )
    assert (
        f.throttle_key("https://a-shop.com/x")
        == f.throttle_key("https://b-shop.com/y")
        == "23.227.38.0/24"
    )
    threads = [
        threading.Thread(target=f.get, args=(url,))
        for url in (
            "https://a-shop.com/1",
            "https://b-shop.com/1",
            "https://a-shop.com/2",
            "https://other.com/1",
        )
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    shop = sorted(starts["shop"])
    assert min(b - a for a, b in pairwise(shop)) >= 0.1, "same network: one at a time, delay apart"
    assert starts["other"][0] - shop[0] < 0.1, "a different network does not wait"


def test_unresolvable_hosts_fall_back_to_the_host_name(tmp_path):
    f = Fetcher(cache_dir=tmp_path, delay=0, resolver=lambda host: None)
    assert f.throttle_key("https://www.x.com/a") == "www.x.com"


def test_akamai_behavioural_challenge_is_a_challenge():
    """next.co.uk, 7 Oct 2026: the browser was answered 200 with this page, and its
    text ('Powered and protected by Privacy') was read as a store page."""
    from pathlib import Path

    body = (
        Path(__file__).parents[1] / "fixtures/http/next.co.uk-2026-10-07-akamai-challenge.html"
    ).read_text()
    assert detect_challenge(200, body) == "akamai"


FIXTURES = Path(__file__).parents[1] / "fixtures/http"


def test_cloudflare_bot_script_on_an_ordinary_page_is_not_a_challenge():
    """Roadmap issue 15: dearprudence.com answers 200 with its whole home page and
    Cloudflare's bot-detection script, and was read as blocked."""
    body = (FIXTURES / "dearprudence.com-2026-10-09-home-cloudflare-jsd.html").read_text()
    assert "challenge-platform/scripts/jsd" in body
    assert detect_challenge(200, body) == ""


def test_cloudflare_challenge_page_is_still_a_challenge():
    body = (FIXTURES / "maptons.com-2026-10-09-cloudflare-challenge.html").read_text()
    assert detect_challenge(403, body) == "cloudflare"


# --- rate limits on a shared server network (roadmap issue 16) ---------------------

SHOPIFY_EDGE = {"a-shop.com": "23.227.38.65", "b-shop.com": "23.227.38.74", "c.com": "198.51.100.7"}
CHALLENGE = "<html><head><title>Just a moment...</title></head><body>_cf_chl_opt</body></html>"


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def edge_fetcher(tmp_path, responses, calls, clock, delay=0.0):
    return Fetcher(
        cache_dir=tmp_path,
        delay=delay,
        retries=0,
        transport=make_transport(responses, calls),
        resolver=lambda host: SHOPIFY_EDGE.get(host),
        clock=clock,
    )


def test_a_429_pauses_the_whole_network_then_lets_it_try_again(tmp_path):
    calls, clock = [], Clock()
    f = edge_fetcher(
        tmp_path,
        {"https://a-shop.com/": (429, ""), "https://b-shop.com/": (200, "<p>ok</p>")},
        calls,
        clock,
        delay=0.01,
    )
    assert f.get("https://a-shop.com/").rate_limited
    paused = f.get("https://b-shop.com/")  # another store on the same edge
    assert (paused.rate_limited, paused.error) == (
        True,
        "rate_limited: the server network is cooling down",
    )
    assert all(url != "https://b-shop.com/" for url, _ in calls), "nothing sent while cooling"
    other = f.get("https://c.com/")  # another network: not paused (a plain 404 here)
    assert (other.status_code, other.rate_limited) == (404, False)
    assert f.cooldown_remaining(["https://b-shop.com/"]) == pytest.approx(300)
    clock.now += 301
    assert f.get("https://b-shop.com/").ok, "after the pause the store is read"
    assert f.was_rate_limited("https://b-shop.com/")
    assert f._delays["23.227.38.0/24"] == 0.02, "the network is asked more slowly from now on"


def test_two_sites_refusing_on_one_network_is_a_rate_limit_one_is_not(tmp_path):
    calls, clock = [], Clock()
    f = edge_fetcher(
        tmp_path,
        {"https://a-shop.com/": (403, CHALLENGE), "https://b-shop.com/": (403, CHALLENGE)},
        calls,
        clock,
    )
    first = f.get("https://a-shop.com/")
    assert (first.challenge, first.rate_limited) == ("cloudflare", False), "one store may block us"
    second = f.get("https://b-shop.com/")
    assert second.rate_limited, "two stores on one edge within 10 minutes: it is us"
    assert f.was_rate_limited("https://a-shop.com/"), "the first one is retried too"


def test_refusals_far_apart_are_not_a_rate_limit(tmp_path):
    calls, clock = [], Clock()
    f = edge_fetcher(
        tmp_path,
        {"https://a-shop.com/": (403, CHALLENGE), "https://b-shop.com/": (403, CHALLENGE)},
        calls,
        clock,
    )
    f.get("https://a-shop.com/")
    clock.now += 601
    assert not f.get("https://b-shop.com/").rate_limited


def test_cooldowns_double_up_to_a_ceiling(tmp_path):
    calls, clock = [], Clock()
    f = edge_fetcher(tmp_path, {"https://a-shop.com/": (429, "")}, calls, clock)
    lengths = []
    for _ in range(5):
        f.get("https://a-shop.com/")
        lengths.append(round(f.cooldown_remaining(["https://a-shop.com/"])))
        clock.now += lengths[-1] + 1
    assert lengths == [300, 600, 1200, 1800, 1800]


# --- cache expiry (roadmap issue 17) --------------------------------------------------


def test_an_old_cached_page_is_fetched_again(tmp_path):
    import os

    calls = []
    f = Fetcher(
        cache_dir=tmp_path,
        delay=0,
        max_age_seconds=3600,
        transport=make_transport({"https://x.com/": (200, "<p>v1</p>")}, calls),
    )
    f.get("https://x.com/")
    assert f.get("https://x.com/").from_cache, "fresh: read from the cache"
    [page] = list((tmp_path / "x.com").glob("*.json"))
    old = page.stat().st_mtime - 7200
    os.utime(page, (old, old))
    again = f.get("https://x.com/")
    assert (again.from_cache, again.body) == (False, "<p>v1</p>"), "two hours old: fetched again"


def test_prune_deletes_old_pages_and_never_the_discovery_cache(tmp_path):
    import os

    from scrapebot.fetch import prune_cache

    for folder, name in (("old.com", "a.json"), ("new.com", "b.json"), ("discover", "c.json")):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / name).write_text("{}")
    for path in (tmp_path / "old.com" / "a.json", tmp_path / "discover" / "c.json"):
        os.utime(path, (0, 0))
    assert prune_cache(tmp_path, max_age_seconds=3600) == 1
    assert not (tmp_path / "old.com").exists()
    assert (tmp_path / "new.com" / "b.json").exists()
    assert (tmp_path / "discover" / "c.json").exists(), "paid answers are never pruned"
    assert prune_cache(tmp_path, max_age_seconds=0) == 0, "0 keeps everything"

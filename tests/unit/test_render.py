"""The browser's own rules, checked without a browser."""

import urllib.robotparser
from contextlib import nullcontext

from scrapebot.config import RunConfig
from scrapebot.fetch import HttpFetcher
from scrapebot.pipeline import build_renderer
from scrapebot.render import CamoufoxRenderer, _route
from tests.fakes import FakeFetcher


class Host:
    def __init__(self, allowed=True):
        self._allowed = allowed

    def allowed(self, url):
        return self._allowed

    def robots(self, url):
        return None

    def polite(self, url):
        return nullcontext()


class Request:
    def __init__(self, url, resource_type):
        self.url, self.resource_type = url, resource_type


class Route:
    def __init__(self, url, resource_type="document"):
        self.request = Request(url, resource_type)
        self.outcome = ""

    def abort(self):
        self.outcome = "abort"

    def continue_(self):
        self.outcome = "continue"


def rules(text):
    parser = urllib.robotparser.RobotFileParser()
    parser.parse(text.splitlines())
    return parser


def test_a_page_robots_disallows_is_never_opened():
    renderer = CamoufoxRenderer(Host(allowed=False))
    rendered = renderer.render("https://shop.com/private")
    assert rendered.result.error == "robots_disallowed"
    assert not renderer._started, "no browser is started for it"


def test_the_browser_skips_images_and_requests_robots_disallows_on_the_store():
    page = "https://shop.com/women"
    disallow = rules("User-agent: *\nDisallow: /api/private")
    cases = {
        ("https://shop.com/img/a.jpg", "image"): "abort",
        ("https://shop.com/api/private/cart", "fetch"): "abort",
        ("https://shop.com/api/products", "fetch"): "continue",
        ("https://cdn.other.com/api/private/x.js", "script"): "continue",
    }
    for (url, kind), expected in cases.items():
        route = Route(url, kind)
        _route(route, page, disallow)
        assert route.outcome == expected, url


def test_the_browser_is_built_only_for_real_runs(tmp_path):
    config = RunConfig()
    assert build_renderer(config, FakeFetcher({})) is None, "a test double never gets a browser"
    real = HttpFetcher(cache_dir=tmp_path)
    assert build_renderer(config, real) is None, "Camoufox is 'not installed' under test"
    off = RunConfig.model_validate({"render": {"enabled": False}})
    assert build_renderer(off, real) is None


def test_polite_holds_the_server_turn(tmp_path):
    fetcher = HttpFetcher(cache_dir=tmp_path, delay=0, resolver=lambda host: None)
    with fetcher.polite("https://shop.com/x"):
        assert fetcher._server_lock("https://shop.com/y").locked()
    assert not fetcher._server_lock("https://shop.com/y").locked()

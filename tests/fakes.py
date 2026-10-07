"""Test doubles shared across suites. Nothing here touches the network."""

from scrapebot.models import FetchResult


class FakeFetcher:
    """Serves canned responses by exact URL; anything unknown is a 404.

    `responses` maps a URL to `(status, body)`. Every requested URL is recorded in
    `calls`, in order.
    """

    def __init__(self, responses: dict[str, tuple[int, str]]):
        self.responses = responses
        self.calls: list[str] = []

    def get(self, url: str) -> FetchResult:
        self.calls.append(url)
        entry = self.responses.get(url)
        if entry is None:
            return FetchResult(url=url, status_code=404, body="", final_url=url)
        status, body = entry
        return FetchResult(url=url, status_code=status, body=body, final_url=url)

    def sitemaps(self, origin: str) -> list[str]:
        return []


class FakeRenderer:
    """Serves canned rendered pages by exact URL; anything unknown is a browser error.

    `pages` maps a URL to `(status, html)` or `(status, html, captured)`, where
    `captured` is a list of `(json_url, data)`. `challenge` maps a URL to the vendor
    whose challenge the browser met. Every rendered URL is recorded in `calls`.
    """

    def __init__(self, pages: dict, challenge: dict[str, str] | None = None):
        self.pages = pages
        self.challenge = challenge or {}
        self.calls: list[str] = []
        self.closed = False

    def render(self, url: str):
        from scrapebot.render import CapturedJson, Rendered

        self.calls.append(url)
        if url in self.challenge:
            return Rendered(
                FetchResult(
                    url=url, status_code=403, body="", final_url=url, challenge=self.challenge[url]
                )
            )
        entry = self.pages.get(url)
        if entry is None:
            return Rendered(
                FetchResult(url=url, status_code=None, body="", final_url=url, error="browser")
            )
        status, html, *rest = entry
        captured = [CapturedJson(u, d) for u, d in (rest[0] if rest else [])]
        return Rendered(
            FetchResult(url=url, status_code=status, body=html, final_url=url), captured
        )

    def close(self) -> None:
        self.closed = True


class FakeSearchApi:
    """Answers the paid search APIs (Google Places, Tavily) offline.

    `routes` maps a URL to a function of the JSON body that returns `(status, answer)`.
    An unknown URL is a 404. Every call is recorded in `calls` as `(url, headers, body)`.
    """

    def __init__(self, routes: dict):
        self.routes = routes
        self.calls: list[tuple[str, dict, dict]] = []

    def __call__(self, method, url, headers, body, timeout):
        import json

        payload = json.loads(body) if body else {}
        self.calls.append((url, dict(headers), payload))
        route = self.routes.get(url)
        if route is None:
            return 404, '{"error": "not found"}'
        status, answer = route(payload)
        return status, answer if isinstance(answer, str) else json.dumps(answer)

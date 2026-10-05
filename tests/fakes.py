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

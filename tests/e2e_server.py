"""The real API and built web app, with recorded-style responses instead of the network.

Used by the Playwright suite (web/e2e). Every run starts from empty temp folders.

    uv run python -m tests.e2e_server --port 8799
"""

import argparse
import json
import tempfile
import time
from pathlib import Path

import uvicorn

from scrapebot.api import ApiSettings, create_app
from scrapebot.config import RunConfig
from scrapebot.models import FetchResult
from tests.fakes import FakeFetcher

ROOT = Path(__file__).resolve().parents[1]

SHOPIFY_HOME = (
    '<html><script>Shopify.currency = {"active":"USD","rate":"1.0"};</script>'
    '<a href="mailto:hello@monkees.com">Mail</a> cdn.shopify.com</html>'
)
FEED = json.dumps(
    {
        "products": [
            {
                "title": "Cher Sweater in Eggnog",
                "handle": "cher",
                "variants": [{"price": "139.00"}],
            },
            {"title": "Quinn Cardigan", "handle": "quinn", "variants": [{"price": "698.00"}]},
            {"title": "Leather Bag", "handle": "bag", "variants": [{"price": "450.00"}]},
        ]
    }
)
READABLE = "<html><body><p>" + "A boutique in Naples. " * 30 + "</p></body></html>"
RESPONSES = {
    "https://monkees.com": (200, SHOPIFY_HOME),
    "https://monkees.com/products.json?limit=250&page=1": (200, FEED),
    "https://boutique.com": (200, READABLE),
    "https://blocked.com": (403, ""),
    "https://knitshop.com": (200, SHOPIFY_HOME.replace("monkees", "knitshop")),
    "https://knitshop.com/products.json?limit=250&page=1": (200, FEED),
}


class SlowFakeFetcher(FakeFetcher):
    """A short pause per request, so progress is visible in the interface."""

    def __init__(self, delay: float):
        super().__init__(RESPONSES)
        self.delay = delay

    def get(self, url: str) -> FetchResult:
        time.sleep(self.delay)
        return super().get(url)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8799)
    parser.add_argument("--delay", type=float, default=0.15)
    args = parser.parse_args()

    work = Path(tempfile.mkdtemp(prefix="scrapebot-e2e-"))
    base = RunConfig.model_validate(
        {"output": {"runs_dir": work / "runs"}, "fetch": {"cache_dir": work / "cache"}}
    )
    settings = ApiSettings(
        base=base,
        uploads_dir=work / "uploads",
        web_dist=ROOT / "web" / "dist",
        poll_seconds=0.2,
        # No keys: the suite never sees a developer's .env, and opens on pasted links.
        env_file=work / ".env",
        discover_dir=work / "discover",
        discover_cache_dir=work / "discover-cache",
    )
    app = create_app(settings, fetcher_factory=lambda: SlowFakeFetcher(args.delay))
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()

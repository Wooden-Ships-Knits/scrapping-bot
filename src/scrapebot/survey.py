"""Survey: which stage can read which store (PRD M1).

A read-only pass that, unlike a run, does not stop at the first stage that works:
every stage is tried on every store and its yield recorded, giving a coverage
matrix. It answers the questions the roadmap gates on, such as whether enough
stores can only be read with a browser to build the render stage (AQ-09).

    uv run scrapebot survey data/list.csv
"""

import csv
import logging
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from .acquire import SHELL_TEXT_CHARS
from .acquire.discovery import (
    MAX_PAGES,
    dedupe,
    failure_reason,
    fetch_pages,
    rank_links,
    sitemap_urls,
    to_page,
    url_key,
)
from .acquire.feeds import FEEDS
from .config import RunConfig
from .extract.profile import detect_platform
from .extract.structured import app_state_products, opengraph_product, schema_products
from .fetch import Fetcher, HttpFetcher
from .inputs.resolve import resolve
from .models import Target
from .pipeline import read_records

log = logging.getLogger(__name__)

# The browser gate in the roadmap: build the render stage only if at least this
# many stores can be read by nothing else.
BROWSER_GATE = 5


@dataclass
class SurveyRow:
    domain: str
    url: str
    homepage: str  # ok | blocked | error
    detail: str
    platform: str
    homepage_text_chars: int
    js_shell: bool
    shopify_feed: int
    woocommerce_feed: int
    squarespace_feed: int
    lightspeed_feed: int
    sitemap_found: bool
    sitemap_product_urls: int
    pages_read: int
    jsonld: int
    microdata: int
    rdfa: int
    opengraph: int
    app_state: int

    @property
    def feed_products(self) -> int:
        feeds = (
            self.shopify_feed,
            self.woocommerce_feed,
            self.squarespace_feed,
            self.lightspeed_feed,
        )
        return sum(feeds)

    @property
    def structured_products(self) -> int:
        return self.jsonld + self.microdata + self.rdfa + self.opengraph + self.app_state

    @property
    def readable_without_browser(self) -> bool:
        return self.feed_products > 0 or self.structured_products > 0

    @property
    def browser_candidate(self) -> bool:
        """Read fine over HTTP, yet nothing found: a browser might help."""
        return self.homepage == "ok" and not self.readable_without_browser


def survey_store(target: Target, fetcher: Fetcher, max_pages: int = MAX_PAGES) -> SurveyRow:
    row = SurveyRow(
        domain=target.domain, url=target.url, homepage="ok", detail="", platform="",
        homepage_text_chars=0, js_shell=False, shopify_feed=0, woocommerce_feed=0,
        squarespace_feed=0, lightspeed_feed=0, sitemap_found=False, sitemap_product_urls=0,
        pages_read=0, jsonld=0, microdata=0, rdfa=0, opengraph=0, app_state=0,
    )  # fmt: skip
    home = fetcher.get(target.url)
    if not home.ok:
        blocked = bool(home.challenge) or home.status_code in (401, 403, 429)
        row.homepage = "blocked" if blocked else "error"
        row.detail = failure_reason(home)
        return row

    home_page = to_page(target.url, home, target.url)
    row.platform = detect_platform(home.body)
    row.homepage_text_chars = len(home_page.text)
    row.js_shell = row.homepage_text_chars < SHELL_TEXT_CHARS

    for name, feed in FEEDS.items():  # every feed, whatever the platform claims
        setattr(row, name, len(feed(target.url, fetcher, home.body)))

    links = rank_links(home.body, target.url, target.domain)
    sitemap = sitemap_urls(target.url, fetcher, fetcher.sitemaps(target.url))
    row.sitemap_found = sitemap.found
    row.sitemap_product_urls = len(sitemap.products)

    candidates = (
        sitemap.products[:10] + sitemap.pages.product[:5] + links.product[:10]
        + links.collection[:5] + links.priority[:3]
    )  # fmt: skip
    urls = dedupe(candidates, {url_key(target.url)})[: max_pages - 1]
    pages = [home_page, *fetch_pages(urls, fetcher, max_pages - 1, target.url)]
    read = [p for p in pages if p.ok]
    row.pages_read = len(read)
    for page in read:
        for product in schema_products(page.html, page.url):
            setattr(row, product.source, getattr(row, product.source) + 1)
        row.opengraph += opengraph_product(page.html, page.url) is not None
        row.app_state += len(app_state_products(page.html, page.url))
    return row


@dataclass(frozen=True)
class SurveyResult:
    rows: list[SurveyRow]
    csv_path: Path
    report_path: Path

    @property
    def browser_candidates(self) -> list[SurveyRow]:
        return [r for r in self.rows if r.browser_candidate]


def run_survey(
    config: RunConfig,
    out_dir: Path,
    fetcher: Fetcher | None = None,
    progress: Callable[[int, int, SurveyRow], None] | None = None,
) -> SurveyResult:
    resolution = resolve(read_records(config.input), limit=config.limit)
    fetcher = fetcher or HttpFetcher(
        cache_dir=config.fetch.cache_dir,
        delay=config.fetch.delay_seconds,
        timeout=config.fetch.timeout_seconds,
        retries=config.fetch.retries,
        max_age_seconds=config.fetch.cache_max_age_hours * 3600,
    )
    targets = resolution.targets
    rows: list[SurveyRow] = []
    with ThreadPoolExecutor(max_workers=config.fetch.concurrency) as pool:
        for n, row in enumerate(pool.map(lambda t: survey_store(t, fetcher), targets), start=1):
            rows.append(row)
            log.info("[%d/%d] %s: %s", n, len(targets), row.domain, _verdict(row))
            if progress:
                progress(n, len(targets), row)

    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "survey.csv"
    columns = [f.name for f in fields(SurveyRow)]
    columns += ["readable_without_browser", "browser_candidate"]
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {**asdict(row), "readable_without_browser": row.readable_without_browser,
                 "browser_candidate": row.browser_candidate}
            )  # fmt: skip
    result = SurveyResult(rows=rows, csv_path=csv_path, report_path=out_dir / "survey.md")
    result.report_path.write_text(survey_report(result), encoding="utf-8")
    return result


def _verdict(row: SurveyRow) -> str:
    if row.homepage != "ok":
        return f"{row.homepage} ({row.detail})"
    if row.feed_products:
        return f"feed, {row.feed_products} products"
    if row.structured_products:
        return f"structured data, {row.structured_products} products"
    return "nothing readable without a browser" + (" (JavaScript shell)" if row.js_shell else "")


STAGES = (
    ("Shopify feed", "shopify_feed"),
    ("WooCommerce feed", "woocommerce_feed"),
    ("Squarespace feed", "squarespace_feed"),
    ("Lightspeed feed", "lightspeed_feed"),
    ("JSON-LD", "jsonld"),
    ("Microdata", "microdata"),
    ("RDFa", "rdfa"),
    ("OpenGraph", "opengraph"),
    ("App state", "app_state"),
)


def _candidate_lines(rows: list[SurveyRow]) -> list[str]:
    return [
        f"- {r.domain} ({r.platform}{', JavaScript shell' if r.js_shell else ''})" for r in rows
    ]


def _share(part: int, whole: int) -> str:
    return f" ({round(100 * part / whole)}%, PRD target 60%)" if whole else ""


def survey_report(result: SurveyResult) -> str:
    rows = result.rows
    reachable = [r for r in rows if r.homepage == "ok"]
    non_shopify = [r for r in reachable if r.platform != "shopify"]
    covered_ns = [r for r in non_shopify if r.readable_without_browser]
    candidates = result.browser_candidates
    lines = [
        "# Survey: coverage by stage",
        "",
        f"- Stores: {len(rows)}; homepage readable: {len(reachable)}; "
        f"blocked: {sum(r.homepage == 'blocked' for r in rows)}; "
        f"error: {sum(r.homepage == 'error' for r in rows)}",
        f"- Readable without a browser: {sum(r.readable_without_browser for r in rows)}",
        f"- Non-Shopify stores with at least one product: {len(covered_ns)} of {len(non_shopify)}"
        + _share(len(covered_ns), len(non_shopify)),
        "",
        "## Stores each stage can read",
        "",
        "| Stage | Stores | Products |",
        "|---|---:|---:|",
    ]
    for label, attr in STAGES:
        hits = [r for r in rows if getattr(r, attr)]
        lines.append(f"| {label} | {len(hits)} | {sum(getattr(r, attr) for r in rows)} |")
    lines += [
        "",
        "## Platforms",
        "",
        *[f"- `{p or 'unread'}`: {n}" for p, n in Counter(r.platform for r in rows).most_common()],
        "",
        "## Browser gate (PRD AQ-09)",
        "",
        f"Stores that load over HTTP but expose no products to any non-browser stage: "
        f"**{len(candidates)}** (gate: {BROWSER_GATE}).",
        "",
        *(_candidate_lines(candidates) or ["- none"]),
        "",
        "**Decision:** "
        + (
            "build the browser render stage (M4)."
            if len(candidates) >= BROWSER_GATE
            else "the browser stage is not needed for this list; keep it optional."
        ),
        "",
        "Per-store detail: `survey.csv`.",
    ]
    return "\n".join(lines) + "\n"

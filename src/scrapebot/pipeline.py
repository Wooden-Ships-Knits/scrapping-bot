"""One run, end to end: read links, visit each store, write tables, export, report.

Plain sequential orchestration (ADR 0003). Each store's rows are appended to the
canonical tables as soon as it is done, so a crash loses at most one store.
"""

import logging
import secrets
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from . import __version__
from .acquire import acquire
from .config import InputConfig, RunConfig
from .fetch import Fetcher, HttpFetcher
from .inputs.readers import InputError, InputRecord, read_file, read_text
from .inputs.resolve import Resolution, ResolvedInput, resolve
from .models import Acquired, Target
from .outputs import export
from .report import build_manifest, build_report, reconcile, write_manifest
from .store import RunStore
from .summary import summary_row, write_summary_csv
from .tables import ContactRow, InputRow, PageRow, ProductRow, Row, RunRow, StoreRow

log = logging.getLogger(__name__)

Progress = Callable[[int, int, Acquired], None]

REPORT_FILE = "report.md"  # written last: its presence marks a finished run
CONFIG_FILE = "config.json"  # written first, so an unfinished run can still be described


@dataclass(frozen=True)
class RunResult:
    run_id: str
    root: Path
    report_path: Path
    summary_path: Path
    links_in: int
    processed: int
    skipped: int
    stores: int
    exports: dict[str, list[Path]]


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def new_run_id(moment: datetime) -> str:
    """Sortable by start time to the millisecond, unique even for runs started together."""
    return f"{moment:%Y%m%dT%H%M%S}{moment.microsecond // 1000:03d}Z-{secrets.token_hex(3)}"


def load_records(cfg: InputConfig) -> list[InputRecord]:
    """The input links as supplied, unchecked."""
    if cfg.text is not None:
        return read_text(cfg.text)
    if cfg.source is not None:
        return read_file(cfg.source, cfg.url_column)
    raise InputError("No input: give a file or paste links")


def read_records(cfg: InputConfig) -> list[InputRecord]:
    """The input links, checked against the per-run maximum before anything is fetched."""
    records = load_records(cfg)
    if not records:
        raise InputError("The input holds no links")
    if len(records) > cfg.max_links:
        raise InputError(
            f"The input holds {len(records)} links; the limit per run is {cfg.max_links}. "
            "Split the list or raise input.max_links."
        )
    return records


def store_rows(run_id: str, target: Target, got: Acquired, fetched_at: str) -> Iterable[Row]:
    """Every table row one visited store produces."""
    yield StoreRow(
        run_id=run_id,
        domain=got.domain,
        url=got.url,
        status=got.status,
        error=got.error,
        platform=got.platform,
        currency=got.currency,
        currency_source=got.currency_source,
        source_used=got.source_used,
        layers_tried=got.layers_tried,
        product_count=len(got.products),
        page_count=len(got.read_pages),
        failed_page_count=len(got.pages) - len(got.read_pages),
        contact_count=len(got.contacts),
        ssl_bypassed=got.ssl_bypassed,
        input_ids=target.input_ids,
        fetched_at=fetched_at,
    )
    for p in got.products:
        yield ProductRow(
            run_id=run_id,
            domain=got.domain,
            **p.model_dump(include=set(ProductRow.model_fields) - {"run_id", "domain"}),
        )
    for page in got.pages:
        yield PageRow(
            run_id=run_id,
            domain=got.domain,
            url=page.url,
            page_kind=page.kind,
            http_status=page.http_status,
            error=page.error,
            text=page.text,
        )
    for c in got.contacts:
        yield ContactRow(
            run_id=run_id, domain=got.domain, type=c.type, value=c.value, source_url=c.source_url
        )


def _input_row(run_id: str, item: ResolvedInput) -> InputRow:
    return InputRow(
        run_id=run_id,
        input_id=item.input_id,
        raw=item.raw,
        url=item.url,
        domain=item.domain,
        status=item.status,
        is_deep_link=item.is_deep_link,
        meta=item.meta,
    )


@dataclass
class PreparedRun:
    """A run whose input has been read and checked, with its folder created.

    Nothing has been fetched yet. Splitting this from `execute` lets a caller (the
    web API) report input errors and the run id before the slow part starts.
    """

    config: RunConfig
    run_id: str
    started: datetime
    resolution: Resolution
    store: RunStore

    @property
    def root(self) -> Path:
        return self.store.root


def prepare(config: RunConfig) -> PreparedRun:
    """Read and resolve the input, then create the run folder with its `inputs` table.

    Raises `InputError` before creating anything if the input cannot be used.
    """
    started = _now()
    resolution = resolve(read_records(config.input), limit=config.limit)
    run_id = new_run_id(started)
    store = RunStore(config.output.runs_dir / run_id)
    store.append(_input_row(run_id, item) for item in resolution.inputs)
    (store.root / CONFIG_FILE).write_text(config.model_dump_json(indent=2), encoding="utf-8")
    log.info(
        "Run %s: %d links, %d stores to visit, %d skipped",
        run_id,
        len(resolution.inputs),
        len(resolution.targets),
        len(resolution.skipped),
    )
    return PreparedRun(config, run_id, started, resolution, store)


def execute(
    prepared: PreparedRun,
    fetcher: Fetcher | None = None,
    progress: Progress | None = None,
) -> RunResult:
    """Visit every store, then write exports, the summary, the report and the manifest."""
    config, run_id, store, resolution = (
        prepared.config,
        prepared.run_id,
        prepared.store,
        prepared.resolution,
    )
    t0 = time.monotonic()
    fetcher = fetcher or HttpFetcher(
        cache_dir=config.fetch.cache_dir,
        delay=config.fetch.delay_seconds,
        timeout=config.fetch.timeout_seconds,
        retries=config.fetch.retries,
    )
    by_id = {item.input_id: item for item in resolution.inputs}
    summary = []

    total = len(resolution.targets)
    for n, target in enumerate(resolution.targets, start=1):
        got = acquire(target, fetcher)
        store.append(store_rows(run_id, target, got, _iso(_now())))
        summary += [summary_row(by_id[i], got) for i in target.input_ids]
        log.info(
            "[%d/%d] %s: %s, %d products via %s",
            n,
            total,
            got.domain,
            got.status,
            len(got.products),
            got.source_used,
        )
        if progress:
            progress(n, total, got)

    visited = {i for t in resolution.targets for i in t.input_ids}
    summary += [
        summary_row(item, None) for item in resolution.inputs if item.input_id not in visited
    ]

    run_row = RunRow(
        run_id=run_id,
        started_at=_iso(prepared.started),
        finished_at=_iso(_now()),
        scrapebot_version=__version__,
        config=config.model_dump(mode="json"),
        input_count=len(resolution.inputs),
        store_count=total,
        limit=config.limit,
    )
    store.append([run_row])

    tables = store.load_tables()
    rows_by_table = {t.name: t.rows for t in tables}
    exports = export(tables, config.output.writers, store.root / "export")
    summary_path = write_summary_csv(resolution.inputs, summary, store.root / "summary.csv")

    duration = time.monotonic() - t0
    write_manifest(
        build_manifest(run_row, rows_by_table, exports, store.root, duration),
        store.root / "manifest.json",
    )
    report_path = store.root / REPORT_FILE
    report_path.write_text(
        build_report(run_row, rows_by_table, exports, store.root, duration), encoding="utf-8"
    )

    links_in, processed, skipped = reconcile(rows_by_table["inputs"])
    return RunResult(
        run_id=run_id,
        root=store.root,
        report_path=report_path,
        summary_path=summary_path,
        links_in=links_in,
        processed=processed,
        skipped=skipped,
        stores=total,
        exports=exports,
    )


def run(
    config: RunConfig,
    fetcher: Fetcher | None = None,
    progress: Progress | None = None,
) -> RunResult:
    """Run the whole pipeline for one input. Raises `InputError` before fetching anything
    if the input cannot be read."""
    return execute(prepare(config), fetcher=fetcher, progress=progress)

"""One run, end to end: read links, visit each store, write tables, export, report.

Plain orchestration (ADR 0003): a thread pool visits several stores at once while
the fetcher keeps one request at a time per host (PRD AQ-11). Each store's rows are
appended to the canonical tables as soon as it is done, so a crash or a stop loses
at most the stores in progress, and the run can be resumed.
"""

import json
import logging
import secrets
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import SecretStr

from . import __version__
from .acquire import acquire
from .config import FocusConfig, InputConfig, RunConfig
from .extract.focus import matched_items
from .extract.signals import is_knit
from .fetch import Fetcher, HttpFetcher
from .inputs.readers import InputError, InputRecord, read_file, read_text
from .inputs.resolve import Resolution, ResolvedInput, resolve
from .models import Acquired, Target
from .outputs import export
from .report import build_manifest, build_report, collect_stats, reconcile, write_manifest
from .store import JsonlRows, RunStore
from .summary import summary_row, write_summary_csv
from .tables import (
    ContactRow,
    InputRow,
    LLMCallRow,
    PageRow,
    ProductRow,
    Row,
    RunRow,
    StoreRow,
)

if TYPE_CHECKING:
    from .llm.gateway import Budget, LLMExtractor
    from .render import Renderer

log = logging.getLogger(__name__)

Progress = Callable[[int, int, Acquired], None]

REPORT_FILE = "report.md"  # written last: its presence marks a finished run
CONFIG_FILE = "config.json"  # written first, so an unfinished run can still be described
STOPPED_FILE = "stopped.json"  # present while a stopped run waits to be resumed
SUMMARY_ROWS_FILE = "summary.jsonl"  # summary rows, kept as stores finish, for resume


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
    stopped: bool = False


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


def store_rows(
    run_id: str,
    target: Target,
    got: Acquired,
    fetched_at: str,
    focus: FocusConfig | None = None,
) -> Iterable[Row]:
    """Every table row one visited store produces."""
    focus = focus or FocusConfig()
    matches = [matched_items(p, focus.items, focus.terms) for p in got.products]
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
        knit_count=sum(is_knit(p) for p in got.products),
        focus_count=sum(bool(m) for m in matches),
        page_count=len(got.read_pages),
        failed_page_count=len(got.pages) - len(got.read_pages),
        contact_count=len(got.contacts),
        ssl_bypassed=got.ssl_bypassed,
        llm_used=bool(got.llm_calls),
        llm_products_dropped=got.llm_products_dropped,
        store_type=got.store_type,
        input_ids=target.input_ids,
        fetched_at=fetched_at,
    )
    for call in got.llm_calls:
        yield LLMCallRow(run_id=run_id, domain=got.domain, **call.model_dump())
    for p, matched in zip(got.products, matches, strict=True):
        yield ProductRow(
            run_id=run_id,
            domain=got.domain,
            is_knitwear=is_knit(p),
            matched_items=matched,
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
            via=page.via,
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
    `done` holds the stores an earlier, stopped attempt already finished.
    """

    config: RunConfig
    run_id: str
    started: datetime
    resolution: Resolution
    store: RunStore
    done: set[str] = field(default_factory=set)

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


def resume(root: Path) -> PreparedRun:
    """Pick up a stopped or interrupted run where it left off (PRD OP-03).

    The input is read again and must give the same links; stores already in the
    `stores` table are not visited again.
    """
    root = Path(root)
    if (root / REPORT_FILE).exists():
        raise InputError(f"Run {root.name} is already finished")
    config = RunConfig.model_validate_json((root / CONFIG_FILE).read_text(encoding="utf-8"))
    resolution = resolve(read_records(config.input), limit=config.limit)
    store = RunStore(root)
    recorded = [row["raw"] for row in store.rows("inputs")]
    if recorded != [item.raw for item in resolution.inputs]:
        raise InputError("The input changed since this run started; start a new run instead")
    done = {row["domain"] for row in store.rows("stores")}
    (root / STOPPED_FILE).unlink(missing_ok=True)
    started = _started_of(root.name)
    log.info("Resuming run %s: %d of %d stores done", root.name, len(done), len(resolution.targets))
    return PreparedRun(config, root.name, started, resolution, store, done)


def _started_of(run_id: str) -> datetime:
    return datetime.strptime(run_id[:15], "%Y%m%dT%H%M%S").replace(tzinfo=UTC)


def _safe_acquire(
    target: Target,
    fetcher: Fetcher,
    llm: "LLMExtractor | None" = None,
    renderer: "Renderer | None" = None,
    render_pages: int = 10,
) -> Acquired:
    """A bug while reading one store is recorded on that store, never fatal to the run."""
    try:
        return acquire(target, fetcher, llm=llm, renderer=renderer, render_pages=render_pages)
    except Exception as exc:
        log.exception("Unexpected error while visiting %s", target.domain)
        return Acquired(
            domain=target.domain,
            url=target.url,
            status="error",
            error=f"internal error: {type(exc).__name__}: {exc}"[:300],
        )


def build_llm(config: RunConfig, keys: Mapping[str, SecretStr]) -> "tuple[LLMExtractor, Budget]":
    """The LLM stage for a run, with its budget."""
    from .llm.gateway import Budget, LiteLLMExtractor

    budget = Budget(config.llm.budget_usd)
    extractor = LiteLLMExtractor(
        config.llm.model,
        keys,
        budget,
        fallbacks=config.llm.fallbacks,
        api_base=config.llm.api_base,
    )
    return extractor, budget


def build_renderer(config: RunConfig, fetcher: Fetcher) -> "Renderer | None":
    """The browser for a run, or None when it is off, not installed, or the fetcher
    cannot share its politeness with it (a test double)."""
    from .render import CamoufoxRenderer, camoufox_available

    if not config.render.enabled:
        return None
    if not isinstance(fetcher, HttpFetcher):
        return None
    if not camoufox_available():
        log.warning(
            "Camoufox is not installed: JavaScript-only stores stay js_required. "
            "Install it with: make install"
        )
        return None
    return CamoufoxRenderer(
        fetcher,
        workers=config.render.browsers,
        timeout_seconds=config.render.timeout_seconds,
        settle_seconds=config.render.settle_seconds,
    )


def execute(
    prepared: PreparedRun,
    fetcher: Fetcher | None = None,
    progress: Progress | None = None,
    stop: threading.Event | None = None,
    keys: Mapping[str, SecretStr] | None = None,
    llm: "LLMExtractor | None" = None,
    renderer: "Renderer | None" = None,
) -> RunResult:
    """Visit every store, several at once, then write the exports, summary, manifest and,
    last, the report. When `stop` is set, the stores in progress finish, nothing new
    starts, and the run is left resumable."""
    config = prepared.config
    t0 = time.monotonic()
    fetcher = fetcher or HttpFetcher(
        cache_dir=config.fetch.cache_dir,
        delay=config.fetch.delay_seconds,
        timeout=config.fetch.timeout_seconds,
        retries=config.fetch.retries,
    )
    if llm is None and config.llm.enabled:
        llm, _ = build_llm(config, keys or {})
    own_renderer = renderer is None
    if renderer is None:
        renderer = build_renderer(config, fetcher)
    try:
        return _visit_and_write(prepared, fetcher, progress, stop, llm, renderer, t0)
    finally:
        if own_renderer and renderer is not None:
            renderer.close()


def _visit_and_write(
    prepared: PreparedRun,
    fetcher: Fetcher,
    progress: Progress | None,
    stop: threading.Event | None,
    llm: "LLMExtractor | None",
    renderer: "Renderer | None",
    t0: float,
) -> RunResult:
    config, run_id, store, resolution = (
        prepared.config,
        prepared.run_id,
        prepared.store,
        prepared.resolution,
    )
    by_id = {item.input_id: item for item in resolution.inputs}
    summary_file = store.root / SUMMARY_ROWS_FILE
    todo = [t for t in resolution.targets if t.domain not in prepared.done]
    total, finished = len(resolution.targets), len(prepared.done)

    def record(target: Target, got: Acquired) -> None:
        store.append(store_rows(run_id, target, got, _iso(_now()), config.focus))
        _append_json_lines(summary_file, [summary_row(by_id[i], got) for i in target.input_ids])

    with ThreadPoolExecutor(max_workers=config.fetch.concurrency) as pool:
        queue = iter(todo)
        running: dict[Future[Acquired], Target] = {}

        def fill() -> None:
            while len(running) < config.fetch.concurrency and not (stop and stop.is_set()):
                target = next(queue, None)
                if target is None:
                    return
                running[
                    pool.submit(
                        _safe_acquire, target, fetcher, llm, renderer, config.render.max_pages
                    )
                ] = target

        fill()
        while running:
            completed, _ = wait(running, return_when=FIRST_COMPLETED)
            for future in completed:
                target = running.pop(future)
                got = future.result()
                record(target, got)
                finished += 1
                log.info(
                    "[%d/%d] %s: %s, %d products via %s",
                    finished,
                    total,
                    got.domain,
                    got.status,
                    len(got.products),
                    got.source_used,
                )
                if progress:
                    progress(finished, total, got)
            fill()

    remaining = total - finished
    if remaining:
        _append_json_lines(
            store.root / STOPPED_FILE, [{"remaining": remaining, "at": _iso(_now())}]
        )
        log.info("Run %s stopped with %d stores left; resume it to continue", run_id, remaining)
        links_in, processed, skipped = reconcile(store.read("inputs"))
        return RunResult(
            run_id=run_id,
            root=store.root,
            report_path=store.root / REPORT_FILE,
            summary_path=store.root / "summary.csv",
            links_in=links_in,
            processed=processed,
            skipped=skipped,
            stores=finished,
            exports={},
            stopped=True,
        )

    visited = {i for t in resolution.targets for i in t.input_ids}
    _append_json_lines(
        summary_file,
        [summary_row(item, None) for item in resolution.inputs if item.input_id not in visited],
    )

    llm_cost = sum(call["cost_usd"] for call in store.rows("llm_calls"))
    run_row = RunRow(
        run_id=run_id,
        started_at=_iso(prepared.started),
        finished_at=_iso(_now()),
        scrapebot_version=__version__,
        config=config.model_dump(mode="json"),
        input_count=len(resolution.inputs),
        store_count=total,
        limit=config.limit,
        llm_cost_usd=round(llm_cost, 6),
    )
    store.append([run_row])

    exports = export(store.load_tables(), config.output.writers, store.root / "export")
    summary_path = write_summary_csv(
        resolution.inputs, list(JsonlRows(summary_file)), store.root / "summary.csv"
    )

    stats = collect_stats(store)
    duration = time.monotonic() - t0
    write_manifest(
        build_manifest(run_row, stats, exports, store.root, duration),
        store.root / "manifest.json",
    )
    report_path = store.root / REPORT_FILE
    report_path.write_text(
        build_report(run_row, stats, exports, store.root, duration), encoding="utf-8"
    )

    links_in, processed, skipped = reconcile(stats.inputs)
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


def _append_json_lines(path: Path, rows: list[dict[str, Any]]) -> None:
    if rows:
        with path.open("a", encoding="utf-8") as fh:
            fh.write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


def run(
    config: RunConfig,
    fetcher: Fetcher | None = None,
    progress: Progress | None = None,
    keys: Mapping[str, SecretStr] | None = None,
) -> RunResult:
    """Run the whole pipeline for one input. Raises `InputError` before fetching anything
    if the input cannot be read."""
    return execute(prepare(config), fetcher=fetcher, progress=progress, keys=keys)

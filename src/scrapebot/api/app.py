"""HTTP routes for the bulk interface. Binds to localhost only (ADR 0007)."""

import asyncio
import re
import secrets
from collections import Counter
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from anyio import to_thread
from fastapi import FastAPI, File, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..config import InputConfig, RunConfig
from ..inputs.readers import SUPPORTED_SUFFIXES, InputError
from ..inputs.resolve import DUPLICATE, resolve
from ..outputs import available_writers
from ..pipeline import load_records, prepare, resume
from . import library
from .manager import FetcherFactory, RunManager
from .schemas import (
    ErrorOut,
    OptionsOut,
    OverviewOut,
    PreviewIn,
    PreviewOut,
    RowsOut,
    RunIn,
    RunListItem,
    RunOut,
    SkippedLink,
    SourceIn,
    UploadOut,
)

UPLOAD_ID_RE = re.compile(r"^[0-9a-f]{32}$")
SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
EXAMPLES = 8
FINISHED = ("done", "failed", "interrupted", "stopped")


class ApiSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base: RunConfig = Field(default_factory=RunConfig)  # fetch and output defaults for runs
    uploads_dir: Path = Path("data/uploads")
    web_dist: Path | None = None  # the built web app; served at / when present
    max_upload_mb: int = 20
    poll_seconds: float = 0.5


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


def create_app(
    settings: ApiSettings | None = None, fetcher_factory: FetcherFactory | None = None
) -> FastAPI:
    settings = settings or ApiSettings()
    manager = RunManager(fetcher_factory)
    runs_dir = settings.base.output.runs_dir

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        manager.shutdown()

    app = FastAPI(title="scrapebot", version="2", lifespan=lifespan)
    app.state.manager = manager

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        body = ErrorOut(code=exc.code, message=exc.message)
        return JSONResponse(status_code=exc.status, content={"detail": body.model_dump()})

    def input_config(source: SourceIn, url_column: str) -> InputConfig:
        base = settings.base.input
        if source.text is not None:
            return InputConfig(text=source.text, url_column=url_column, max_links=base.max_links)
        upload_id = source.upload_id or ""
        folder = settings.uploads_dir / upload_id
        files = list(folder.iterdir()) if UPLOAD_ID_RE.match(upload_id) and folder.is_dir() else []
        if len(files) != 1:
            raise ApiError(404, "upload_not_found", "File unggahan tidak ditemukan; unggah ulang.")
        return InputConfig(source=files[0], url_column=url_column, max_links=base.max_links)

    def root_or_404(run_id: str) -> Path:
        root = library.run_root(runs_dir, run_id)
        if root is None:
            raise ApiError(404, "run_not_found", f"Run {run_id} tidak ditemukan.")
        return root

    def load(run_id: str) -> RunOut:
        root = root_or_404(run_id)
        live = manager.get(run_id)
        return library.load_run(root, live.state if live else None, live.error if live else "")

    def start(cfg: RunConfig) -> RunOut:
        try:
            prepared = prepare(cfg)
        except InputError as exc:
            raise ApiError(422, "bad_input", str(exc)) from exc
        manager.submit(prepared)
        return load(prepared.run_id)

    @app.get("/api/options")
    def options() -> OptionsOut:
        return OptionsOut(
            writers=list(available_writers()),
            default_writers=settings.base.output.writers,
            suffixes=list(SUPPORTED_SUFFIXES),
            max_links=settings.base.input.max_links,
            default_test_limit=2,
            max_upload_mb=settings.max_upload_mb,
        )

    @app.post("/api/uploads", status_code=201)
    async def upload(file: Annotated[UploadFile, File()]) -> UploadOut:
        name = SAFE_NAME_RE.sub("_", Path(file.filename or "links.txt").name).strip("._") or "links"
        if Path(name).suffix.lower() not in SUPPORTED_SUFFIXES:
            raise ApiError(
                415,
                "unsupported_format",
                f"Format tidak didukung. Gunakan: {', '.join(SUPPORTED_SUFFIXES)}",
            )
        limit = settings.max_upload_mb * 1024 * 1024
        data = await file.read(limit + 1)
        if len(data) > limit:
            raise ApiError(413, "too_large", f"File lebih dari {settings.max_upload_mb} MB.")
        upload_id = secrets.token_hex(16)
        folder = settings.uploads_dir / upload_id
        folder.mkdir(parents=True)
        (folder / name).write_bytes(data)
        return UploadOut(upload_id=upload_id, filename=name, size_bytes=len(data))

    @app.post("/api/preview")
    def preview(body: PreviewIn) -> PreviewOut:
        cfg = input_config(body.source, body.url_column)
        try:
            records = load_records(cfg)
        except InputError as exc:
            raise ApiError(422, "bad_input", str(exc)) from exc
        resolution = resolve(records)
        skipped = [i for i in resolution.inputs if i.status not in ("processed", DUPLICATE)]
        return PreviewOut(
            links=len(records),
            stores=len(resolution.targets),
            duplicates=sum(1 for i in resolution.inputs if i.status == DUPLICATE),
            skipped=dict(Counter(i.status for i in skipped).most_common()),
            skipped_examples=[SkippedLink(raw=i.raw, reason=i.status) for i in skipped[:EXAMPLES]],
            store_examples=[t.domain for t in resolution.targets[:EXAMPLES]],
            max_links=cfg.max_links,
            too_many=len(records) > cfg.max_links,
            tested=library.fingerprint(r.value for r in records)
            in library.tested_fingerprints(runs_dir),
        )

    @app.post("/api/runs", status_code=202)
    def create_run(body: RunIn) -> RunOut:
        cfg_input = input_config(body.source, body.url_column)
        if not body.test_mode and not body.skip_test_run:
            try:
                links = [r.value for r in load_records(cfg_input)]
            except InputError as exc:
                raise ApiError(422, "bad_input", str(exc)) from exc
            if library.fingerprint(links) not in library.tested_fingerprints(runs_dir):
                raise ApiError(
                    409,
                    "test_run_required",
                    "Jalankan mode uji dulu untuk daftar ini, atau pilih untuk melewatinya.",
                )
        data = settings.base.model_dump()
        data["input"] = cfg_input.model_dump()
        data["output"]["writers"] = body.writers
        data["limit"] = body.test_limit if body.test_mode else None
        try:
            cfg = RunConfig.model_validate(data)
        except ValidationError as exc:
            raise ApiError(422, "bad_settings", exc.errors()[0]["msg"]) from exc
        return start(cfg)

    @app.post("/api/runs/{run_id}/full", status_code=202)
    def full_run(run_id: str) -> RunOut:
        """Run the whole list of a finished test run, with the same input and formats."""
        root = root_or_404(run_id)
        test = load(run_id)
        if test.mode != "test" or test.state != "done":
            raise ApiError(
                409, "not_a_finished_test", "Hanya run uji yang selesai bisa dilanjutkan."
            )
        cfg = RunConfig.model_validate_json((root / "config.json").read_text(encoding="utf-8"))
        return start(cfg.model_copy(update={"limit": None}))

    @app.post("/api/runs/{run_id}/stop", status_code=202)
    def stop_run(run_id: str) -> RunOut:
        """Finish the stores in progress, start no new ones; the run stays resumable."""
        root_or_404(run_id)
        if not manager.stop(run_id):
            raise ApiError(409, "not_running", "Run ini tidak sedang berjalan.")
        return load(run_id)

    @app.post("/api/runs/{run_id}/resume", status_code=202)
    def resume_run(run_id: str) -> RunOut:
        """Continue a stopped or interrupted run without revisiting finished stores."""
        root = root_or_404(run_id)
        if load(run_id).state not in ("stopped", "interrupted"):
            raise ApiError(409, "not_resumable", "Hanya run yang berhenti yang bisa dilanjutkan.")
        try:
            prepared = resume(root)
        except InputError as exc:
            raise ApiError(422, "bad_input", str(exc)) from exc
        manager.submit(prepared)
        return load(run_id)

    @app.get("/api/runs")
    def runs() -> list[RunListItem]:
        return library.list_runs(runs_dir, manager.states())

    @app.get("/api/runs/{run_id}")
    def run_detail(run_id: str) -> RunOut:
        return load(run_id)

    @app.get("/api/runs/{run_id}/events")
    async def run_events(run_id: str, request: Request) -> StreamingResponse:
        """Server-sent events: the full run state each time it changes, until it ends."""
        root_or_404(run_id)

        async def stream() -> AsyncIterator[str]:
            last = ""
            while not await request.is_disconnected():
                run = await to_thread.run_sync(load, run_id)
                payload = run.model_dump_json()
                if payload != last:
                    last = payload
                    yield f"event: run\ndata: {payload}\n\n"
                if run.state in FINISHED:
                    break
                await asyncio.sleep(settings.poll_seconds)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/overview")
    def overview() -> OverviewOut:
        items = library.list_runs(runs_dir, manager.states())
        return OverviewOut(
            runs=len(items),
            runs_done=sum(1 for r in items if r.state == "done"),
            stores=sum(r.stores_done for r in items),
            products=sum(r.products for r in items),
            contacts=sum(r.contacts for r in items),
            last_run=items[0] if items else None,
        )

    @app.get("/api/runs/{run_id}/rows/{table}")
    def rows(
        run_id: str,
        table: str,
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        include_raw: bool = False,
    ) -> RowsOut:
        root = root_or_404(run_id)
        if table not in library.PREVIEW_TABLES:
            raise ApiError(404, "table_not_found", f"Tabel {table} tidak bisa dipratinjau.")
        columns, total, page, truncated = library.read_rows(root, table, offset, limit, include_raw)
        return RowsOut(
            table=table,
            columns=columns,
            total=total,
            offset=offset,
            rows=page,
            truncated_fields=truncated,
        )

    @app.get("/api/runs/{run_id}/download/{key}")
    def download(run_id: str, key: str) -> FileResponse:
        root = root_or_404(run_id)
        path = library.download_path(root, key)
        if path is None:
            raise ApiError(404, "download_not_found", "File ini tidak tersedia untuk run tersebut.")
        return FileResponse(path, filename=path.name)

    if settings.web_dist and (settings.web_dist / "index.html").exists():
        app.mount("/", StaticFiles(directory=settings.web_dist, html=True), name="web")

    return app

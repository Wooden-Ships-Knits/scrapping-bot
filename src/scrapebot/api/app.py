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
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from ..config import FocusConfig, InputConfig, RunConfig
from ..discover.agent import Completion, pick_agent_model
from ..discover.paid import Transport
from ..discover.regions import DEFAULT_REGION, REGIONS, discover_config
from ..extract.focus import DEFAULT_ITEMS, OTHER
from ..extract.focus import ITEMS as FOCUS_ITEMS
from ..inputs.readers import SUPPORTED_SUFFIXES, InputError
from ..inputs.resolve import DUPLICATE, resolve
from ..keys import load_keys
from ..llm.gateway import KEY_VARIABLES, check_connection, key_for, provider_of
from ..outputs import available_writers
from ..pipeline import load_records, prepare, resume
from . import library
from .discovery import DiscoveryManager
from .manager import FetcherFactory, RunManager
from .schemas import (
    DiscoverIn,
    DiscoverOptionsOut,
    DiscoveryOut,
    ErrorOut,
    LLMCheckIn,
    LLMCheckOut,
    OptionsOut,
    OverviewOut,
    PreviewIn,
    PreviewOut,
    ProviderOut,
    RowsOut,
    RunIn,
    RunListItem,
    RunOut,
    SkippedLink,
    SourceIn,
    UploadOut,
)

UPLOAD_ID_RE = re.compile(r"^[0-9a-f]{32}$")

# (provider, label, example model). Any LiteLLM provider/model works; these are offered.
PROVIDERS = (
    ("gemini", "Google Gemini", "gemini/gemini-3.5-flash"),
    ("openai", "OpenAI", "openai/gpt-4o-mini"),
    ("anthropic", "Anthropic Claude", "anthropic/claude-haiku-4-5-20251001"),
    ("mistral", "Mistral", "mistral/mistral-small-latest"),
    ("groq", "Groq", "groq/llama-3.3-70b-versatile"),
    ("openrouter", "OpenRouter", "openrouter/openai/gpt-4o-mini"),
    ("azure", "Azure OpenAI", "azure/<deployment-name>"),
    ("ollama", "Ollama (lokal)", "ollama/qwen2.5:3b"),
)
SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
EXAMPLES = 8
MAX_DISCOVER_COUNT = 500
FINISHED = ("done", "failed", "interrupted", "stopped")


class ApiSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base: RunConfig = Field(default_factory=RunConfig)  # fetch and output defaults for runs
    uploads_dir: Path = Path("data/uploads")
    web_dist: Path | None = None  # the built web app; served at / when present
    max_upload_mb: int = 20
    poll_seconds: float = 0.5
    env_file: Path = Path(".env")  # provider keys; read, never written
    discover_dir: Path = Path("data/discover")  # stores found from the interface
    discover_cache_dir: Path = Path("data/.cache/discover")  # paid answers, without keys


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


def create_app(
    settings: ApiSettings | None = None,
    fetcher_factory: FetcherFactory | None = None,
    discover_transport: Transport | None = None,
    discover_completion: Completion | None = None,
) -> FastAPI:
    settings = settings or ApiSettings()
    manager = RunManager(fetcher_factory)
    finder = DiscoveryManager(discover_transport, discover_completion)
    runs_dir = settings.base.output.runs_dir

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        manager.shutdown()
        finder.shutdown()

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

    def run_keys(model: str, given: SecretStr | None) -> dict[str, SecretStr]:
        """Keys for a run: the one typed in the interface wins over .env and the environment."""
        given_map = {provider_of(model): given.get_secret_value()} if given and model else {}
        return load_keys(settings.env_file, given_map)

    def start(cfg: RunConfig, keys: dict[str, SecretStr] | None = None) -> RunOut:
        try:
            prepared = prepare(cfg)
        except InputError as exc:
            raise ApiError(422, "bad_input", str(exc)) from exc
        manager.submit(prepared, keys)
        return load(prepared.run_id)

    @app.get("/api/options")
    def options() -> OptionsOut:
        return OptionsOut(
            writers=list(available_writers()),
            default_writers=settings.base.output.writers,
            suffixes=list(SUPPORTED_SUFFIXES),
            max_links=settings.base.input.max_links,
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
        )

    @app.post("/api/runs", status_code=202)
    def create_run(body: RunIn) -> RunOut:
        data = settings.base.model_dump()
        data["input"] = input_config(body.source, body.url_column).model_dump()
        data["output"]["writers"] = body.writers
        keys: dict[str, SecretStr] = {}
        if body.llm and body.llm.enabled:
            data["llm"] = body.llm.model_dump(exclude={"api_key"})
            keys = run_keys(body.llm.model, body.llm.api_key)
        try:
            cfg = RunConfig.model_validate(data)
        except ValidationError as exc:
            raise ApiError(422, "bad_settings", exc.errors()[0]["msg"]) from exc
        if cfg.llm.enabled and not keys:  # switched on in the server's config file
            keys = run_keys(cfg.llm.model, None)
        return start(cfg, keys)

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
        live = manager.get(run_id)
        keys = dict(live.keys) if live and live.keys else run_keys(prepared.config.llm.model, None)
        manager.submit(prepared, keys)
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

    def discovery_sources(keys: dict[str, SecretStr]) -> dict[str, bool]:
        tavily = "tavily" in keys
        return {
            "google_places": "google_places" in keys,
            "web_search": tavily,
            "social_search": tavily,
            "ai_agent": bool(pick_agent_model(keys)),
        }

    @app.get("/api/discover/options")
    def discover_options() -> DiscoverOptionsOut:
        """What the interface offers for finding stores, and which sources have a key.
        Keys themselves are never sent."""
        keys = load_keys(settings.env_file)
        return DiscoverOptionsOut(
            regions=list(REGIONS),
            default_region=DEFAULT_REGION,
            items=[*FOCUS_ITEMS, OTHER],
            default_items=list(DEFAULT_ITEMS),
            max_count=MAX_DISCOVER_COUNT,
            agent_model=pick_agent_model(keys),
            sources=discovery_sources(keys),
        )

    @app.post("/api/discover", status_code=202)
    def start_discovery(body: DiscoverIn) -> DiscoveryOut:
        """Find stores, then start a run on all of them; poll GET /api/discover/{id}."""
        if body.region not in REGIONS:
            raise ApiError(422, "bad_region", f"Region {body.region} tidak dikenal.")
        if OTHER in body.items and not any(t.strip() for t in body.terms):
            raise ApiError(422, "terms_required", "Isi kata kunci untuk item Lainnya.")
        keys = load_keys(settings.env_file)
        if not any(discovery_sources(keys).values()):
            raise ApiError(
                422,
                "no_discovery_source",
                "Belum ada API key untuk mencari toko. Isi OPENAI_API_KEY, GEMINI_API_KEY, "
                "GOOGLE_MAPS_API_KEY atau TAVILY_API_KEY di .env, lalu jalankan ulang server.",
            )
        try:
            focus = FocusConfig(items=body.items, terms=body.terms)
            config = discover_config(
                body.count, body.region, focus.items, focus.terms, pick_agent_model(keys)
            ).model_copy(
                update={"out_dir": settings.discover_dir, "cache_dir": settings.discover_cache_dir}
            )
            base = settings.base.model_dump()
            base["output"]["writers"] = body.writers
            base["focus"] = focus.model_dump()
            RunConfig.model_validate(base)  # fail now, not after paying for the search
        except ValidationError as exc:
            raise ApiError(422, "bad_settings", exc.errors()[0]["msg"]) from exc

        def start_run(links: Path) -> str:
            data = {**base, "input": {**base["input"], "source": links, "text": None}}
            data["input"]["url_column"] = "website"
            prepared = prepare(RunConfig.model_validate(data))
            manager.submit(prepared, keys)
            return prepared.run_id

        return finder.submit(config, keys, start_run).out()

    @app.get("/api/discover/{discovery_id}")
    def discovery(discovery_id: str) -> DiscoveryOut:
        job = finder.get(discovery_id)
        if job is None:
            raise ApiError(404, "discovery_not_found", "Pencarian ini tidak ditemukan.")
        return job.out()

    @app.get("/api/llm/providers")
    def llm_providers() -> list[ProviderOut]:
        """The supported providers (PRD LM-02) and whether .env already has a key for each.
        Keys themselves are never sent."""
        env_keys = load_keys(settings.env_file)
        return [
            ProviderOut(
                provider=provider,
                label=label,
                example_model=example,
                needs_key=provider in KEY_VARIABLES,
                key_in_env=provider in env_keys,
            )
            for provider, label, example in PROVIDERS
        ]

    @app.post("/api/llm/check")
    def llm_check(body: LLMCheckIn) -> LLMCheckOut:
        """Prove a key and model work before a run (PRD LM-05)."""
        if "/" not in body.model:
            return LLMCheckOut(ok=False, message="Tulis model sebagai penyedia/model.")
        keys = run_keys(body.model, body.api_key)
        ok, message = check_connection(body.model, key_for(body.model, keys), body.api_base)
        return LLMCheckOut(ok=ok, message=message)

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

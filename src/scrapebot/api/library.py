"""Reading run folders from disk.

The run folder is the source of truth: a closed browser or a restarted server loses
nothing. The in-memory manager only adds whether a run is queued or running.
"""

import json
import re
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from ..config import DEFAULT_LLM_MODEL, LLMConfig
from ..final import qualifies
from ..pipeline import CONFIG_FILE, REPORT_FILE, STOPPED_FILE
from .schemas import DownloadOut, RunListItem, RunOut, RunState, StoreOut

RUN_ID_RE = re.compile(r"^\d{8}T\d{9}Z-[0-9a-f]{6}$")  # 20261005T085253123Z-56162b

# key -> (label, path inside the run folder). Directories are served as a zip.
DOWNLOADS: dict[str, tuple[str, str]] = {
    "final_xlsx": (
        "Daftar final: toko multi-brand + produk rajut (.xlsx)",
        "export/final/tables.xlsx",
    ),
    "final_csv": ("Daftar final (CSV .zip)", "export/final/csv"),
    "report": ("Laporan run (.md)", REPORT_FILE),
    "summary": ("Ringkasan per tautan (.csv)", "summary.csv"),
    "xlsx": ("Excel (.xlsx)", "export/tables.xlsx"),
    "csv": ("CSV (.zip)", "export/csv"),
    "tsv": ("TSV (.zip)", "export/tsv"),
    "parquet": ("Parquet (.zip)", "export/parquet"),
    "json": ("JSON (.zip)", "export/json"),
    "jsonl": ("JSONL (.zip)", "export/jsonl"),
    "sqlite": ("SQLite (.sqlite)", "export/tables.sqlite"),
    "duckdb": ("DuckDB (.duckdb)", "export/tables.duckdb"),
    "manifest": ("Manifest (.json)", "manifest.json"),
}


def run_root(runs_dir: Path, run_id: str) -> Path | None:
    """The folder of a run, or None. Only well-formed ids are accepted (no path tricks)."""
    if not RUN_ID_RE.match(run_id):
        return None
    root = runs_dir / run_id
    return root if (root / CONFIG_FILE).exists() else None


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Rows of a table that may be being appended to: a half-written last line is skipped."""
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


def _config(root: Path) -> dict[str, Any]:
    return json.loads((root / CONFIG_FILE).read_text(encoding="utf-8"))


def _source(config: dict[str, Any]) -> tuple[Literal["text", "file"], str]:
    source = config["input"].get("source")
    if source:
        return "file", Path(source).name
    return "text", "Tautan yang ditempel"


def is_finished(root: Path) -> bool:
    return (root / REPORT_FILE).exists()


def run_roots(runs_dir: Path) -> list[Path]:
    """Run folders, newest first."""
    if not runs_dir.exists():
        return []
    roots = [
        p for p in runs_dir.iterdir() if RUN_ID_RE.match(p.name) and (p / CONFIG_FILE).exists()
    ]
    return sorted(roots, key=lambda p: p.name, reverse=True)


def _state(root: Path, live_state: RunState | None) -> RunState:
    if is_finished(root):
        return "done"
    if live_state in ("queued", "running", "failed"):
        return live_state
    return "stopped" if (root / STOPPED_FILE).exists() else live_state or "interrupted"


def downloads(root: Path) -> list[DownloadOut]:
    out = []
    for key, (label, rel) in DOWNLOADS.items():
        path = root / rel
        if path.is_file() or (path.is_dir() and any(path.iterdir())):
            if path.is_dir():
                filename = f"{root.name}-{key}.zip"
            elif key.startswith("final_"):  # not a second "tables.xlsx" in Downloads
                filename = f"{root.name}-final{path.suffix}"
            else:
                filename = path.name
            out.append(DownloadOut(key=key, label=label, filename=filename))
    return out


def download_path(root: Path, key: str) -> Path | None:
    """The file to send for a download key; directories are zipped once and reused."""
    if key not in DOWNLOADS or not is_finished(root):
        return None
    path = root / DOWNLOADS[key][1]
    if path.is_file():
        return path
    if not path.is_dir():
        return None
    archive = root / "export" / f"{root.name}-{key}.zip"
    if not archive.exists():
        tmp = archive.with_suffix(".zip.part")
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            for file in sorted(path.iterdir()):
                zf.write(file, arcname=file.name)
        tmp.rename(archive)
    return archive


PREVIEW_MAX_CHARS = 600
PREVIEW_TABLES = (
    "final_stores", "final_products", "stores", "products", "contacts", "pages", "inputs",
)  # fmt: skip


def _shorten(value: Any) -> tuple[Any, bool]:
    if isinstance(value, str) and len(value) > PREVIEW_MAX_CHARS:
        return value[:PREVIEW_MAX_CHARS] + "…", True
    return value, False


def read_rows(
    root: Path, table: str, offset: int, limit: int, include_raw: bool = False
) -> tuple[list[str], int, list[dict[str, Any]], bool]:
    """(columns, total, rows, truncated) for one page of a table, streamed from JSONL.

    Long text is shortened and the bulky `raw` source object is left out unless asked
    for: the preview is for looking, the downloads hold everything.
    """
    from ..tables import FINAL_TABLES, TABLES

    model = {**TABLES, **FINAL_TABLES}[table]
    columns = [c for c in model.model_fields if include_raw or c != "raw"]
    rows: list[dict[str, Any]] = []
    total, truncated = 0, False
    path = root / "tables" / f"{table}.jsonl"
    if path.exists():
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                if offset <= total < offset + limit:
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    shown = {}
                    for key in columns:
                        shown[key], cut = _shorten(row.get(key))
                        truncated |= cut
                    rows.append(shown)
                total += 1
    return columns, total, rows, truncated


def cli_command(config: dict[str, Any]) -> str:
    """The command line that runs the same settings."""
    source = config["input"].get("source")
    parts = ["uv run scrapebot run", f'"{source}"' if source else "links.txt"]
    if config.get("limit"):
        parts.append(f"--limit {config['limit']}")
    parts.append("-f " + ",".join(config["output"]["writers"]))
    if config["input"].get("url_column", "auto") != "auto":
        parts.append(f"--url-column {config['input']['url_column']}")
    llm = config.get("llm") or {}
    if not (llm.get("enabled") and llm.get("model")):
        parts.append("--no-llm")
    else:  # only what differs from the defaults (LLMConfig)
        if llm["model"] != DEFAULT_LLM_MODEL:
            parts.append(f"--llm {llm['model']}")
        parts += [f"--llm-fallback {m}" for m in llm.get("fallbacks", [])]
        if llm.get("budget_usd", 1.0) != LLMConfig().budget_usd:
            parts.append(f"--llm-budget {llm['budget_usd']}")
        if llm.get("api_base"):
            parts.append(f"--llm-api-base {llm['api_base']}")
    return " ".join(parts)


def load_run(
    root: Path,
    live_state: RunState | None = None,
    error: str = "",
    with_stores: bool = True,
) -> RunOut:
    config = _config(root)
    inputs = read_jsonl(root / "tables" / "inputs.jsonl")
    stores = read_jsonl(root / "tables" / "stores.jsonl")
    runs = read_jsonl(root / "tables" / "runs.jsonl")
    skipped = Counter(i["status"] for i in inputs if i["status"] != "processed")
    processed = sum(1 for i in inputs if i["status"] == "processed")
    kind, name = _source(config)
    llm = config.get("llm") or {}
    llm_calls = read_jsonl(root / "tables" / "llm_calls.jsonl")
    started = runs[0]["started_at"] if runs else _started_from_id(root.name)
    return RunOut(
        run_id=root.name,
        state=_state(root, live_state),
        mode="test" if config.get("limit") else "full",
        limit=config.get("limit"),
        started_at=started,
        finished_at=runs[0]["finished_at"] if runs else "",
        source_kind=kind,
        source_name=name,
        writers=config["output"]["writers"],
        links_in=len(inputs),
        processed=processed,
        skipped=len(inputs) - processed,
        skipped_by_reason=dict(skipped.most_common()),
        stores_total=processed,
        stores_done=len(stores),
        status_counts=dict(Counter(s["status"] for s in stores).most_common()),
        products=sum(s["product_count"] for s in stores),
        pages=sum(s["page_count"] for s in stores),
        contacts=sum(s["contact_count"] for s in stores),
        final_stores=sum(1 for s in stores if qualifies(s)),
        final_products=sum(s.get("knit_kind_count", 0) for s in stores if qualifies(s)),
        stores=[StoreOut.model_validate(s, from_attributes=False) for s in _store_fields(stores)]
        if with_stores
        else [],
        downloads=downloads(root) if is_finished(root) else [],
        error=error,
        config=_public_config(config),
        cli=cli_command(config),
        llm_model=llm["model"] if llm.get("enabled") else "",
        llm_cost_usd=round(sum(c["cost_usd"] for c in llm_calls), 6),
        llm_stores=sum(1 for s in stores if s.get("llm_used")),
    )


def _public_config(config: dict[str, Any]) -> dict[str, Any]:
    """The config as shown in the interface: pasted text is summarised, not repeated."""
    shown = json.loads(json.dumps(config))
    text = shown["input"].get("text")
    if text:
        shown["input"]["text"] = f"{len(text)} characters of pasted links"
    return shown


def _store_fields(stores: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keep = set(StoreOut.model_fields)
    return [{k: v for k, v in s.items() if k in keep} for s in stores]


def started_at(root: Path) -> str:
    runs = read_jsonl(root / "tables" / "runs.jsonl")
    return runs[0]["started_at"] if runs else _started_from_id(root.name)


def _started_from_id(run_id: str) -> str:
    stamp = run_id.split("-")[0]
    return (
        f"{stamp[0:4]}-{stamp[4:6]}-{stamp[6:8]}T{stamp[9:11]}:{stamp[11:13]}:{stamp[13:15]}+00:00"
    )


def list_runs(runs_dir: Path, live: dict[str, RunState]) -> list[RunListItem]:
    items = []
    for root in run_roots(runs_dir):
        run = load_run(root, live.get(root.name), with_stores=False)
        items.append(
            RunListItem(
                run_id=run.run_id,
                state=run.state,
                mode=run.mode,
                started_at=run.started_at,
                source_name=run.source_name,
                links_in=run.links_in,
                stores_total=run.stores_total,
                stores_done=run.stores_done,
                products=run.products,
                contacts=run.contacts,
            )
        )
    return items

"""The run report (PRD OP-02) and the run manifest.

The report is for people: reconciliation first, then what to look at. The
manifest is for machines: the exact config (never secrets), versions and counts.
"""

import json
import platform
import sys
from collections import Counter
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from .tables import RunRow

MANIFEST_PACKAGES = (
    "scrapebot", "requests", "beautifulsoup4", "lxml", "pydantic", "tldextract",
    "urlextract", "openpyxl", "pyarrow", "duckdb",
)  # fmt: skip

# Stages in the architecture that this build cannot run yet. Listed in every report
# so an empty result is never mistaken for "nothing there".
UNAVAILABLE_STAGES = (
    "LLM extraction (planned, M3)",
    "Browser render (gated on the M1 survey, M4)",
    "Change detection against earlier runs (planned, M5)",
)


def reconcile(inputs: list[dict[str, Any]]) -> tuple[int, int, int]:
    """(links in, processed, skipped). The first always equals the sum of the others."""
    processed = sum(1 for i in inputs if i["status"] == "processed")
    return len(inputs), processed, len(inputs) - processed


def _location(paths: list[Path], root: Path) -> str:
    """One file, or the folder holding a writer's files."""
    if len(paths) == 1:
        return str(paths[0].relative_to(root))
    return f"{paths[0].parent.relative_to(root)}/"


def _bullets(items: list[str]) -> list[str]:
    return [f"- {i}" for i in items] or ["- none"]


def _table(header: tuple[str, str], counts: Counter[str]) -> list[str]:
    rows = [f"| {header[0]} | {header[1]} |", "|---|---:|"]
    rows += [f"| `{key or '-'}` | {n} |" for key, n in counts.most_common()]
    return rows if counts else ["- none"]


def build_report(
    run: RunRow,
    tables: dict[str, list[dict[str, Any]]],
    exports: dict[str, list[Path]],
    root: Path,
    duration_seconds: float,
) -> str:
    inputs, stores = tables["inputs"], tables["stores"]
    links_in, processed, skipped = reconcile(inputs)
    balanced = links_in == processed + skipped
    by_status: Counter[str] = Counter(s["status"] for s in stores)
    by_source: Counter[str] = Counter(p["source"] for p in tables["products"])
    by_contact: Counter[str] = Counter(c["type"] for c in tables["contacts"])

    def domains(status: str) -> list[str]:
        return [s["domain"] for s in stores if s["status"] == status]

    mode = f"test mode, first {run.limit} stores" if run.limit else "full run"
    lines = [
        f"# Run report: {run.run_id}",
        "",
        f"- Started {run.started_at}, finished {run.finished_at} ({duration_seconds:.0f} s)",
        f"- Mode: {mode}",
        f"- scrapebot {run.scrapebot_version}",
        "",
        "## Reconciliation",
        "",
        f"**Links in: {links_in} = processed {processed} + skipped {skipped}** "
        + ("(balanced)" if balanced else "(MISMATCH: report this as a bug)"),
        "",
        *_table(
            ("Skip reason", "Links"),
            Counter(i["status"] for i in inputs if i["status"] != "processed"),
        ),
        "",
        "## Stores",
        "",
        f"{len(stores)} stores visited.",
        "",
        *_table(("Status", "Stores"), by_status),
        "",
        "## Data collected",
        "",
        f"- Products: {len(tables['products'])}",
        f"- Pages: {len(tables['pages'])}",
        f"- Contacts: {len(tables['contacts'])}",
        "",
        "Products by source:",
        "",
        *_table(("Source", "Products"), by_source),
        "",
        "Contacts by type:",
        "",
        *_table(("Type", "Contacts"), by_contact),
        "",
        "## Needs a look",
        "",
        "Readable, but no catalogue found (`no_products`):",
        "",
        *_bullets(domains("no_products")),
        "",
        "JavaScript-only, needs a browser (`js_required`):",
        "",
        *_bullets(domains("js_required")),
        "",
        "Blocked or failed (`blocked`, `error`):",
        "",
        *_bullets(
            [
                f"{s['domain']}: {s['status']} ({s['error'] or 'no detail'})"
                for s in stores
                if s["status"] in ("blocked", "error")
            ]
        ),
        "",
        "Read with TLS verification off (`ssl_bypassed`):",
        "",
        *_bullets([s["domain"] for s in stores if s["ssl_bypassed"]]),
        "",
        "## Stages not available in this build",
        "",
        *_bullets(list(UNAVAILABLE_STAGES)),
        "",
        "## Files",
        "",
        "- `summary.csv`: one row per input link, v1 layout",
        "- `tables/`: canonical tables (JSONL)",
    ]
    for name, paths in exports.items():
        if paths:
            lines.append(f"- {name}: `{_location(paths, root)}`")
        else:
            lines.append(f"- {name}: **failed**, see the log; the other formats are unaffected")
    return "\n".join(lines) + "\n"


def package_versions() -> dict[str, str]:
    out = {}
    for name in MANIFEST_PACKAGES:
        try:
            out[name] = version(name)
        except PackageNotFoundError:
            out[name] = "not installed"
    return out


def build_manifest(
    run: RunRow,
    tables: dict[str, list[dict[str, Any]]],
    exports: dict[str, list[Path]],
    root: Path,
    duration_seconds: float,
) -> dict[str, Any]:
    links_in, processed, skipped = reconcile(tables["inputs"])
    return {
        "run_id": run.run_id,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "duration_seconds": round(duration_seconds, 1),
        "config": run.config,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "packages": package_versions(),
        "counts": {
            "links_in": links_in,
            "processed": processed,
            "skipped": skipped,
            **{name: len(rows) for name, rows in tables.items()},
        },
        "exports": {
            name: [str(p.relative_to(root)) for p in paths] for name, paths in exports.items()
        },
    }


def write_manifest(manifest: dict[str, Any], path: Path) -> Path:
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path

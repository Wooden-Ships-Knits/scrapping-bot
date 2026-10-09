"""The run report (PRD OP-02) and the run manifest.

The report is for people: reconciliation first, then what to look at. The
manifest is for machines: the exact config (never secrets), versions and counts.
"""

import json
import platform
import sys
from collections import Counter
from dataclasses import dataclass, field
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .final import EXCLUSIONS, exclusion
from .tables import RunRow

if TYPE_CHECKING:
    from .store import RunStore

MANIFEST_PACKAGES = (
    "scrapebot", "requests", "beautifulsoup4", "lxml", "pydantic", "tldextract",
    "urlextract", "openpyxl", "pyarrow", "duckdb",
)  # fmt: skip

# Stages in the architecture that this build cannot run yet. Listed in every report
# so an empty result is never mistaken for "nothing there".
UNAVAILABLE_STAGES = ("Change detection against earlier runs (planned, M5)",)


@dataclass
class RunStats:
    """What the report and manifest need, gathered by streaming each table once.

    `inputs` and `stores` stay as rows (one per link or store); the large tables
    are only counted.
    """

    inputs: list[dict[str, Any]]
    stores: list[dict[str, Any]]
    counts: dict[str, int] = field(default_factory=dict)
    products_by_source: Counter[str] = field(default_factory=Counter)
    products_for_review: int = 0
    contacts_by_type: Counter[str] = field(default_factory=Counter)
    failed_pages: int = 0
    changes_by_type: Counter[str] = field(default_factory=Counter)
    llm_calls: list[dict[str, Any]] = field(default_factory=list)


def collect_stats(store: "RunStore") -> RunStats:
    stats = RunStats(inputs=store.read("inputs"), stores=store.read("stores"))
    for p in store.rows("products"):
        stats.products_by_source[p["source"]] += 1
        stats.products_for_review += bool(p.get("needs_review"))
    stats.failed_pages = sum(1 for page in store.rows("pages") if page.get("error"))
    stats.contacts_by_type.update(c["type"] for c in store.rows("contacts"))
    stats.changes_by_type.update(c["change_type"] for c in store.rows("changes"))
    stats.llm_calls = store.read("llm_calls")
    stats.counts = {
        "runs": len(store.read("runs")),
        "inputs": len(stats.inputs),
        "stores": len(stats.stores),
        "products": sum(stats.products_by_source.values()),
        "pages": sum(1 for _ in store.rows("pages")),
        "contacts": sum(stats.contacts_by_type.values()),
        "changes": sum(stats.changes_by_type.values()),
        "llm_calls": len(stats.llm_calls),
    }
    return stats


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


def _final_section(stats: RunStats) -> list[str]:
    """ADR 0010: how many stores made the final list, and why the others did not."""
    final = [s for s in stats.stores if not exclusion(s)]
    reasons: Counter[str] = Counter(exclusion(s) for s in stats.stores if exclusion(s))
    unclear = [s["domain"] for s in stats.stores if exclusion(s) == "not_judged"]
    lines = [
        "## Final list",
        "",
        "Multi-brand stores that sell knitwear (`export/final/`): "
        f"**{len(final)} stores, {sum(s.get('knit_kind_count', 0) for s in final)} "
        "knitwear products**.",
        "",
    ]
    if reasons:
        lines += [
            "| Not on the list because | Stores |",
            "|---|---:|",
            *[f"| {EXCLUSIONS[key]} | {n} |" for key, n in reasons.most_common()],
            "",
        ]
    if unclear:
        lines += ["Sell knitwear, store type unclear (check by hand):", "", *_bullets(unclear), ""]
    return lines


def _llm_section(stats: RunStats, run: RunRow) -> list[str]:
    """PRD LM-06, LM-09, LM-11: who used the LLM, what it cost, where the budget stopped."""
    calls = stats.llm_calls
    if run.llm_skipped:
        return ["## LLM", "", f"**Not used: {run.llm_skipped}.** Add the key to `.env`.", ""]
    if not calls:
        return []
    ok = [c for c in calls if c["status"] == "ok"]
    skipped = sorted({c["domain"] for c in calls if c["status"] == "skipped_budget"})
    failed = [c for c in calls if c["status"] == "error"]
    used = [s for s in stats.stores if "llm" in s.get("layers_tried", [])]
    with_products = [s for s in used if s["source_used"] == "llm"]
    judged = {c["domain"] for c in calls if c["prompt_version"].startswith("store-type")}
    dropped = sum(s.get("llm_products_dropped", 0) for s in used)
    cost = sum(c["cost_usd"] for c in calls)
    estimated = any(c["cost_estimated"] for c in calls)
    lines = [
        "## LLM",
        "",
        f"- Stores sent to the LLM for products (none from any other stage): {len(used)}",
        f"- Stores the LLM found products for: {len(with_products)}",
        f"- Stores whose type the LLM judged (vendors unclear, knitwear found): {len(judged)}",
        f"- Products dropped by the evidence rule: {dropped}",
        f"- Calls: {len(ok)} answered, {len(failed)} failed, {len(skipped)} skipped for budget",
        f"- Tokens: {sum(c['input_tokens'] for c in calls)} in, "
        f"{sum(c['output_tokens'] for c in calls)} out",
        f"- Cost: ${cost:.4f}"
        + (" (partly estimated: no list price for the model)" if estimated else ""),
        f"- Models: {', '.join(sorted({c['model'] for c in ok})) or 'none answered'}",
    ]
    if skipped:
        lines += [
            "",
            f"**Budget reached.** {len(skipped)} stores got no LLM call:",
            "",
            *[f"- {d}" for d in skipped],
        ]
    if failed:
        errors = Counter(c["error"] for c in failed)
        lines += ["", "Failed calls:", "", *[f"- {e} ({n})" for e, n in errors.most_common()]]
    return [*lines, ""]


def build_report(
    run: RunRow,
    stats: RunStats,
    exports: dict[str, list[Path]],
    root: Path,
    duration_seconds: float,
) -> str:
    inputs, stores = stats.inputs, stats.stores
    links_in, processed, skipped = reconcile(inputs)
    balanced = links_in == processed + skipped
    by_status: Counter[str] = Counter(s["status"] for s in stores)
    by_source = stats.products_by_source
    by_contact = stats.contacts_by_type

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
        *_final_section(stats),
        "## Data collected",
        "",
        f"- Products: {stats.counts['products']}"
        + (
            f" ({stats.products_for_review} flagged `needs_review`)"
            if stats.products_for_review
            else ""
        ),
        f"- Pages: {stats.counts['pages']}"
        + (
            f" ({stats.failed_pages} could not be read; see `pages.error`)"
            if stats.failed_pages
            else ""
        ),
        f"- Contacts: {stats.counts['contacts']}",
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
        *_llm_section(stats, run),
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
    stats: RunStats,
    exports: dict[str, list[Path]],
    root: Path,
    duration_seconds: float,
) -> dict[str, Any]:
    links_in, processed, skipped = reconcile(stats.inputs)
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
            **stats.counts,
        },
        "exports": {
            name: [str(p.relative_to(root)) for p in paths] for name, paths in exports.items()
        },
    }


def write_manifest(manifest: dict[str, Any], path: Path) -> Path:
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path

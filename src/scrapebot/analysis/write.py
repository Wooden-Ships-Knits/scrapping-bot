"""Write the analysis next to the run it reads: `<run>/analysis/` in every chosen format
(the Excel workbook has one sheet per table), plus a short README of what it rests on."""

from collections import Counter
from pathlib import Path

from ..outputs import Table, export
from ..tables import columns
from .build import Analysis
from .tables import ANALYSIS_TABLES

ANALYSIS_DIR = "analysis"
SEGMENT_ORDER = (
    "retail_partner", "b2b_partner", "competitor", "existing_customer",
    "not_a_fit", "not_relevant", "not_read", "unknown",
)  # fmt: skip


def write(analysis: Analysis, root: Path, writers: list[str]) -> dict[str, list[Path]]:
    dest = root / ANALYSIS_DIR
    rows = {
        "stores": sorted(
            analysis.stores,
            key=lambda r: (SEGMENT_ORDER.index(r.segment), -(r.score or 0), r.domain),
        ),
        "knit_products": analysis.knit,
        "competitors": sorted(analysis.competitors, key=lambda r: -r.knit_products),
        "brands": analysis.brands,
    }
    tables = [
        Table(
            name=name, columns=columns(model), rows=[r.model_dump(mode="json") for r in rows[name]]
        )
        for name, model in ANALYSIS_TABLES.items()
    ]
    written = export(tables, writers, dest)
    (dest / "README.md").write_text(summary(analysis), encoding="utf-8")
    return written


def summary(analysis: Analysis) -> str:
    segments = Counter(r.segment for r in analysis.stores)
    top = [r for r in analysis.stores if r.segment in ("retail_partner", "b2b_partner")]
    top.sort(key=lambda r: -(r.score or 0))
    lines = [
        "# Wholesale analysis",
        "",
        "One row per store in `stores`, its knitwear in `knit_products`, own-label knitwear",
        "in `competitors`, and who carries which brand in `brands`. Every segment and score",
        "has its reasons in the `reasons` column.",
        "",
        "## Segments",
        "",
        "| Segment | Stores |",
        "|---|---:|",
        *[f"| {s} | {segments[s]} |" for s in SEGMENT_ORDER if segments[s]],
        "",
        "## Best partner candidates",
        "",
        *[
            f"- {r.domain} ({r.segment}, score {r.score}): {r.knit_products} knitwear, "
            f"{r.city or 'location unknown'} {r.state}".rstrip()
            for r in top[:15]
        ],
        "",
        "## Inputs",
        "",
        *[f"- {n}" for n in analysis.notes],
        "",
    ]
    return "\n".join(lines)

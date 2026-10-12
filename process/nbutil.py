"""Shared helpers for the process notebooks: paths, loaders, name keys, chart style.

A first look at the data for the competitive and retailer analysis
(docs/product/prd-competitive-retailer-analysis.md). Exploratory: nothing in scrapebot
imports this, and the numbers it produces are not the final method.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import duckdb
import matplotlib as mpl
import pandas as pd

from scrapebot.analysis.inputs import compact, domain_core
from scrapebot.analysis.location import miles

__all__ = ["INK", "INK_2", "INK_3", "SERIES", "compact", "domain_core", "miles"]

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists())
RUNS = ROOT / "data" / "runs"
INPUTS = ROOT / "data" / "inputs"
LOCATORS = ROOT / "data" / "locators"

# Chart colours: a categorical order checked for colour-blind separation, and ink for text.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
INK, INK_2, INK_3, GRID, SURFACE = "#0b0b0b", "#52514e", "#7b7a75", "#dddbd5", "#ffffff"

PRODUCT_COLUMNS = {
    "domain": "VARCHAR", "title": "VARCHAR", "price_raw": "VARCHAR", "currency": "VARCHAR",
    "vendor": "VARCHAR", "product_type": "VARCHAR", "tags": "VARCHAR[]", "url": "VARCHAR",
    "source": "VARCHAR", "is_knitwear": "BOOLEAN", "knit_kind": "VARCHAR",
}  # fmt: skip


def run_id() -> str:
    """The run to analyse: SCRAPEBOT_RUN, else the newest run that `scrapebot analyze` has read."""
    if chosen := os.environ.get("SCRAPEBOT_RUN"):
        return chosen
    analysed = sorted(p.parent.name for p in RUNS.glob("*/analysis") if (p / "csv").is_dir())
    if not analysed:
        raise FileNotFoundError("no analysed run: run `scrapebot analyze <run>` first")
    return max(analysed, key=lambda r: (RUNS / r / "tables" / "products.jsonl").stat().st_size)


def run_dir() -> Path:
    return RUNS / run_id()


def process_dir() -> Path:
    """Everything the process writes for one run. Inside data/, so never committed."""
    return ROOT / "data" / "process" / run_id()


def out_dir() -> Path:
    """Where the notebooks keep their tables."""
    path = process_dir() / "tables"
    path.mkdir(parents=True, exist_ok=True)
    return path


def save(frame: pd.DataFrame, name: str) -> pd.DataFrame:
    frame.to_parquet(out_dir() / f"{name}.parquet", index=False)
    return frame


def load(name: str) -> pd.DataFrame:
    path = out_dir() / f"{name}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"{path.name} is missing: run the earlier notebooks first")
    return pd.read_parquet(path)


def load_products() -> pd.DataFrame:
    """Every product of the run, without the bulky `raw` and `description` columns."""
    source = run_dir() / "tables" / "products.jsonl"
    query = f"SELECT * FROM read_ndjson('{source}', columns={PRODUCT_COLUMNS!r})"
    return duckdb.connect().execute(query).df()


def load_stores() -> pd.DataFrame:
    """One row per store, with the segment, location and score the analysis stage added."""
    return pd.read_csv(run_dir() / "analysis" / "csv" / "stores.csv", low_memory=False)


def load_knit() -> pd.DataFrame:
    """Knitwear products with category, material and a numeric price."""
    return pd.read_csv(run_dir() / "analysis" / "csv" / "knit_products.csv", low_memory=False)


def load_stockists() -> pd.DataFrame:
    path = INPUTS / "stockists.json"
    if not path.exists():
        return pd.DataFrame(columns=["name", "city", "prov_state", "lat", "lng"])
    frame = pd.DataFrame(json.loads(path.read_text(encoding="utf-8")))
    frame["lat"] = pd.to_numeric(frame["lat"], errors="coerce")
    frame["lng"] = pd.to_numeric(frame["lng"], errors="coerce")
    return frame


def json_list(value: object) -> list[str]:
    """A column the CSV writer stored as JSON text, back as a list."""
    if not isinstance(value, str) or not value.startswith("["):
        return []
    try:
        return [str(v) for v in json.loads(value)]
    except json.JSONDecodeError:
        return []


def use_style() -> None:
    """Quiet charts: thin marks, recessive grid, text in ink rather than in the data colour."""
    mpl.rcParams.update(
        {
            "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
            "figure.dpi": 110, "font.size": 9, "text.color": INK,
            "axes.edgecolor": INK_3, "axes.labelcolor": INK_2, "axes.titlesize": 10.5,
            "axes.titleweight": "bold", "axes.titlelocation": "left", "axes.titlepad": 10,
            "axes.spines.top": False, "axes.spines.right": False, "axes.grid": False,
            "axes.prop_cycle": mpl.cycler(color=SERIES),
            "xtick.color": INK_3, "ytick.color": INK, "xtick.labelsize": 8, "ytick.labelsize": 8.5,
            "grid.color": GRID, "grid.linewidth": 0.8, "legend.frameon": False, "legend.fontsize": 8.5,
        }
    )  # fmt: skip

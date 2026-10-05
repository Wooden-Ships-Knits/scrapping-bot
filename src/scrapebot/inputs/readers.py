"""Read store links from pasted text or a file in any supported format (PRD IN-01 to IN-03).

Every reader yields `InputRecord`s: the link as supplied, plus the whole input row
as metadata. Tabular files keep every column untouched; the URL column is found
automatically unless one is named.
"""

import csv
import datetime as dt
import json
import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from functools import cache
from pathlib import Path
from typing import Any

SUPPORTED_SUFFIXES = (".txt", ".csv", ".tsv", ".xlsx", ".json", ".jsonl", ".parquet")

# Column names that hold the link, most specific first. Matched case-insensitively.
URL_COLUMN_NAMES = (
    "url", "website", "website_url", "site", "homepage", "link", "store_url", "domain", "web",
)  # fmt: skip
_TRAILING_PUNCTUATION = ".,;:!?)]}'\""
_URLISH_RE = re.compile(r"^(https?://)?[\w.-]+\.[a-z]{2,}(/\S*)?$", re.I)


class InputError(ValueError):
    """The input cannot be read. The message is shown to the operator as-is."""


@dataclass(frozen=True)
class InputRecord:
    value: str  # the link as supplied (may be empty or junk; resolve decides)
    meta: dict[str, Any] = field(default_factory=dict)


@cache
def _extractor():
    from urlextract import URLExtract

    return URLExtract()


def extract_urls(text: str) -> list[str]:
    """Every URL-like string in free text, in order, without trailing punctuation."""
    found = _extractor().find_urls(text or "", only_unique=False)
    return [u.rstrip(_TRAILING_PUNCTUATION) for u in found if isinstance(u, str)]


def read_text(text: str) -> list[InputRecord]:
    """Links pasted as free text, even mixed into sentences."""
    return [InputRecord(value=url) for url in extract_urls(text)]


def read_file(path: str | Path, url_column: str | None = None) -> list[InputRecord]:
    path = Path(path)
    if not path.exists():
        raise InputError(f"Input file not found: {path}")
    suffix = path.suffix.lower()
    if suffix == ".txt":
        return read_text(path.read_text(encoding="utf-8-sig"))
    if suffix in (".csv", ".tsv"):
        return records_from_rows(_read_delimited(path, suffix), url_column)
    if suffix == ".xlsx":
        return records_from_rows(_read_xlsx(path), url_column)
    if suffix == ".json":
        return _records_from_json(json.loads(path.read_text(encoding="utf-8-sig")), url_column)
    if suffix == ".jsonl":
        lines = path.read_text(encoding="utf-8-sig").splitlines()
        return _records_from_json([json.loads(line) for line in lines if line.strip()], url_column)
    if suffix == ".parquet":
        import pyarrow.parquet as pq

        return records_from_rows(pq.read_table(path).to_pylist(), url_column)
    raise InputError(
        f"Unsupported input format '{suffix}'. Use one of: {', '.join(SUPPORTED_SUFFIXES)}"
    )


def _read_delimited(path: Path, suffix: str) -> list[dict[str, Any]]:
    delimiter = "\t" if suffix == ".tsv" else ","
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh, delimiter=delimiter))


def _read_xlsx(path: Path) -> list[dict[str, Any]]:
    """The first sheet; its first non-empty row is the header."""
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb.worksheets[0]
        rows = [r for r in ws.iter_rows(values_only=True) if any(c is not None for c in r)]
    finally:
        wb.close()
    if not rows:
        return []
    header = [str(h).strip() if h is not None else f"column_{i + 1}" for i, h in enumerate(rows[0])]
    return [dict(zip(header, r, strict=False)) for r in rows[1:]]


def _records_from_json(data: Any, url_column: str | None) -> list[InputRecord]:
    """A list of links, a list of row objects, or an object wrapping one such list."""
    if isinstance(data, Mapping):
        lists = [v for v in data.values() if isinstance(v, list)]
        if len(lists) != 1:
            raise InputError("JSON input must be a list, or an object holding exactly one list")
        data = lists[0]
    if not isinstance(data, list):
        raise InputError("JSON input must be a list of links or of objects")
    if all(isinstance(item, str) for item in data):
        return [InputRecord(value=item) for item in data]
    rows = [item for item in data if isinstance(item, Mapping)]
    if len(rows) != len(data):
        raise InputError("JSON input mixes links and objects; use one or the other")
    return records_from_rows(rows, url_column)


def records_from_rows(
    rows: Iterable[Mapping[str, Any]], url_column: str | None = None
) -> list[InputRecord]:
    """One record per row. The whole row is kept as metadata."""
    rows = [{str(k): _jsonable(v) for k, v in row.items()} for row in rows]
    if not rows:
        return []
    column = _choose_url_column(rows, url_column)
    return [InputRecord(value=_link_in(row.get(column)), meta=row) for row in rows]


def _choose_url_column(rows: list[dict[str, Any]], requested: str | None) -> str:
    names = list(dict.fromkeys(k for row in rows for k in row))
    if requested and requested != "auto":
        if requested not in names:
            raise InputError(
                f"URL column '{requested}' not found. Columns: {', '.join(names) or 'none'}"
            )
        return requested
    by_lower = {n.lower().strip(): n for n in names}
    for candidate in URL_COLUMN_NAMES:
        if candidate in by_lower:
            return by_lower[candidate]
    # No telling header: take the column where most values look like links.
    best, best_share = "", 0.0
    for name in names:
        values = [str(r.get(name) or "").strip() for r in rows]
        filled = [v for v in values if v]
        share = sum(bool(_URLISH_RE.match(v)) for v in filled) / len(filled) if filled else 0.0
        if share > best_share:
            best, best_share = name, share
    if best_share < 0.5:
        raise InputError(
            "Could not find the column with links. Name it with url_column. "
            f"Columns: {', '.join(names)}"
        )
    return best


def _link_in(value: Any) -> str:
    """The link in a cell. A cell holding a sentence yields the first URL in it."""
    text = str(value or "").strip()
    if not text or not any(ch.isspace() for ch in text):
        return text
    urls = extract_urls(text)
    return urls[0] if urls else text


def _jsonable(value: Any) -> Any:
    """Spreadsheet and Parquet values as JSON-safe values, so metadata can be written anywhere."""
    if isinstance(value, float) and not math.isfinite(value):
        return None  # NaN and infinity are not valid JSON; spreadsheets use NaN for "empty"
    if value is None or isinstance(value, str | bool | int | float):
        return value
    if isinstance(value, dt.datetime | dt.date | dt.time):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    return str(value)

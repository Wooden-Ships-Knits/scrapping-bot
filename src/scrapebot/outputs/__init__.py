"""Output writers (PRD OUT-01 to OUT-08). A new format is one new writer here.

Writers read the canonical tables of a run and never change acquisition.
"""

import logging
from pathlib import Path

from .base import Table, Writer
from .databases import DuckdbWriter, SqliteWriter
from .excel import ExcelWriter
from .files import CsvWriter, JsonlWriter, JsonWriter, TsvWriter
from .parquet import ParquetWriter

log = logging.getLogger(__name__)

_WRITERS: dict[str, Writer] = {
    w.name: w
    for w in (
        JsonWriter(),
        JsonlWriter(),
        CsvWriter(),
        TsvWriter(),
        ExcelWriter(),
        ParquetWriter(),
        SqliteWriter(),
        DuckdbWriter(),
    )
}

__all__ = ["Table", "Writer", "available_writers", "export", "get_writer"]


def available_writers() -> tuple[str, ...]:
    return tuple(_WRITERS)


def get_writer(name: str) -> Writer:
    try:
        return _WRITERS[name]
    except KeyError:
        raise ValueError(f"unknown writer '{name}'; available: {', '.join(_WRITERS)}") from None


def export(tables: list[Table], names: list[str], dest: Path) -> dict[str, list[Path]]:
    """Write every chosen format. One failing format does not stop the others."""
    written: dict[str, list[Path]] = {}
    for name in names:
        try:
            written[name] = get_writer(name).write(tables, dest)
        except Exception:
            log.exception("Writer %s failed; the canonical tables are unaffected", name)
            written[name] = []
    return written

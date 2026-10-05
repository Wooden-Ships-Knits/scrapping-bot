"""The canonical copy of a run: one JSONL file per table (ADR 0006).

Rows are appended store by store and flushed, so a crash loses at most the
store in progress. Every export format is generated from these files, read back
as streams so no table has to fit in memory.
"""

import json
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from .outputs.base import Table
from .tables import TABLES, Row, columns


class JsonlRows:
    """A table's rows, read from its JSONL file each time it is iterated."""

    def __init__(self, path: Path):
        self.path = path

    def __iter__(self) -> Iterator[dict[str, Any]]:
        with self.path.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    yield json.loads(line)


class RunStore:
    def __init__(self, root: Path):
        self.root = root
        self.tables_dir = root / "tables"
        self.tables_dir.mkdir(parents=True, exist_ok=True)
        for name in TABLES:
            self.path(name).touch()

    def path(self, table: str) -> Path:
        return self.tables_dir / f"{table}.jsonl"

    def append(self, rows: Iterable[Row]) -> None:
        lines: dict[str, list[str]] = {}
        for row in rows:
            lines.setdefault(row.table, []).append(row.model_dump_json())
        for table, batch in lines.items():
            with self.path(table).open("a", encoding="utf-8") as fh:
                fh.write("\n".join(batch) + "\n")

    def rows(self, table: str) -> JsonlRows:
        return JsonlRows(self.path(table))

    def read(self, table: str) -> list[dict[str, Any]]:
        return list(self.rows(table))

    def load_tables(self) -> list[Table]:
        """Every table, streamed from disk."""
        return [
            Table(name=name, columns=columns(model), rows=self.rows(name))
            for name, model in TABLES.items()
        ]

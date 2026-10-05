"""Plain file formats: JSON, JSONL, CSV and TSV. One file per table."""

import csv
import json
from pathlib import Path
from typing import Any

from .base import Table, flat_rows


class JsonWriter:
    name = "json"

    def write(self, tables: list[Table], dest: Path) -> list[Path]:
        out = dest / "json"
        out.mkdir(parents=True, exist_ok=True)
        paths = []
        for table in tables:
            path = out / f"{table.name}.json"
            path.write_text(json.dumps(table.rows, ensure_ascii=False, indent=1), encoding="utf-8")
            paths.append(path)
        return paths


class JsonlWriter:
    name = "jsonl"

    def write(self, tables: list[Table], dest: Path) -> list[Path]:
        out = dest / "jsonl"
        out.mkdir(parents=True, exist_ok=True)
        paths = []
        for table in tables:
            path = out / f"{table.name}.jsonl"
            with path.open("w", encoding="utf-8") as fh:
                for row in table.rows:
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            paths.append(path)
        return paths


def _cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


class _DelimitedWriter:
    name: str
    delimiter: str

    def write(self, tables: list[Table], dest: Path) -> list[Path]:
        out = dest / self.name
        out.mkdir(parents=True, exist_ok=True)
        paths = []
        for table in tables:
            path = out / f"{table.name}.{self.name}"
            with path.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh, delimiter=self.delimiter)
                writer.writerow([c.name for c in table.columns])
                writer.writerows([[_cell(v) for v in row] for row in flat_rows(table)])
            paths.append(path)
        return paths


class CsvWriter(_DelimitedWriter):
    name = "csv"
    delimiter = ","


class TsvWriter(_DelimitedWriter):
    name = "tsv"
    delimiter = "\t"

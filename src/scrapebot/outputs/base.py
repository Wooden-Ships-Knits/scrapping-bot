"""What every writer receives, and the conversions they share."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from ..tables import Column

if TYPE_CHECKING:
    import pyarrow as pa


@dataclass(frozen=True)
class Table:
    name: str
    columns: list[Column]
    rows: list[dict[str, Any]]


class Writer(Protocol):
    """Turns the run's tables into one output format under `dest`."""

    name: str

    def write(self, tables: list[Table], dest: Path) -> list[Path]: ...


def flat_value(value: Any, column: Column) -> Any:
    """A value for a flat format: nested JSON fields become JSON text (ADR 0006)."""
    if column.kind == "json":
        return None if value is None else json.dumps(value, ensure_ascii=False)
    return value


def flat_rows(table: Table) -> list[list[Any]]:
    return [[flat_value(row.get(c.name), c) for c in table.columns] for row in table.rows]


def to_arrow(table: Table) -> "pa.Table":
    """An Arrow table with a fixed schema, so empty tables keep their column types."""
    import pyarrow as pa

    types = {
        "str": pa.string(),
        "int": pa.int64(),
        "float": pa.float64(),
        "bool": pa.bool_(),
        "json": pa.string(),
    }
    schema = pa.schema([pa.field(c.name, types[c.kind]) for c in table.columns])
    data = {c.name: [flat_value(row.get(c.name), c) for row in table.rows] for c in table.columns}
    return pa.Table.from_pydict(data, schema=schema)

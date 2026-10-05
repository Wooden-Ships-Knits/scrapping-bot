"""What every writer receives, and the conversions they share.

Rows are streamed: a table's `rows` is any re-iterable source (a list in tests,
the canonical JSONL file in a run), and writers never hold a whole table in
memory, so a 1,000-store run with long pages and full feed objects still exports.
"""

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from itertools import islice
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from ..tables import Column

if TYPE_CHECKING:
    import pyarrow as pa

BATCH_ROWS = 5000


@dataclass(frozen=True)
class Table:
    name: str
    columns: list[Column]
    rows: Iterable[dict[str, Any]]  # iterated once per writer


class Writer(Protocol):
    """Turns the run's tables into one output format under `dest`."""

    name: str

    def write(self, tables: list[Table], dest: Path) -> list[Path]: ...


def flat_value(value: Any, column: Column) -> Any:
    """A value for a flat format: nested JSON fields become JSON text (ADR 0006)."""
    if column.kind == "json":
        return None if value is None else json.dumps(value, ensure_ascii=False)
    return value


def flat_rows(table: Table) -> Iterator[list[Any]]:
    for row in table.rows:
        yield [flat_value(row.get(c.name), c) for c in table.columns]


def batches(rows: Iterable[Any], size: int = BATCH_ROWS) -> Iterator[list[Any]]:
    it = iter(rows)
    while batch := list(islice(it, size)):
        yield batch


def arrow_schema(table: Table) -> "pa.Schema":
    import pyarrow as pa

    types = {
        "str": pa.string(),
        "int": pa.int64(),
        "float": pa.float64(),
        "bool": pa.bool_(),
        "json": pa.string(),
    }
    return pa.schema([pa.field(c.name, types[c.kind]) for c in table.columns])


def arrow_batches(table: Table) -> Iterator["pa.Table"]:
    """The table as Arrow tables of at most BATCH_ROWS rows, with a fixed schema so
    empty tables keep their column types."""
    import pyarrow as pa

    schema = arrow_schema(table)
    for batch in batches(table.rows):
        data = {c.name: [flat_value(row.get(c.name), c) for row in batch] for c in table.columns}
        yield pa.Table.from_pydict(data, schema=schema)


def to_arrow(table: Table) -> "pa.Table":
    """The whole table as one Arrow table. For small tables and tests."""
    import pyarrow as pa

    parts = list(arrow_batches(table))
    return pa.concat_tables(parts) if parts else arrow_schema(table).empty_table()

"""Local databases: SQLite and DuckDB, queryable without an import step.

Each run gets its own database file inside its run folder, so earlier runs are
never touched. Regenerating a run's export rebuilds that run's file.
"""

import sqlite3
from pathlib import Path

from .base import Table, flat_rows, to_arrow

_SQLITE_TYPES = {
    "str": "TEXT",
    "int": "INTEGER",
    "float": "REAL",
    "bool": "INTEGER",
    "json": "TEXT",
}


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


class SqliteWriter:
    name = "sqlite"

    def write(self, tables: list[Table], dest: Path) -> list[Path]:
        dest.mkdir(parents=True, exist_ok=True)
        path = dest / "tables.sqlite"
        path.unlink(missing_ok=True)
        con = sqlite3.connect(path)
        try:
            for table in tables:
                cols = ", ".join(f"{_quote(c.name)} {_SQLITE_TYPES[c.kind]}" for c in table.columns)
                con.execute(f"CREATE TABLE {_quote(table.name)} ({cols})")
                marks = ", ".join("?" for _ in table.columns)
                con.executemany(
                    f"INSERT INTO {_quote(table.name)} VALUES ({marks})", flat_rows(table)
                )
                if any(c.name == "domain" for c in table.columns):
                    con.execute(
                        f"CREATE INDEX {_quote(f'idx_{table.name}_domain')} "
                        f"ON {_quote(table.name)} (domain)"
                    )
            con.commit()
        finally:
            con.close()
        return [path]


class DuckdbWriter:
    name = "duckdb"

    def write(self, tables: list[Table], dest: Path) -> list[Path]:
        import duckdb

        dest.mkdir(parents=True, exist_ok=True)
        path = dest / "tables.duckdb"
        path.unlink(missing_ok=True)
        con = duckdb.connect(str(path))
        try:
            for table in tables:
                con.register("incoming", to_arrow(table))
                con.execute(f"CREATE TABLE {_quote(table.name)} AS SELECT * FROM incoming")
                con.unregister("incoming")
        finally:
            con.close()
        return [path]

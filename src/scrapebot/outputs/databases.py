"""Local databases: SQLite and DuckDB, queryable without an import step.

Each run gets its own database file inside its run folder, so earlier runs are
never touched. Regenerating a run's export rebuilds that run's file.
"""

import sqlite3
from pathlib import Path

from .base import Table, arrow_batches, arrow_schema, batches, flat_rows

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
                insert = f"INSERT INTO {_quote(table.name)} VALUES ({marks})"
                for batch in batches(flat_rows(table)):
                    con.executemany(insert, batch)
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
                con.register("incoming", arrow_schema(table).empty_table())
                con.execute(f"CREATE TABLE {_quote(table.name)} AS SELECT * FROM incoming")
                con.unregister("incoming")
                for batch in arrow_batches(table):
                    con.register("incoming", batch)
                    con.execute(f"INSERT INTO {_quote(table.name)} SELECT * FROM incoming")
                    con.unregister("incoming")
        finally:
            con.close()
        return [path]

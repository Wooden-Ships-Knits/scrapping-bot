"""Parquet: one file per table, typed columns. Best for analysis at scale."""

from pathlib import Path

from .base import Table, to_arrow


class ParquetWriter:
    name = "parquet"

    def write(self, tables: list[Table], dest: Path) -> list[Path]:
        import pyarrow.parquet as pq

        out = dest / "parquet"
        out.mkdir(parents=True, exist_ok=True)
        paths = []
        for table in tables:
            path = out / f"{table.name}.parquet"
            pq.write_table(to_arrow(table), path)
            paths.append(path)
        return paths

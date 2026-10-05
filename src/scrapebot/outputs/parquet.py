"""Parquet: one file per table, typed columns. Best for analysis at scale."""

from pathlib import Path

from .base import Table, arrow_batches, arrow_schema


class ParquetWriter:
    name = "parquet"

    def write(self, tables: list[Table], dest: Path) -> list[Path]:
        import pyarrow.parquet as pq

        out = dest / "parquet"
        out.mkdir(parents=True, exist_ok=True)
        paths = []
        for table in tables:
            path = out / f"{table.name}.parquet"
            with pq.ParquetWriter(path, arrow_schema(table)) as writer:
                for batch in arrow_batches(table):
                    writer.write_table(batch)
            paths.append(path)
        return paths

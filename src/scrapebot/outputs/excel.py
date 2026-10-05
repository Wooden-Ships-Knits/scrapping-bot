"""Excel: one workbook, one sheet per table."""

import logging
from pathlib import Path
from typing import Any

from .base import Table, flat_rows

log = logging.getLogger(__name__)

MAX_DATA_ROWS = 1_048_575  # Excel's 1,048,576 rows per sheet, minus the header
MAX_CELL_CHARS = 32_767
TRUNCATED_MARKER = " …[truncated: Excel cell limit]"


class ExcelWriter:
    name = "xlsx"
    max_rows = MAX_DATA_ROWS

    def write(self, tables: list[Table], dest: Path) -> list[Path]:
        from openpyxl import Workbook
        from openpyxl.cell import WriteOnlyCell
        from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
        from openpyxl.styles import Font

        dest.mkdir(parents=True, exist_ok=True)
        path = dest / "tables.xlsx"
        wb = Workbook(write_only=True)
        truncated = 0

        def cell(ws: Any, value: Any) -> Any:
            nonlocal truncated
            if isinstance(value, str):
                value = ILLEGAL_CHARACTERS_RE.sub("", value)
                if len(value) > MAX_CELL_CHARS:
                    truncated += 1
                    value = value[: MAX_CELL_CHARS - len(TRUNCATED_MARKER)] + TRUNCATED_MARKER
            c = WriteOnlyCell(ws, value=value)
            if isinstance(value, str) and value.startswith("="):
                c.data_type = "s"  # store page text as text, never as a formula
            return c

        bold = Font(bold=True)

        def new_sheet(table: Table, n: int) -> Any:
            ws = wb.create_sheet(table.name if n == 1 else f"{table.name}_{n}")
            ws.freeze_panes = "A2"
            header = []
            for c in table.columns:
                h = WriteOnlyCell(ws, value=c.name)
                h.font = bold
                header.append(h)
            ws.append(header)
            return ws

        for table in tables:
            sheets, written = 1, 0
            ws = new_sheet(table, sheets)
            for row in flat_rows(table):
                if written == self.max_rows:  # Excel's row limit: continue on a new sheet
                    sheets, written = sheets + 1, 0
                    ws = new_sheet(table, sheets)
                ws.append([cell(ws, v) for v in row])
                written += 1
            if sheets > 1:
                log.warning("Excel: table %s split across %d sheets", table.name, sheets)

        wb.save(path)
        if truncated:
            log.warning(
                "Excel: %d cells over %d characters were truncated; other formats keep them whole",
                truncated,
                MAX_CELL_CHARS,
            )
        return [path]

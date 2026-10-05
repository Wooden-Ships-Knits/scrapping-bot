# data/

Local working folder. Everything here except this file is gitignored.

| Path | What |
|---|---|
| `data/*.csv`, `*.xlsx`, ... | Input lists you supply. They hold prospect records: never commit them |
| `data/.cache/` | HTTP cache shared by all runs. Delete it to force fresh fetches |
| `data/runs/<run_id>/` | One folder per run: tables, exports, report and manifest |

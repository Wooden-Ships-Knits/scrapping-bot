# Engineering standards

How code in this repo is written, tested and shipped. The [PRD](../product/prd.md)
says what to build; this page says how.

## 1. Tooling

| Concern | Tool | Rule |
|---|---|---|
| Python | 3.11+ | One version, pinned in `pyproject.toml` |
| Environment and lock | `uv` | `pyproject.toml` + `uv.lock` replace `requirements.txt` (migrate in M0) |
| Lint and format | `ruff` | `ruff check` and `ruff format` pass before every commit |
| Types | `pyright` | Basic mode for existing modules, strict for new ones |
| Tests | `pytest` | Offline only; see section 5 |
| Hooks | `pre-commit` | Runs ruff, pyright, the web type check and the fast tests |
| CI | GitHub Actions | Lint, types, tests, API-type drift, web build and e2e on every pull request |
| Web app | TypeScript 6, React, Vite, `pnpm` | `tsc --noEmit` strict; Vitest + Testing Library; Playwright e2e, offline |

Optional features are extras, so a basic install stays small:
`scrapebot[browser]`, `scrapebot[llm]`, `scrapebot[ui]`, `scrapebot[db]`.

## 2. Project layout

Modules marked *(planned)* arrive with the milestone that needs them. Moves happen
one stage per pull request, with tests passing at every step.

```
src/scrapebot/
  cli.py               # `scrapebot run`: flags -> RunConfig -> pipeline
  config.py            # RunConfig (Pydantic + YAML)
  pipeline.py          # orchestration of one run, stage order
  models.py            # in-memory records between stages: Product, Page, Acquired, ...
  tables.py            # the seven output tables; writers derive columns from them
  store.py             # canonical JSONL tables for a run
  summary.py           # v1-layout summary.csv (until the analysis phase)
  report.py            # run report, reconciliation, manifest
  fetch.py             # Fetcher protocol + HttpFetcher: robots, cache, delay (fetch/ in M2)
  inputs/              # readers (text, txt, csv, tsv, xlsx, json, jsonl, parquet) + resolve
  acquire/             # stage order for one store; feeds.py, discovery.py
    structured.py      # extruct, app state (planned, M2)
    render.py          # Camoufox (gated, M4)
  extract/             # pure functions: text, prices, products, profile, pages, contacts, signals
  llm/                 # LiteLLM + instructor gateway, schemas, prompts (planned, M3)
  api/                 # FastAPI service for the web app; imports the pipeline, never the reverse
  outputs/             # writers: json, jsonl, csv, tsv, xlsx, parquet, sqlite, duckdb
  region.py            # pycountry, babel, phonenumbers (planned, M5)
  changes.py           # run-to-run comparison (planned, M5)
web/                   # React + TypeScript + Vite; src/api/schema.d.ts generated from the API
  e2e/                 # Playwright suite against tests/e2e_server.py
tests/
  fakes.py             # FakeFetcher and other doubles
  fixtures/            # recorded responses from real sites; never edited
  contract/            # one suite per adapter type (writers today)
  api/                 # the HTTP API end to end with a FakeFetcher
  e2e_server.py        # real API + built web app over a fake network, for Playwright
  unit/
```

## 3. Design rules

1. **Ports and adapters.** Each stage depends on a `Protocol` (`Fetcher`, `Renderer`,
   `FeedAdapter`, `LLMExtractor`, `InputReader`, `OutputWriter`). Implementations
   register by name and are picked from config.
2. **Pydantic at every boundary.** Stage inputs and outputs are models, not dicts.
   Raw source objects travel in a typed `raw: dict` field.
3. **Stages are plain functions or small classes with injected dependencies.** No
   module-level clients, no hidden globals. Tests inject fakes.
4. **Network conditions never raise past the fetch layer.** They become a status
   (`blocked`, `error`, ...) on the record.
5. **Append-only, idempotent writes.** Re-running a finished store produces the same
   rows; writers never delete earlier runs.
6. **The API and UI import the pipeline, never the reverse.**
7. **Raw means raw.** Acquisition does not clean, convert or drop values, except the
   LLM evidence rule.

## 4. Configuration and secrets

- Run settings live in YAML, validated by `pydantic-settings`. Environment variables
  override files.
- API keys and DSNs are `SecretStr`, read from the UI session or `.env`. They never
  appear in config files, logs, outputs, reports, cache or exceptions.
- `.env` and `data/` are in `.gitignore`. `.env.example` lists variable names with
  empty values.
- A redaction filter on the logger masks anything that looks like a key, as a second
  line of defence.

## 5. Testing

- **No test touches the network.** HTTP is replayed from recorded cassettes
  (`pytest-recording`); LLM calls are replayed from recorded responses.
- **Fixtures come from real sites.** Each fixture file name carries the site and the
  date it was recorded.
- **Contract tests per adapter type.** Every writer round-trips the same tables. Every
  LLM provider parses its recorded response into the same schema. Every input reader
  yields the same URLs for the same list.
- **Every status has a test**: `ok`, `no_products`, `blocked`, `error`, and each skip
  reason.
- A bug fix starts with a failing test that reproduces it.

## 6. Verifying real runs

Passing tests are not enough. Before a stage counts as done:

1. Run it in **LIMIT mode** on 2 real stores and read the actual output files.
2. Spot-check edge rows: empty prices, duplicate products, non-ASCII titles.
3. Check the reconciliation line: links in = processed + skipped.
4. Only then run the full list.

## 7. Logging and observability

- `structlog`, JSON output, with `run_id` and `domain` bound to every line.
- Log events and counts, not page text or product payloads.
- Each run writes a manifest: config (without secrets), package versions, durations,
  token use and cost.

## 8. Dependencies

- Prefer small, single-purpose libraries. A new dependency needs a one-line reason in
  the pull request.
- Versions are locked. Fast-moving packages (LiteLLM, Camoufox) are upgraded on purpose,
  with the contract tests run against the new version.

## 9. Git and review

- One branch per change. No direct commits to `main`.
- Conventional commit messages (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`).
- A pull request states what changed, how it was verified (test names, LIMIT run
  output), and any follow-up.
- Never commit input lists, run outputs or `.env`.

## 10. Documentation and writing

- A decision that is hard to reverse gets an ADR in [decisions/](../decisions/).
- A change in behaviour updates the PRD or the architecture page in the same pull
  request.
- Write plainly. Lead with the point, use numbers with their source, cut filler and
  hype. Every claim in a document should be checkable against code, data or a test.

## 11. Definition of done

A change is done when:

- [ ] lint, types and tests pass in CI;
- [ ] a LIMIT run on real stores was checked by reading the output;
- [ ] docs and, if needed, an ADR are updated;
- [ ] for a release: the five handover documents exist in `docs/operations/`
  ([PRD section 14](../product/prd.md#14-serah-terima)).

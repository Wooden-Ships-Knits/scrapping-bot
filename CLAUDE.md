# CLAUDE.md

Guidance for Claude Code (and any contributor) working in this repo.

## Read first

- What and why: `docs/product/prd.md` (Indonesian)
- How it works: `docs/architecture/overview.md`
- How code is written: `docs/engineering/standards.md`
- What is next: `docs/planning/roadmap.md`

## Commands

```bash
make install   # Python + web deps, Playwright browser, pre-commit hooks
make check     # ruff, pyright, pytest, web typecheck + unit tests: must pass before a commit
make e2e       # Playwright, offline, desktop + mobile
make fmt       # format + safe lint fixes
make serve     # web interface on http://127.0.0.1:8765
uv run scrapebot discover -c discover.example.yaml   # find stores (paid APIs; ADR 0008)
uv run scrapebot run <input> --limit 2   # the bot from the command line
```

## Rules that are easy to break

- Tests never touch the network. Use `tests/fakes.py` or recorded fixtures in
  `tests/fixtures/`. Fixtures are byte-exact copies of real responses: do not edit them.
- No `Accept-Language` header on HTTP requests: it makes Shopify localise prices.
- No anti-bot bypass, no login, respect `robots.txt` (ADR 0002).
- Never store or export HTML; store page text (ADR 0006).
- Discovery never opens store websites or Instagram/Facebook profiles; every paid
  source keeps its request cap and disk cache (ADR 0008).
- Raw means raw: acquisition does not clean or convert values.
- The pipeline never imports the API or UI.
- After changing a model in `api/schemas.py`, run `make api-types` and commit
  `web/src/api/schema.d.ts`; CI fails on drift.
- UI text is Indonesian; every API code gets a label in `web/src/labels.ts`.
- Never commit anything in `data/` or `.env`.
- One branch per change, conventional commits, docs updated in the same change.

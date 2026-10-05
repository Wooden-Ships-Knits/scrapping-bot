# CLAUDE.md

Guidance for Claude Code (and any contributor) working in this repo.

## Read first

- What and why: `docs/product/prd.md` (Indonesian)
- How it works: `docs/architecture/overview.md`
- How code is written: `docs/engineering/standards.md`
- What is next: `docs/planning/roadmap.md`

## Commands

```bash
make install   # uv sync + pre-commit hooks
make check     # ruff, pyright, pytest: must pass before any commit
make fmt       # format + safe lint fixes
uv run scrapebot <input>   # run the bot
```

## Rules that are easy to break

- Tests never touch the network. Use `tests/fakes.py` or recorded fixtures in
  `tests/fixtures/`. Fixtures are byte-exact copies of real responses: do not edit them.
- No `Accept-Language` header on HTTP requests: it makes Shopify localise prices.
- No anti-bot bypass, no login, respect `robots.txt` (ADR 0002).
- Never store or export HTML; store page text (ADR 0006).
- Raw means raw: acquisition does not clean or convert values.
- The pipeline never imports the API or UI.
- Never commit anything in `data/` or `.env`.
- One branch per change, conventional commits, docs updated in the same change.

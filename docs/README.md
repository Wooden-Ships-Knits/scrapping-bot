# Documentation

Start with the PRD for *what* and *why*, then the architecture for *how*.

```
docs/
├── product/        what we build and why (PRD)
├── architecture/   how the system works
├── decisions/      why we chose X over Y (ADRs)
├── engineering/    how code is written, tested and shipped
├── planning/       milestones, gates, known issues
├── operations/     runbook and handover docs (created at release, M6)
├── exports/        PDF snapshots for reading offline
└── archive/        superseded documents, kept for history
```

## Current documents

| Document | Language | What it covers |
|---|---|---|
| [PRD](product/prd.md) | English | Knitwear stores found or bulk links in, raw data out in any format; users, scope, requirements, data model, milestones, metrics, handover |
| [Architecture](architecture/overview.md) | English | The pipeline stage by stage, marked Built, Planned or Gated; entry points, config, writers |
| [Engineering standards](engineering/standards.md) | English | Tooling, code layout, design rules, testing, secrets, definition of done |
| [Roadmap](planning/roadmap.md) | English | v1 findings, known issues, milestones M0–M6 with gates |
| [System flow](system-flow.md) | English | A learning guide: how a list of links becomes tables, stage by stage, with the tools each stage uses |

## Decisions

| # | Decision | Status |
|---|---|---|
| [0001](decisions/0001-layered-acquisition-llm-last.md) | Layered acquisition, LLM last: ScrapeGraph's workflow shape, without its API | Accepted |
| [0002](decisions/0002-camoufox-for-rendering-only.md) | Camoufox for rendering only; no anti-bot bypass | Accepted |
| [0003](decisions/0003-plain-python-orchestration-file-output.md) | Plain Python orchestration; no LangGraph; databases only as writers | Accepted |
| [0004](decisions/0004-llm-gateway-litellm-instructor.md) | Any LLM provider through LiteLLM, structured output through instructor | Accepted |
| [0005](decisions/0005-streamlit-bulk-interface.md) | Local Streamlit app for bulk runs, same pipeline as the CLI | Superseded by 0007 |
| [0006](decisions/0006-tidy-tables-multiformat-writers.md) | Seven tidy tables, many output writers, no HTML | Accepted |
| [0007](decisions/0007-typescript-web-ui-local-api.md) | TypeScript (React + Vite) web interface over a local FastAPI service | Accepted |
| [0008](decisions/0008-store-discovery-paid-search.md) | Store discovery with paid search APIs before a run; knitwear flag, no product dropped | Accepted |

## Exports and archive

- [exports/](exports/README.md): PDF snapshots of the v2 design and technical workflow
  (Indonesian, 2026-10-05). The Markdown documents above are the source of truth.
- [archive/](archive/README.md): earlier designs, the v1 build plan and PRD 1.0.

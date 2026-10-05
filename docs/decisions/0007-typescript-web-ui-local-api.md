# 0007 — TypeScript web interface over a local API

**Date:** 2026-10-05
**Status:** Accepted
**Supersedes:** [ADR 0005](0005-streamlit-bulk-interface.md)

## Context

ADR 0005 chose Streamlit for the bulk interface. The operator has decided the
interface should be written in **TypeScript** instead. The requirements for the screen
do not change: paste or upload many links, choose region, language, LLM provider,
API key and output formats, run test mode, follow progress per store, download
results ([PRD section 6](../product/prd.md#6-antarmuka-pengguna)).

The scraping pipeline stays in Python. v1 is built and tested there, and the
libraries it depends on (`extruct`, `trafilatura`, LiteLLM, instructor, Camoufox,
`pyarrow`) have no equal in the TypeScript ecosystem.

## Decision

- **Frontend:** React + TypeScript, built with Vite, in `web/`. It is a static
  single-page app; no server-side rendering.
- **Backend:** a thin **FastAPI** service in `src/scrapebot/api/`, run locally. It
  builds the same `RunConfig` the CLI reads, starts the same pipeline in a background
  worker, and serves progress, reports and output files from the run directory.
- **Progress** is read from the run directory and streamed to the browser with
  Server-Sent Events. Closing the browser does not lose a run, and a stopped run can
  resume.
- **Shared types:** the frontend's API types are generated from FastAPI's OpenAPI
  schema (`openapi-typescript`). Pydantic models stay the single source of truth.
- **API keys** are sent with the run request and held in the worker's memory for that
  run only. They are never written to disk, logs, config files or output.
- The service binds to `127.0.0.1` only. In production mode it serves the built
  frontend itself, so the operator starts one command and opens one URL.
- Test mode (LIMIT, first 2 links) is on by default.

## Rejected alternatives

- **Streamlit (ADR 0005).** Python-only UI; replaced by operator preference for
  TypeScript.
- **Next.js calling the Python CLI as a subprocess.** Process control, progress
  parsing and file serving would live in Node, duplicating what the Python side
  already knows. Types could not be generated from the Pydantic models.
- **Rewriting the pipeline in TypeScript.** Throws away a working, tested v1 and the
  Python extraction libraries for no gain in output quality.

## Consequences

- Two toolchains: `uv` for Python, `pnpm` for `web/`. CI runs both.
- The pipeline must not import the API or know about HTTP. Everything the web
  interface does, the CLI can do.
- The API is single-user and has no login. Shared access with accounts would be a new
  decision.

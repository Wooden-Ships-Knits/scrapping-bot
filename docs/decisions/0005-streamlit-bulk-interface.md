# 0005 — Streamlit for the bulk interface

**Date:** 2026-10-05
**Status:** Superseded by [ADR 0007](0007-typescript-web-ui-local-api.md)

## Context

The operator wants an interface like ScrapeGraph's playground, but one that accepts
many links at once in any format, with settings for region, language, LLM provider,
API key and output formats. It is an internal tool for one to a few people. Runs take
minutes to an hour.

## Decision

- A **Streamlit** app, run locally, is the interface. It is a thin layer: it builds the
  same run configuration the CLI reads, starts the same pipeline, and shows progress
  and downloads.
- The pipeline runs in a background worker and writes progress to the run directory.
  The app reads that progress. Closing the browser does not lose a run, and a stopped
  run can resume.
- API keys live only in `st.session_state` for the session. The app never writes them
  to disk.
- Test mode (LIMIT, first 2 links) is on by default.

## Rejected alternatives

- **FastAPI + a JavaScript frontend.** Right for a multi-user product with accounts.
  For an internal tool it means two codebases to maintain.
- **Gradio.** Also viable. Streamlit fits better for tables, sidebar settings and
  file downloads, which are most of this screen.
- **n8n form trigger.** The scraping engine stays in Python either way, so n8n would
  only add a hop. n8n can still call the CLI later for scheduled runs.
- **CLI only.** Fine for automation, but the operator should not need a terminal.

## Consequences

- The pipeline must not import Streamlit. Everything the app does, the CLI can do.
- The app is single-user and local. If the team needs shared access with logins, add a
  FastAPI service in front of the same pipeline and record that as a new decision.

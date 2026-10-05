# 0003 — Plain Python orchestration; files, not a database

**Date:** 2026-10-05
**Status:** Accepted

## Context

A proposed pipeline modelled on ScrapeGraph's workflow put a **LangGraph
orchestrator** at the start and **Postgres** with analytics, monitoring and an
API at the end.

The bot processes one prospect list per run, about 67 domains. Its output is
read by a person deciding which stores to contact. The route through the
pipeline is fixed by rules (feed found or not, content OK or not, products found
or not). No step needs a model to choose what happens next.

## Decision

- **Orchestration is a plain Python loop** over stores, calling one function per
  stage, as `cli.py` and `sources.py` do today. Stage results are recorded in a
  trail on each store (`layers_tried`).
- **Output stays as files:** the enriched CSV, one raw JSON per domain, and the
  run report.
- The record built for each CSV row stays the single source of output. A future
  database becomes another writer of the same records, with no change to the
  pipeline.

## Rejected alternatives

- **LangGraph.** It is useful when an LLM decides the next step or the flow
  loops. Here the routing is fixed `if` statements, and the file cache already
  gives cheap resume. It depends only on `langchain-core`, not all of LangChain,
  so the cost is small, but nothing here uses what it adds. If each stage is a
  plain function, wrapping them as LangGraph nodes later is cheap.
- **Postgres now.** It adds a server to run, migrations and credentials, for
  data that fits in one CSV per run. Nothing yet needs history across runs.

## Consequences

- The bot runs with no services.
- **Revisit when** runs become scheduled or recurring and we need history across
  runs (price changes, new stores, status changes). Start with SQLite as a
  second output writer, and move to Postgres only if several people or services
  must read it at the same time.
- **Revisit LangGraph** only if a stage ever needs an LLM to choose the next step.

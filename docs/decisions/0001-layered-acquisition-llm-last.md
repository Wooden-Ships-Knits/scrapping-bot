# 0001 — Layered acquisition, LLM last

**Date:** 2026-10-05
**Status:** Accepted

## Context

v1 reads non-Shopify stores only through JSON-LD. Sites without it return zero
products. ScrapeGraphAI and its workflow (discover pages, fetch, render if
needed, extract against a schema, validate) were evaluated as a way to read any
site without writing selectors for each one. We do not want to pay for the
ScrapeGraph API.

## Decision

Adopt the **shape** of the ScrapeGraph workflow, built from plain Python and
open libraries:

1. Platform feeds. Products come straight from the feed; product pages are not
   fetched one by one.
2. Product discovery (sitemaps, links) into a capped, prioritised URL queue.
3. Per page: HTTP fetch, then a content check. Only empty or JavaScript-shell
   pages are rendered with a browser (see [0002](0002-camoufox-for-rendering-only.md)).
4. Structured extraction: JSON-LD, Microdata, OpenGraph, app state, captured XHR
   JSON.
5. LLM extraction, only for a store still at zero products.
6. Normalise, then validate, then output with provenance.

The LLM stage uses ScrapeGraph's technique (describe *what* to extract with a
schema) as a direct Claude call with a Pydantic schema, on page text the bot
already holds.

## Rejected alternatives

- **ScrapeGraph API (paid).** Recurring cost for something the bot can do with
  one direct LLM call, on a small number of sites.
- **Replace the pipeline with the ScrapeGraphAI library.** This would swap the
  free, exact Shopify feed (6,167 priced products in recon) for an LLM read of a
  few pages per store. It would also make `knit_share`, which needs the whole
  catalogue, meaningless. Results would vary between runs and could not be
  tested offline.
- **ScrapeGraphAI as the LLM stage.** `SmartScraperGraph` handles one URL at a
  time and sends every chunk of a page to the model. It also pulls in LangChain
  and Playwright-Chromium. The bot already chooses its pages and holds their
  text, so it needs about 5% of the library.
- **Site-specific selectors.** They must be written for every site and break on
  every redesign.

## Consequences

- Most stores are expected to be read without a browser or LLM. The Phase 1
  probe measures this.
- LLM rows are flagged `needs_review`, and each product must cite the page it
  came from.

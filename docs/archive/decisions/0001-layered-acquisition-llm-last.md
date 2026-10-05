# 0001 — Layered acquisition, LLM last

**Date:** 2026-10-05
**Status:** Proposed

## Context

v1 reads non-Shopify stores only through JSON-LD. Sites without it return zero
products. ScrapeGraphAI was evaluated as a way to read any site without writing
selectors for each one.

## Decision

Non-Shopify acquisition is a sequence of layers, cheapest and most exact first:

1. Platform feeds.
2. Embedded structured data.
3. Product sitemaps.
4. Browser render.
5. LLM extraction.

A store stops at the first layer that yields products.

The LLM layer adopts ScrapeGraph's technique (describe *what* to extract with a
schema), but implements it as a direct call on page text the bot already holds.
ScrapeGraphAI stays an optional alternative.

## Rejected alternatives

- **Replace the pipeline with ScrapeGraphAI.** This would swap the free, exact
  Shopify feed (6,167 priced products in recon) for an LLM read of a few pages
  per store. It would also make `knit_share`, which needs the whole catalogue,
  meaningless. Results would vary between runs and could not be tested offline.
- **ScrapeGraphAI as the LLM layer by default.** `SmartScraperGraph` handles one
  URL at a time and sends every chunk of a page to the model. It also pulls in
  LangChain and Playwright-Chromium. The bot already chooses its pages and holds
  their text, so it needs about 5% of the library.
- **Site-specific selectors.** These must be written for every site and break on
  every redesign.

## Consequences

- Most stores are expected to be read without a browser or LLM. Phase 1 of the
  v2 plan measures this.
- LLM rows are flagged `needs_review`, and each product must cite the page it
  came from.

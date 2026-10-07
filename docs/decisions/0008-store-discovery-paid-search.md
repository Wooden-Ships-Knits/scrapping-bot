# 0008 — Store discovery with paid search APIs; knitwear focus

**Date:** 2026-10-07
**Status:** Accepted

## Context

Until now the operator had to bring the list of store links (PRD 2.0, section 5.2:
"finding new stores automatically" was out of scope). A separate prototype, the
*knitwear store finder*, did that part: it searched Google Maps, the web, Instagram
and Facebook (through search results) and an LLM with web search, merged the hits
into one record per store, and then opened every store's website a second time to
label it and to scrape its sweaters with its own Playwright scraper.

That left two tools that each visited store websites, with different rules for
politeness, prices and statuses. The operator decided to combine them: the finder
finds, scrapebot scrapes, and the finder's labelling step goes. The business only
cares about knitwear.

## Decision

- **`scrapebot discover` is a step before a run.** It searches, merges and writes a
  links file (`data/discover/<id>/stores.csv`) that `scrapebot run` reads like any
  other input. Store details (name, address, phone, profiles, which search found it)
  travel as input metadata, so they appear in the run's `inputs` table and summary.
- **Sources** come from the finder, rewritten to scrapebot's rules:
  - Google Places API (Text Search, New), with a field mask limited to what finding
    and visiting a store needs: name, address, website, phone, status. No ratings,
    reviews, coordinates or summaries are requested or stored.
  - Tavily for web search, for Instagram and Facebook profiles (search results only,
    the profiles are never opened), and to look up the website of a store known only
    by name or profile.
  - An LLM with web search, through LiteLLM's `web_search_options`
    ([ADR 0004](0004-llm-gateway-litellm-instructor.md)), not one SDK per provider.
- **Every paid call is capped and cached.** Each source has a hard request cap; the
  agent has a cost cap. Successful answers are cached on disk without the key, so a
  repeated discovery costs nothing. A source without its key is skipped.
- **Discovery never opens a store's website.** Whether a store sells knitwear, which
  brands it carries and whether it is multi-brand are read from the data a run
  collects. The finder's labelling (`classify`, its AI second opinion), its scraper and
  its Playwright browser are not carried over.
- **The customer-account matching is not carried over.** Sales figures stay out of
  this tool until the analysis phase decides how to use them.
- **Knitwear focus without dropping data.** Discovery searches for knitwear stores
  (queries, brand seeds, agent prompt). A run flags every product with `is_knitwear`
  and every store with `knit_count`, using the existing knitwear rule. No product is
  dropped: raw means raw, and a store's non-knit catalogue still says something about
  it.

## Rejected alternatives

- **Keep the finder as a separate tool.** Two scrapers with different politeness,
  price and status rules, and a store visited twice per discovery.
- **Port the finder's labelling as well.** It is the analysis phase (roadmap, "Next
  phase"), which works from the raw data and has its own PRD.
- **Keep only knitwear products.** Smaller output, but it breaks "raw means raw", hides
  stores that sell knitwear under unexpected names, and loses the store-wide price
  band. A filter on `is_knitwear` gives the same view.
- **Scrape Instagram and Facebook profiles.** Both forbid automated collection and
  block it ([ADR 0002](0002-camoufox-for-rendering-only.md)).

## Consequences

- Discovery costs money per request: Google Places bills per search, Tavily per
  query, the agent per token. The caps in `discover.example.yaml` bound one discovery.
- Search coverage follows the configured places and queries: Google returns at most
  60 places per search, so a town not listed is missed.
- Google's terms for Places content limit how long it may be cached and where it may
  be shown. Only the fields above are kept, in the operator's local run data; check
  the current terms before sharing discovery output outside the team.
- The sources were written against each provider's documentation and tested offline;
  their first real discovery is the real test of the request formats.
- `products.is_knitwear` and `stores.knit_count` are new columns in every export.

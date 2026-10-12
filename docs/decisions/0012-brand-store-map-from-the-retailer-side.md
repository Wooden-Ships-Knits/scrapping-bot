# 0012 — Brand and store map from the retailer side; locators only where the list is open

**Date:** 2026-10-12
**Status:** Proposed

## Context

The next phase asks where brands like Wooden Ships are sold, which of those stores we
already have, and where the gaps are
([PRD — Competitive and Retailer Analysis](../product/prd-competitive-retailer-analysis.md)).
The proposal named four brands (White + Warren, Lilla P, Rails, Z Supply) and assumed
their retailer lists could be collected from their sites.

Measured on 12 October 2026:

- None of the four publishes a list the bot may read. Z Supply's locator is fed by
  Storemapper, whose data host answers `Disallow: /` to every agent. Rails lists its own
  shops. White + Warren took its locator down. Lilla P's locator page is empty.
- Of 24 other brands that stores in run `20261009T073717823Z-e4d60c` carry most, 4 use
  Stockist.co, whose `robots.txt` allows crawlers. Of the 3 feeds tried, 1 (Heartloom)
  returns the whole list in one request; Habitat and Joseph Ribkoff return "Method not
  allowed" for it and offer pin coordinates and search by area.
- The data we already hold answers the question from the other side. `vendor` in the
  run's `products` table shows 67 stores selling at least one of the four brands, 59 of
  them partner candidates not matched to a stockist.
- Where a full list exists it is large and mostly new to us: Heartloom's 415 retailers
  gave 29 stores shared with Wooden Ships and 120 with no stockist within 15 miles, and
  only 3 of the 415 were in the 808-store run.

[ADR 0008](0008-store-discovery-paid-search.md) keeps discovery away from store
websites, and [ADR 0011](0011-wholesale-analysis-stage.md) keeps the analysis from
fetching anything. Neither stage can read a locator as written.

## Decision

- **The map is built from the retailer side first.** `brand_stores` holds one row per
  brand, store and source. The `vendor` column of scraped catalogues is the main
  source, read from the full `products` table (the `brands` column of the analysis
  sheet keeps 15 brands per store and undercounts). A brand's published list is a
  second source with its own rows.
- **A locator is read only when two things hold:** the `robots.txt` of the host that
  serves the data allows it, and the feed gives the whole list in the request the
  widget itself makes. The first reader is for Stockist.co.
- **A list the brand does not publish as a whole is not rebuilt.** No search area by
  area where "list all" is off, no rendering a page in the browser to capture a feed
  the host disallows, no reading a locator the brand has removed from its site. Pin
  coordinates from the widget's own overview request may be counted per state.
- **Reading locators is its own command, before the analysis.** It writes each brand's
  list as found under `data/` and the analysis reads those files. The analysis still
  fetches nothing, and discovery still opens no store website.
- **Finding more stores of a relevant brand reuses discovery's brand search** (`brands`,
  `agent.brand_tasks`, `web_search.brand_queries`) and the ordinary run. No new search
  source.
- **The expansion is bounded.** One round by default, caps on brands and on new stores,
  candidates compared with stores already read before any request, and stores outside
  the chosen region kept but not scraped unless the operator says so.
- **A brand is judged across stores, with an evidence floor**, from components kept as
  separate columns. The operator's label in `brands.csv` wins over the computed rank. A
  hand-labelled gold set measures every change to the method.
- **Stores are matched by domain, phone, then name with place.** A name alone, or a
  name with only the state, is a case for review, never a match.
- **Every row says where it came from and how complete it is:** source, evidence,
  confidence, and per brand whether its stores are a full published list or a sample.
- **This stays in scrapebot.** Tables in the existing writers; no graph database and no
  separate service. New dependencies are limited to loose name matching (`rapidfuzz`)
  and TF-IDF with cosine similarity (`scikit-learn`). Sentence embeddings wait for a
  measured need.

## Rejected alternatives

- **Scrape the brands' own sites for their retailers.** The four named brands show
  nothing there. A brand's site gives its catalogue and retail prices, which is useful
  for product and price comparison, not for distribution.
- **Read Storemapper feeds, or enumerate area search on closed Stockist feeds.** The
  first breaks [ADR 0002](0002-camoufox-for-rendering-only.md). The second walks around
  a setting the brand chose, for hundreds of requests per brand.
- **Wholesale marketplaces and social profiles.** They need a login, or are profiles
  discovery does not open.
- **A separate project.** Discovery, acquisition, the tables, customer matching and the
  distance code would be copied or turned into a dependency, and two repositories kept
  in step.
- **A graph database for the relationships.** Every question in the PRD is a join or a
  count over a few thousand rows.
- **Ranking brands by text similarity alone.** Product text in our data is written by
  each store, not by the brand, and much of it is marketing copy that reads alike. It
  is one component among five.

## Consequences

- For most brands the result is a sample of the stores we happened to read. It supports
  "which stores" and "which brands are sold together"; it cannot be read as a share of
  a brand's retailers, and the workbook has to say so per brand.
- Which brands get a full list depends on which widget they bought, not on how much
  they matter to us. The locator survey decides where the reader is worth the work.
- A locator list often has no website or phone (Heartloom's has neither). Those stores
  need a website lookup before the bot can read them, and can only be matched by name
  and place.
- The loop from brand back to stores costs paid searches and Shopify's rate limit.
  The caps make a round predictable; they also mean a round leaves stores out, and the
  report names how many.
- "Not ours" is measured against `stockists.json` until the Salesforce export exists.
- Rails and Z Supply, the most carried brands in the run, hold 12% and 15% knitwear.
  Brand relevance needs two lists: knitwear rivals, and brands that mark the right kind
  of boutique.

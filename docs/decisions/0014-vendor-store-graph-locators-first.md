# 0014 — Vendor and store graph in six layers; store locators first, catalogue vendors as the fallback

**Date:** 2026-10-13
**Status:** Proposed
**Supersedes:** [ADR 0012](0012-brand-store-map-from-the-retailer-side.md)

## Context

[ADR 0012](0012-brand-store-map-from-the-retailer-side.md) proposed building the map of
who sells which brand from the retailer side first (the `vendor` of each product) and
reading a brand's store locator only as a second source. It was never accepted.

On 13 October 2026 the product owner set the plan for the phase as six layers and
reversed that order: read what a site says outright first (its store locator, or a page
like it), and fall back to the vendors in a store's catalogue where that is not
possible. The aim is stated as reverse engineering: learn where each vendor's goods go,
then find the vendors that overlap with Wooden Ships.

Measured the same day on run `20261009T073717823Z-e4d60c` (808 stores, 287 readable):

- A page with a locator-like address was already read for up to 27 stores, most holding
  several thousand characters of text, though the run does not look for such pages on
  purpose and marks only 10 stores as having a `stockist` page. A brands or designers
  page was read for 101 stores.
- 95% of 195,901 products name a vendor, in 224 stores. The 10,308 spellings fall to
  8,663 with a plain rule; 1,330 vendors were written more than one way; 9% of the
  products name the store itself; 75% of vendors are seen in one store only.
- From ADR 0012's check: none of the four brands named in the proposal gives a list
  the bot may read, and of three Stockist.co feeds one returns its whole list.

## Decision

- **Six layers, each reading only what the one before wrote:** (1) data acquisition,
  (2) goals and method, (3) preprocessing and normalisation, (4) entity resolution,
  (5) reverse engineering, (6) insight. Layer 1 is the existing discovery and run.
- **Route 1 comes first: what a site says outright.** On a vendor's own site, its
  locator or stockist list gives the stores that sell it. On a multi-brand store, its
  brands page gives the vendors it sells. A store's own list of shops gives places.
  Wooden Ships' stockist list is the same kind of list. These pairs are `declared`.
- **Route 2 is the fallback: the vendor of each product** in a store's catalogue,
  where a site has no such page or the bot may not read it. These pairs are `observed`.
- **Both are kept, with their source.** `declared` outranks `observed` when they
  disagree. Coverage is stated per vendor: a full published list, or a sample of the
  stores the bot happened to read. A store that was not read is unknown, not a "no".
- **Layer 1 gains a locator pass.** For every store read, the run looks for a locator,
  stockist, retailer, "where to buy" or brands page on purpose and stores it as found.
  A widget feed is read only when the `robots.txt` of the host serving it allows it and
  it gives the whole list; the first reader is for Stockist.co. Discovery still opens
  no store website ([ADR 0008](0008-store-discovery-paid-search.md)), and the analysis
  still fetches nothing ([ADR 0011](0011-wholesale-analysis-stage.md)).
- **A list the vendor does not publish as a whole is not rebuilt.** No search area by
  area where "list all" is off, no rendering a page to capture a feed its host
  disallows, no reading a locator the vendor has removed
  ([ADR 0002](0002-camoufox-for-rendering-only.md)). Such a vendor is covered by
  route 2.
- **Normalisation is fixed rules, an alias list and a review list.** A vendor key
  (trim, lower case, `&` and `+` as "and", letters and digits), aliases and sub-lines
  from `brands.csv`, the store's own name and placeholders dropped, places and phones
  to one form. Raw values stay beside the cleaned ones. No fuzzy merging of vendor
  names and no learned model.
- **Two kinds of node: vendor and store.** A store is matched by domain, then phone,
  then name with place; a name alone, or a name with only the state, goes to review. A
  vendor whose own site was read is linked to that store record. Wooden Ships is a
  vendor node like any other.
- **The graph is tables:** one row per vendor, store and source. No graph database and
  no separate service; it stays in scrapebot.
- **A vendor is described by separate parameters,** each its own column: stores in
  common with Wooden Ships, number of stores and coverage, knitwear share, price
  against ours, kinds of garment and material, and geography. It is ranked only above
  an evidence floor, and the operator's label in `brands.csv` wins over the rank.
- **No new dependency in layers 3 to 5.** Loose name matching and text similarity
  (TF-IDF, embeddings) wait for a measured need.

## Rejected alternatives

- **Catalogue vendors first, locators second (ADR 0012).** It was the cheaper order,
  because the data is already held. It makes the weaker evidence the main one: a
  catalogue shows a sample of a vendor's stores, a locator states the whole list.
- **Locators only.** Most vendors do not publish a list the bot may read; the four
  named brands publish none. Without the fallback they would have no pairs at all.
- **Read every locator whatever its host says, or enumerate area search.** The first
  breaks ADR 0002. The second walks around a setting the vendor chose.
- **Fuzzy or learned merging of vendor names.** Two different vendors with similar
  names would become one, and nobody could say why. The alias list is slower and can
  be read.
- **A graph database.** Every question in the PRD is a join or a count over a few
  thousand rows.
- **A separate project.** Discovery, acquisition, the tables, store matching and the
  distance code would be copied or turned into a dependency.

## Consequences

- Layer 1 is not finished for this phase: the locator pass has to be built before
  route 1 gives more than the pages the run came across by chance.
- Which vendors get a full list depends on how they publish it, not on how much they
  matter to Wooden Ships. For the rest the result is a sample, and every output has to
  say so.
- A locator list often has no website or phone. Those stores can only be matched by
  name and place, and need a website lookup before the bot can read them.
- Sub-lines ("Z Supply Lounge") merge only when someone lists them as aliases. The
  alias list needs an owner.
- Three quarters of vendors are seen in one store. They stay in the graph and are not
  ranked.
- "Not ours" is measured against the stockist list until the account export exists.

# 0010 — Final list: multi-brand stores that sell knitwear

**Date:** 2026-10-09
**Status:** Accepted

## Context

The operator wants each run to end in a list they can act on: stores that resell
other brands (a boutique, not Nike or a designer's own shop) and sell knitwear, with
the knitwear products themselves. Until now the bot only collected: every product
was flagged `is_knitwear`, and `stores.store_type` was filled only when the LLM read
a store, which was almost never.

Two measurements on the 808-store run of 2026-10-08 shaped the decision:

- **The broad knitwear flag is too loose for a list.** It matches a knit word in the
  title, type, tags or description. Of 45,108 flagged products, a sample showed tees,
  trousers, socks, candles, denim "jumpers" (overalls) and sweatshirts, taken in
  through a tag such as "knit" or a fabric line.
- **Vendors settle most store types.** Of 267 readable stores, 176 name three or more
  outside brands as product vendors (25southboutiques.com: 192). The other 91 name no
  vendor, only their own name, or one brand for nearly everything: a boutique and a
  label look the same there.

The LLM stage had also been off by default, so custom sites with no structured data
ended `no_products` even when their pages showed products and prices: about 30 such
stores across the historical runs never had the LLM tried.

## Decision

- **A final list, derived, never destructive.** At the end of a run the bot writes
  `final_stores` and `final_products` (`tables/` and `export/final/`) from the raw
  tables. The raw tables still keep every store and product, so the criteria can
  change without a new scrape.
- **A store qualifies** when it was read (`ok`), is `multi_brand`, and has at least one
  product whose `knit_kind` is set.
- **Strict knitwear, `products.knit_kind`** (`extract/knitwear.py`): from the title,
  and the product type when the title is only a name. `garment` for sweaters,
  cardigans, pullovers, knit jumpers, turtlenecks, ponchos and knit or cashmere/wool
  tops; `accessory` for beanies and knitted scarves, hats, gloves and wraps. Tags and
  descriptions are not read. Sweatshirts, jersey basics, woven wool coats, yarn and
  knitting supplies, pet and home goods are excluded. The broad `is_knitwear` flag
  stays as it was, as a raw signal.
- **Store type: rules first, the LLM for the unclear rest** (`extract/brands.py`,
  `final.judge_store`). Three or more outside brands, none above 90% of the branded
  products, is `multi_brand`. Vendors equal to the store's own name and placeholders
  ("Default Vendor") do not count. Anything else is `unknown`; when the store sells
  knitwear, the LLM judges it from its about, brands and home pages, its vendors and
  some product names (`llm/prompts/store_type_v1.md`). An answer below 0.6
  confidence leaves the store `unknown`, and the report lists it for a person to
  check. The rule alone never says `own_brand`. `stores.store_type_source` records
  `vendors` or `llm`.
- **A knitwear-only download** (`knit_products`, `export/knit/`): every knitwear product
  of every store that was read, with the store's type and whether it made the final list,
  for when own-label and unclear stores matter too.
- **The LLM is on by default**, with `openai/gpt-4o-mini` and a US$1 budget per run
  (about US$0.001 a store on real runs). It reads stores no other stage could (PRD
  LM-06) and judges store types. Without the provider's key the run goes on without
  it and the report says so; `--no-llm` turns it off.

## Consequences

- The operator downloads one small workbook (`Daftar final`) instead of filtering a
  200,000-product export, and the web app opens a run on the final list.
- A store whose type stays unclear is left off the list, not guessed onto it. The
  report names those stores.
- Runs cost a little money by default. The budget caps it, every call is in
  `llm_calls`, and the report shows the total.
- `knit_kind` is deliberately narrow: a "Cashmere & Silk Scarf" or a "Knit Midi
  Dress" is left out. Widening it is a change to `extract/knitwear.py` and its tests,
  and the next run applies it, since raw products are kept.
- Store type and strict knitwear are judgements, which PRD 1.0 left to the analysis
  phase. They are kept as columns beside the raw data and can move there unchanged.

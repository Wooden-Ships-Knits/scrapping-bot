# 0011 — Wholesale analysis as its own stage over a finished run

**Date:** 2026-10-09
**Status:** Accepted

## Context

The scraped data feeds one decision: which stores are **retail partners** (boutiques that
could stock Wooden Ships), **B2B partners** (hotel, resort and club shops, gift and museum
shops, outfitters, promotional suppliers, showrooms and agencies), **competitors** (own
labels that sell knitwear), and which are **existing customers** already. The PRD left that
analysis to a next phase. Measured on the 808-store run of 2026-10-09, the raw tables carry
most of what it needs (vendor on 95% of products, tags 70%, product type 73%, price 100%,
email for 74% of readable stores), but not as answers: no business type, no location for a
pasted list, no link to the stockist list or the Salesforce accounts, no price fit.

## Decision

- **A separate command, `scrapebot analyze <run>`.** It reads a finished run and the
  operator's files in `data/inputs/` (stockists, a Salesforce account export, brands with
  their relation, Wooden Ships' price points) and writes `<run>/analysis/`: an Excel
  workbook (`stores`, `knit_products`, `competitors`, `brands`) and a README of the inputs
  it used and lacked. It never fetches a store and never changes the run's tables, so it
  is re-run whenever an input changes, without scraping again.
- **Every judgement has its reasons.** A segment and a 0–100 score per partner, with each
  point in `reasons` (knitwear on offer, peer brands carried, price fit, a stockist within
  the territory radius, brand count, a way to reach them, a wholesale page, new products).
- **Business type from strong evidence only.** Known chains and marketplaces, the store's
  name and domain, and multi-brand vs own label decide it. Phrases on the store's pages
  ("golf shop", "country club") are shown as `b2b_hints` for a person, because boutiques
  use them too; "consignment" is the exception, being unambiguous.
- **Location without a new request.** From the input row when the list came from discovery,
  else from the address a store writes on its contact, about or home page (48% of
  readable stores on 2026-10-09). Points come from geocoding the postal code (OpenStreetMap
  Nominatim, one request a second, cached in `data/.cache/geocode.json`).
- **Existing customers by domain, phone, then name.** A name match must be exact once the
  words stores add are dropped ("The Tango Boutique" is "tango"); a partial match counts
  only where the state agrees. Listing sites given as a stockist's website (MapQuest) are
  ignored.
- **Prices read as written.** `products.price_minor_unit` (new) records when `price_raw` is
  in minor units (WooCommerce, `priceCents`), so the analysis reads "4800" as 48.00 without
  the raw value changing. Price fit compares US-dollar prices only; nothing is converted.

## Consequences

- The wholesale team gets one workbook per run, sorted best candidates first, with the
  evidence beside every verdict, and can change the inputs and re-run in minutes.
- Most B2B prospects are not in today's lists: discovery searched for knitwear stores. B2B
  partners need their own discovery queries (resort boutiques, pro shops, museum stores).
- Scores rest on the inputs: without `brands.csv` and `price_points.csv` those points are
  left out and the README says so.
- Business type and name matching are rules and will file some stores wrongly; each
  verdict names its evidence so a person can correct it.

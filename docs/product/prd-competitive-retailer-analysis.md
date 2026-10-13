# PRD — Competitive and Retailer Analysis

| | |
|---|---|
| **Version** | 0.2 (draft) |
| **Date** | 13 October 2026 |
| **Status** | Draft for review. Layer 1 is built; nothing in layers 3 to 6 is built in scrapebot yet |
| **Product owner** | _(fill in the owner's name)_ |
| **Extends** | [PRD — Scrapebot](prd.md), section 3 ("Competitor or partner analysis: next phase, with its own PRD") and [ADR 0011](../decisions/0011-wholesale-analysis-stage.md) |
| **Technical documents** | [ADR 0014](../decisions/0014-vendor-store-graph-locators-first.md) · [Architecture](../architecture/overview.md) · [Roadmap](../planning/roadmap.md) |

**What changed since 0.1 (12 October).** The product owner set the plan as six layers
and reversed the order of the two ways to learn who sells what. Version 0.1 built the
map from the retailer side first and read store locators only as an extra. Version 0.2
reads **store locators and the pages like them first**, and falls back to **the vendors
named in each store's catalogue** where a site has no such page or the bot may not read
it. [ADR 0012](../decisions/0012-brand-store-map-from-the-retailer-side.md) is
superseded by ADR 0014. The numbered requirements of 0.1 are replaced by those in
[section 9](#9-requirements).

---

## 1. Summary

Wooden Ships wants to know where the goods of vendors like itself go: which stores
carry them, which of those stores Wooden Ships already sells to, and which vendors sit
closest to it. Vendors rarely hand that over, so the bot works it out backwards
(reverse engineering) from what stores and vendors publish:

1. **Preferred:** a site's own store locator, stockist list or brand list says outright
   who sells whom.
2. **Fallback:** a store's product catalogue names a vendor on each product; gathered
   over many stores, that shows where each vendor's goods flow.

Both give the same thing, a list of **vendor and store pairs**. With vendors and stores
cleaned and matched, the pairs form a graph. Wooden Ships is one vendor in it. The
vendors that share its stores, its kind of product and its price range are its
competitors, and the stores that carry them but not Wooden Ships are the ones to
approach.

## 2. Problem and business outcomes

**Problems today:**

1. `scrapebot analyze` scores each store on its own. It does not show a vendor's
   retailers as a group, or compare that group with ours.
2. The wholesale team picks which brands to watch by judgement. Nothing ranks vendors
   by how close they are to Wooden Ships.
3. Discovery searches for knitwear stores. A store that carries a similar vendor but
   did not match a knitwear search is never found.

**Target business outcomes:**

| Outcome | Measure |
|---|---|
| A list of stores to contact, with the reason | Stores that carry vendors like ours and are not Wooden Ships customers, ranked, each with its evidence |
| Regions to prioritise | Per state or province: retailers of those vendors against Wooden Ships stockists |
| A watch list of vendors chosen from data | Vendors ranked by how much they overlap with Wooden Ships, with the parts of the rank shown |
| Known risk in our own accounts | Current Wooden Ships retailers that also carry closely overlapping vendors |

## 3. The six layers

| Layer | What it does | Status |
|---|---|---|
| **1. Data acquisition** | Finds stores and reads their catalogues, pages and contacts | Built. One addition is needed for the preferred route: [section 4](#4-layer-1-data-acquisition) |
| **2. Goals and method** | This document: what is reverse engineered, and by which route | This document |
| **3. Preprocessing and normalisation** | One clean name per vendor and one clean record per store, raw values kept beside them | Explored in notebooks only |
| **4. Entity resolution** | Decides which records are the same vendor or the same store, and links them | Exists for stores against stockists; not for vendors |
| **5. Reverse engineering** | Builds the vendor and store graph and measures overlap and similarity | Explored in notebooks only |
| **6. Insight** | Turns the graph into the lists and tables the wholesale team uses | A first page exists (Retailer map), fed by the notebooks |

Each layer reads only what the layer before wrote. A layer can be run again without
running the ones before it.

## 4. Layer 1: data acquisition

Built ([PRD — Scrapebot](prd.md)): discovery finds stores, a run reads each store's
product feed or pages, and writes seven raw tables. What this phase uses from a run:

| Table | Used for |
|---|---|
| `stores` | The store itself: domain, platform, status, store type (own label or multi-brand) |
| `products` | `vendor` on each product: the fallback route |
| `pages` | The text of each page read, with its kind (`stockist`, `brands`, `wholesale`, …): the preferred route |
| `contacts` | Phone and email, for matching stores |

**What the data already holds** (run `20261009T073717823Z-e4d60c`, 808 stores, 287
readable; measured 13 October 2026):

| Measured | Result |
|---|---|
| Readable stores by type | 206 multi-brand, 44 own label, 37 undecided |
| Stores where a page with a locator-like address was read (`store-locator`, `stockists`, `retailers`, `where-to-buy`, `locations`) | 27: 9 own label, 10 multi-brand, 8 undecided. Counted by address only, so a few are not locators (one is a news post with "location" in its address) |
| How much text those pages hold | Median 4,577 characters; 18 of 27 over 3,000. Examples: eribe.com `/pages/store-locator` 31,818, bridgeandburn.com `/pages/stockists` 8,454, bareknitwear.ca `/pages/retailers` 4,577 |
| Stores where a brands or designers page was read | 101 (217 pages) |
| Products with a vendor | 185,477 of 195,901 (95%), in 224 stores |

**The addition layer 1 needs.** Today the run reads a locator page only when it
happens to come across the link, and it marks only 10 stores as having a `stockist`
page while up to 27 have a locator-like page. Two things are missing for the preferred
route:

- **A locator pass.** For every store read, look for a store locator, stockist,
  retailer, "where to buy" or brands page on purpose, and read it.
- **Widget feeds.** Many locators are a map drawn by a third-party service (Stockist.co,
  Storemapper and others); the page text is then empty and the list sits in a feed.
  The feed is read only where the service's `robots.txt` allows it and it gives the
  whole list ([section 10](#10-out-of-scope)).

Raw stays raw: the pass stores what it found as written. Reading a list into vendor
and store pairs is layer 3.

## 5. Layer 2: goals and method

### 5.1 The goal

A table of **vendor and store pairs**, each with where it was seen, good enough to
answer: where do this vendor's goods go, which vendors go to the same stores, and how
close is each of them to Wooden Ships.

### 5.2 Route 1, preferred: what a site says outright

For every site read, Shopify or not, the bot looks for a store locator or a page like
it. What the page tells depends on whose site it is:

| Site | Page | What it gives |
|---|---|---|
| A vendor's own site (own label) | Store locator, stockists, retailers, "where to buy" | The stores that sell this vendor: pairs for one vendor and many stores |
| A multi-brand store | Brands, designers, "brands we carry" | The vendors this store sells: pairs for one store and many vendors |
| A multi-brand store with several shops | Locations, "our stores" | The store's own shops: places, no vendor. Used to place the store on the map and to match it |
| Wooden Ships itself | Its stockist list (`data/inputs/stockists.json`, 500 stores) | Wooden Ships' pairs: the same kind of list, already held |

A pair from route 1 is a statement by the vendor or the store. It is marked
`declared`.

### 5.3 Route 2, fallback: what the catalogue shows

Where a site has no such page, or the bot may not read it, the store's products are
read and the vendor of each product is taken. One store selling 40 products of a vendor
is one pair, with the 40 as its weight. A pair from route 2 is marked `observed`.

### 5.4 How the two routes combine

- Route 1 is tried first for every site. Route 2 fills in what route 1 does not give.
- A pair seen by both routes keeps both sources. `declared` outranks `observed` when
  they disagree about a name, and a pair seen by both is the most certain.
- Coverage is stated per vendor: **full list** when the vendor's own locator gave its
  stores, **sample** when its stores are only those the bot happened to read. A sample
  is never shown as a share of the vendor's retailers.
- A store that was not read (521 of 808 in the measured run: blocked, failed or without
  a catalogue) is **unknown**, not "does not sell it".

### 5.5 What is known about route 1 so far

| Checked on 12 October 2026 | Result |
|---|---|
| The four brands named in the proposal | None gives a list the bot may read. Z Supply's locator is fed by Storemapper, whose data host disallows all crawlers. Rails lists only its own shops. White + Warren removed its locator. Lilla P's locator page is empty |
| 24 brands most carried by stores in the run | 4 use Stockist.co, 1 Storemapper, 5 have a stores page with no recognised widget, 6 have no locator, 8 could not be checked |
| 3 Stockist.co feeds | Heartloom returns its whole list (415 US retailers: name, address, coordinates; no website or phone). Habitat and Joseph Ribkoff give pin coordinates and search by area only |

So route 1 is the better evidence where it exists, and it will not exist for every
vendor. For the four named brands the answer today comes from route 2: 67 stores sell
at least one of them (Z Supply 36, Rails 29, White + Warren 18, Lilla P 15), and 59 of
those are not Wooden Ships stockists.

## 6. Layer 3: preprocessing and normalisation

The aim is the least cleaning that makes layer 4 work: fixed rules, an alias list a
person can edit, and a list of what the rules were unsure about. No model, no
similarity scoring, no new dependency.

**What the vendor field looks like** (same run):

| Measured | Result |
|---|---|
| Different vendor spellings | 10,308 |
| After trimming, lower case, and dropping punctuation, with `&` and `+` read as "and" | 8,663 |
| Vendors still written more than one way before that | 1,330. Z Supply has 8 spellings, White + Warren 6, Free People 6 |
| What the rule does not merge | Sub-lines: "Z Supply Lounge", "Z Supply Activewear", "Free People Beach" |
| Products whose vendor is the store's own name | 16,895 (9%): not a vendor, the store's own label |
| Vendors seen in one store only | 6,457 of 8,663 (75%) |

**Rules, in order:**

| Step | Rule | Why |
|---|---|---|
| Vendor key | Trim, lower case, `&` and `+` to "and", keep letters and digits | Merges 1,330 vendors written several ways |
| Aliases | `brands.csv` may list aliases and sub-lines per vendor ("Z Supply Lounge" is Z Supply) | The only way to merge sub-lines without guessing |
| Own label | A vendor that is the store's own name is marked `own_label` and gives no pair | 9% of products; otherwise every store looks like its own retailer |
| Placeholders | "Default Vendor", "Gift Card", "Sale" and the like are dropped | The existing list in `extract/brands.py` |
| Declared lists | A locator or brands page is split into rows (name, address, city, state, postal code, website or phone where given), values as written | Layer 4 needs fields, not a page of text |
| Places | State and province to their two-letter code, postal code to one form, country to its code | Already in `discover/geo.py` |
| Store names | The existing core name ("The Tango Boutique" and "shoptango.com" are "tango") | Already in `analysis/inputs.py` |
| Phones and domains | Last ten digits; registrable domain | Already in the code |

Raw values are never changed: every cleaned value sits beside the value as found.

**Left out on purpose:** spelling correction, fuzzy merging of vendor names (two
different vendors with similar names would become one), translation, and any learned
model. A vendor seen in one store is kept and not ranked.

## 7. Layer 4: entity resolution

Two kinds of thing, each with one record however many times it was seen:

| Node | What it is | Its key |
|---|---|---|
| **Vendor** | A brand whose goods are sold in stores. Wooden Ships is one | The vendor key and its aliases; the vendor's own domain when its site was read |
| **Store** | A retailer: a website, with one or more shops | The domain; else phone; else name with place |

**Matching rules:**

| Case | Rule |
|---|---|
| Two store records | Same domain: the same store. Else same phone: the same store. Else same core name **and** same postal code or within 1 mile: the same store. Same name and state only: to review, not a match |
| A vendor and a store | A vendor whose own site was read is linked to that store record (eribe.com is both the vendor Eribe and a site the bot read) |
| A locator row without a website | Matched by name with place; a website is looked up for it later, within the existing cap |
| A name alone | Never a match |

Every match records how it was made (`domain`, `phone`, `name+place`) and unsure cases
go to a review table. The same rules already match scraped stores to Wooden Ships
stockists; this layer applies them to every store and every list.

**The link between nodes** is the pair of section 5:

| Field | Meaning |
|---|---|
| `vendor_key`, `store_key` | The two nodes |
| `source` | `locator_page`, `locator_feed`, `brands_page` (route 1) or `product_vendor` (route 2) |
| `evidence` | `declared` or `observed` |
| `evidence_url`, `seen_at`, `run_id` | Where and when it was seen |
| `products`, `knit_products` | For `product_vendor`: how many products carry the pair |

The graph is kept as tables. Every question in this document is a join or a count over
a few thousand rows, so no graph database is used.

## 8. Layers 5 and 6: reverse engineering and insight

### 8.1 Layer 5: what is worked out

| Result | How | Meaning |
|---|---|---|
| A vendor's stores | Every pair with that vendor | Where its goods go, with coverage stated |
| A store's vendors | Every pair with that store | What kind of store it is |
| Vendors that overlap | For two vendors: stores both are in, against stores either is in | Sold side by side |
| Overlap with Wooden Ships | The same, with Wooden Ships as one of the two | How close a vendor is to us |
| Sold together more than chance | For pairs with enough stores | Vendors that travel together |

**Parameters of a vendor**, each its own column so the rank can be checked by hand:

| Parameter | From |
|---|---|
| Stores in common with Wooden Ships | The graph |
| Number of stores, and coverage (full list or sample) | The graph |
| Share of its products that are knitwear | `products`, the existing strict rule |
| Price against Wooden Ships, for the same kind of garment | `products` and `price_points.csv`, US dollars only |
| Kinds of garment and materials it sells | `products` |
| Where its stores are, against where ours are | Store places and the stockist list |

A vendor is ranked only with enough evidence (proposed floor: 8 stores and 30
products). A vendor the operator labels in `brands.csv` keeps that label whatever the
rank says. Text similarity (TF-IDF, embeddings) is not part of this version.

### 8.2 Layer 6: what the wholesale team gets

| Output | Content |
|---|---|
| **Stores to approach** | Stores that carry overlapping vendors and are not Wooden Ships customers, best first, with the vendors found there, the nearest stockist and a contact |
| **Vendors closest to us** | The ranked vendors with every parameter, in two lists: those that compete on knitwear, and those that mark the right kind of store (Rails and Z Supply are the most carried, with 12% and 15% knitwear) |
| **Regions** | Per state or province: retailers of overlapping vendors, Wooden Ships stockists, and stores with no stockist nearby |
| **Risk in our accounts** | Wooden Ships retailers that also carry closely overlapping vendors |
| **Review list** | Matches and labels the rules were unsure about |

Shown on the *Retailer map* page of the interface and written to the analysis
workbook. Every row names its source, its evidence and its coverage.

## 9. Requirements

Priorities: **Must**, **Should**.

| ID | Layer | Requirement | Priority | Acceptance criteria |
|---|---|---|---|---|
| A-01 | 1 | A locator pass: for every store read, look for a locator, stockist, retailer, "where to buy" or brands page and read it | Must | On the measured run the real locators among the 27 candidates of section 4 are found, and a page that merely has "location" in its address is not counted |
| A-02 | 1 | A widget feed is read only when the `robots.txt` of the host serving it allows it and it gives the whole list. First provider: Stockist.co | Must | Test: an allowed page with a disallowed data host is not read. Heartloom's 415 locations reproduce from a recorded fixture |
| A-03 | 1 | A locator survey per vendor site: page found or not, widget provider, and one status (`page_list`, `full_feed`, `area_search_only`, `robots_disallowed`, `own_shops_only`, `none`, `unreachable`) | Must | The survey is a table in the output |
| A-04 | 1 | What the pass finds is stored as found, with its URL and time | Must | Raw values unchanged |
| N-01 | 3 | The vendor key and the alias list of section 6 | Must | The spellings measured in section 6 merge into one vendor each; "Z Supply Lounge" merges only when listed as an alias |
| N-02 | 3 | Own-label vendors and placeholders give no pair | Must | A store's own name is not counted among its vendors |
| N-03 | 3 | A declared list is split into rows with the fields it holds | Must | A page list and a feed give the same columns |
| N-04 | 3 | Every cleaned value keeps the raw value beside it | Must | No raw table of a run is changed |
| N-05 | 3 | What a rule could not read goes to the review list | Should | A locator page that could not be split into rows is listed, not dropped |
| E-01 | 4 | One record per vendor and per store, with the keys of section 7 | Must | A store read in two runs is one store |
| E-02 | 4 | Stores match by domain, then phone, then name with place; same name and state only goes to review | Must | "The Hive" in two cities stays two stores |
| E-03 | 4 | A vendor whose site was read is linked to that store record | Must | Eribe the vendor and eribe.com the site are one vendor node with a site |
| E-04 | 4 | Every match records its method, and unsure ones are listed for review | Must | `match_method` on every match |
| R-01 | 5 | One row per vendor, store and source, with `declared` or `observed` | Must | A pair seen by both routes has two rows |
| R-02 | 5 | Route 1 is used first and route 2 fills in; coverage is stated per vendor | Must | A vendor known only from catalogues is marked `sample` |
| R-03 | 5 | Wooden Ships is a vendor in the graph, from its stockist list and from catalogues that name it | Must | The 500 stockists and the 6 stores seen selling Wooden Ships in the measured run are its pairs |
| R-04 | 5 | Overlap between vendors, and with Wooden Ships, with the number of stores behind it | Must | Reported only above the evidence floor |
| R-05 | 5 | The parameters of section 8.1, each in its own column | Must | A rank can be recomputed by hand from them |
| R-06 | 5 | Built over more than one run | Should | The newest reading of a store is used |
| I-01 | 6 | Stores to approach, vendors closest to us, regions, risk in our accounts, review list | Must | In the workbook and on the Retailer map page |
| I-02 | 6 | Every row names its source, evidence and coverage | Must | Columns exist on every output |
| I-03 | 6 | A not-read store is reported as unknown, apart from stores read and found not relevant | Must | The three counts are stated |

## 10. Out of scope

| Item | Reason |
|---|---|
| Reading a locator whose data host disallows crawlers | [ADR 0002](../decisions/0002-camoufox-for-rendering-only.md). Rendering the page in the browser to capture the same feed is the same request and is also out. Such a vendor is covered by route 2 |
| Rebuilding a list by searching area after area where the vendor turned "list all" off | The vendor chose not to publish the list as a whole. Pin coordinates may still be counted per state |
| A locator the vendor has removed from its site | The list is no longer published |
| Wholesale marketplaces (Faire, JOOR, NuORDER) | They need a login |
| Opening Instagram or Facebook profiles | [ADR 0008](../decisions/0008-store-discovery-paid-search.md) |
| Currency conversion | Prices stay as written; price comparison uses US-dollar prices only |
| Customer and order data in this repository | Accounts and sales reach the analysis as files in `data/inputs/`, which is never committed |
| Fuzzy merging of vendor names, text similarity, a graph database | Not needed for the questions asked ([sections 6 to 8](#6-layer-3-preprocessing-and-normalisation)); added only on a measured need |
| Reachout | Later, as in the main PRD |

## 11. Nonfunctional requirements

| Aspect | Requirement |
|---|---|
| **Ethics** | `robots.txt` respected on every host read, public pages only, no login, no bypass |
| **Raw stays raw** | Layer 1 keeps values as found. Cleaning, matching and scoring live in layers 3 to 5 |
| **Privacy** | Stockists, accounts and sales stay in `data/`, which is never committed |
| **Traceability** | Every pair, match and score names its source and evidence |
| **Cost** | No paid request in layers 3 to 6. The locator pass keeps the run's politeness and cache |
| **Testing** | No network in tests: recorded locator pages and feeds, and a recorded slice of a run |
| **Structure** | The pipeline and the analysis do not import the API or the interface |

## 12. Release plan

One layer at a time, each ending with a person reading its output.

| Stage | Layer | Content | Exit gate |
|---|---|---|---|
| **R0. Inputs** | — | `brands.csv` with the vendors to watch and their aliases, `accounts.csv`, `price_points.csv` | The files exist; a missing one is named and its part of the result left out |
| **R1. Locator pass** | 1 | A-01 to A-04 | The survey table for one run is read by a person; no request breaks `robots.txt` |
| **R2. Clean** | 3 | N-01 to N-05 | The vendors of section 6 merge as measured; a person checks 30 vendor names |
| **R3. Match** | 4 | E-01 to E-04 | A person checks 30 matches and the review list |
| **R4. Graph** | 5 | R-01 to R-06 | The four named brands reproduce the counts of section 5.5; Wooden Ships' own pairs are present |
| **R5. Insight** | 6 | I-01 to I-03 | The wholesale team reads the list of stores to approach and says what is missing |

## 13. Success metrics

| Metric | Target | Type |
|---|---|---|
| Requests that break `robots.txt`, on any host | 0 | Hard |
| Pairs without a source and evidence | 0 | Hard |
| Raw values changed by cleaning | 0 | Hard |
| Matches marked as the same store that a person finds wrong, on a checked sample | ≤ 5% | Proposed |
| Vendors merged that a person finds are different vendors, on a checked sample | ≤ 2% | Proposed |
| Stores to approach that the wholesale team accepts as worth contacting, on a checked sample | Set after the first review | Proposed |

## 14. Open questions for this review

| No. | Question | What it affects |
|---|---|---|
| Q-01 | Is section 5.2 the right reading of "a store locator or something related to it"? It counts three pages: a vendor's retailer list, a store's brand list, and a store's own shop locations | Layer 2, A-01 |
| Q-02 | Layer 1 is called done, yet the preferred route needs the locator pass of section 4. Is that addition accepted as part of this phase? | A-01 to A-04, stage R1 |
| Q-03 | A vendor whose locator the bot may not read (Z Supply) is covered by route 2 only, as a sample. Is that acceptable? | R-02 |
| Q-04 | Which vendors does the locator pass cover first: the four named brands, every own-label site already read (44 in the measured run), or every vendor sold in 10 or more stores (113)? | Stage R1 |
| Q-05 | Are the parameters of section 8.1 the ones that should decide who is a competitor? Is any missing? | R-05 |
| Q-06 | Two lists of vendors, those that compete on knitwear and those that mark the right kind of store: is that split right? | I-01 |
| Q-07 | When are `brands.csv`, `accounts.csv` and `price_points.csv` available? Without accounts, "not ours" is measured against the stockist list only | Stage R0 |
| Q-08 | The price range was given as "50–60% of the price of our Shopify products". Does that mean up to 50–60% cheaper or dearer than ours, or 50–60% of our price? | R-05 |
| Q-09 | What is the territory radius, and are regions reported per state or per metro area? | I-01 |
| Q-10 | Are the floors (8 stores and 30 products to rank a vendor) acceptable? | R-04 |

## 15. Glossary

| Term | Meaning |
|---|---|
| Coverage | Whether a vendor's stores come from its full published list or from a sample of catalogues |
| Declared | A pair stated by the vendor or the store on its own site (route 1) |
| Entity resolution | Deciding which records are the same vendor or the same store |
| Locator | A "find a store" page: a list on the page, or a map fed by a third-party service |
| Observed | A pair seen in a store's product catalogue (route 2) |
| Own label | A vendor name that is the store's own name |
| Pair | One vendor sold in one store, with where it was seen |
| Reverse engineering | Working out where a vendor's goods go from what stores and vendors publish |
| Vendor | A brand whose goods are sold in stores |

# Process

The repository has two parts:

| Part | Where | What it does |
|---|---|---|
| **Scrape bot** | `src/scrapebot/`, `web/`, `tests/` | Finds stores, reads their catalogues, writes a run to `data/runs/<run>/` |
| **Process** | `process/` (this folder) | Turns one run into insight: tables, charts and a dashboard, in `data/process/<run>/` |

This folder is a first look at the data for the
[competitive and retailer analysis](../docs/product/prd-competitive-retailer-analysis.md).
**Exploratory, not the final method**: thresholds are proposals, the Wooden Ships profile is a
stand-in, and nothing here is imported by scrapebot. The narration in the notebooks is in
Indonesian; the dashboard is in English.

## The steps

| Step | Stage | What it does | Tables it writes |
|---|---|---|---|
| [01_eda](01_eda.ipynb) | EDA | Looks at one run as it is: stores read, columns filled, vendor spellings, prices, materials, reference files present | none |
| [02_preprocessing_normalization](02_preprocessing_normalization.ipynb) | Preprocessing, normalisation | One key per brand with aliases, own labels marked, the brand and store map, a short store table, US-dollar prices, fibre families | `brand_stores`, `brands_dim`, `stores_clean`, `knit_clean`, `knit_text` |
| [03_processing](03_processing.ipynb) | Processing | Wooden Ships profile, product relevance in four parts, brand relevance from five components, overlap, brands sold together, opportunities, regions, a published retailer list | `product_relevance`, `brands_ranked`, `brand_overlap`, `brand_jaccard`, `brand_pairs`, `opportunities`, `regions`, `locator_match`, `locator_states` |
| [04_insights_visualization](04_insights_visualization.ipynb) | Insight, visualisation | Eight charts, each with what it means for the business, and a printed summary | none |
| [build_dashboard.py](build_dashboard.py) | Dashboard | The Retailer map from the tables of step 03: stores to approach, brands, regions, published lists. As `retailer_map.json` for the web interface and as one HTML file | none |

Each step reads what the one before wrote.

## Setup and running

```bash
uv sync --all-extras --group process               # pandas, matplotlib, scikit-learn, Jupyter kernel
uv run --group process python process/run_all.py   # every step, in order
uv run --group process python process/build_dashboard.py   # the dashboard alone
```

Or open a notebook in VS Code, pick the project's `.venv` as the kernel, and *Run All*.

`make install` runs `uv sync --all-extras`, which removes the process packages again; repeat
the first command after it.

## What it reads

| Input | Where | Needed |
|---|---|---|
| A run that `scrapebot analyze` has read | `data/runs/<run>/` with `analysis/csv/` | Yes. The largest analysed run is used; set `SCRAPEBOT_RUN=<run id>` to choose |
| Wooden Ships stockists | `data/inputs/stockists.json` | Yes, for overlap and territory |
| Brands to watch | `data/inputs/brands.csv` | No. Without it the four brands of the proposal are used |
| Wooden Ships prices | `data/inputs/price_points.csv` | No. Without it prices come from the Wooden Ships products seen in stockists' catalogues (12 in the measured run) |
| A brand's published retailer list | `data/locators/<brand>.json`, in Stockist.co's format | No. Section 8 of notebook 03 is skipped without it |

## What it writes

Everything for one run is in one folder, inside `data/`, which is never committed:

```text
data/process/<run>/
  tables/              the tables of steps 02 and 03, as Parquet
  executed/            the four notebooks with their outputs and charts
  retailer_map.json    what the web interface shows on its Retailer map page
  dashboard.html       the same page as one file; open it in a browser
```

The notebooks in this folder are stored **without outputs**, because outputs show store,
stockist and contact data. Clear the outputs before committing a notebook you ran in the
editor.

## The dashboard

The Retailer map is a page of the web interface, under **Process** in the menu:

```bash
uv run --group process python process/run_all.py   # writes retailer_map.json
make serve                                         # then open Process > Retailer map
```

The interface shows the newest run that has a `retailer_map.json`. The API serves that file
as it is (`GET /api/retailer-map`), and checks it against `RetailerMapOut` in
`src/scrapebot/api/schemas.py`: change `build_dashboard.py` and that model together, then
run `make api-types`.

`dashboard.html` is the same page as one file, to send to someone who does not run the
interface. It embeds the interface's stylesheet (`web/src/styles.css`) and the data of one
run, so it works offline. Its parts are in `dashboard/`: `template.html`, `page.css`,
`page.js`, and `icons.json` (the menu icons, copied from lucide, ISC licence). It is a second
copy of the page: a change to `web/src/pages/RetailerMap.tsx` is not picked up by it.

`nbutil.py` holds the shared paths, loaders and chart style, and reuses scrapebot's own name
normalisation and distance code.

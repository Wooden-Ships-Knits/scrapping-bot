"""Build the Retailer map from the tables the notebooks wrote.

    uv run --group process python process/build_dashboard.py

Writes two files to data/process/<run>/, which is never committed:

- retailer_map.json: what the web interface shows on its Retailer map page. Its shape is
  `RetailerMapOut` in src/scrapebot/api/schemas.py; change both together.
- dashboard.html: the same page as one file that opens without a server, to send to someone.
"""

import json
from pathlib import Path

import nbutil as nb
import pandas as pd

from scrapebot.analysis.build import Options

HERE = Path(__file__).resolve().parent
PARTS = HERE / "dashboard"

# The notebooks label rows in Indonesian; the page is in English.
TERRITORY = {
    "wilayah kosong": "open",
    "ada stockist dalam radius": "near",
    "lokasi tidak diketahui": "unknown",
}
KIND = {"pesaing knitwear": "rival", "brand penanda": "marker"}
GROUP = {
    "toko yang sama": "same",
    "perlu diperiksa": "check",
    "bukan kita, ada stockist dalam 15 mil": "near",
    "bukan kita, wilayah kosong": "open",
}
DISPLAY = {"whitewarren": "White + Warren"}
# Measured on 2026-10-12 (PRD, section 3). No table holds this yet.
SURVEY = [
    ("Z Supply", "Storemapper", "robots", None),
    ("Rails", "Own page", "own", None),
    ("White + Warren", "Stockist.co (page removed)", "none", None),
    ("Lilla P", "Unknown", "none", None),
    ("Heartloom", "Stockist.co", "full", 415),
    ("Habitat", "Stockist.co", "area", 1151),
    ("Joseph Ribkoff", "Stockist.co", "area", None),
    ("Liverpool", "Storemapper", "robots", None),
]


def clean(value):
    """NaN and numpy scalars to plain JSON values."""
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, float) and value != value:
        return None
    return value


def records(frame: pd.DataFrame, columns: list[str]) -> list[dict]:
    return [{c: clean(row[c]) for c in columns} for _, row in frame.iterrows()]


def page_data() -> dict:
    stores = nb.load("stores_clean")
    ranked = nb.load("brands_ranked")
    overlap = nb.load("brand_overlap")
    pairs = nb.load("brand_stores")
    opps = nb.load("opportunities")

    watched = ranked[ranked.watched].sort_values("stores", ascending=False)
    names = dict(zip(ranked.brand_key, ranked.brand, strict=True)) | DISPLAY
    watched_pairs = pairs[pairs.brand_key.isin(watched.brand_key)]
    carried = watched_pairs.groupby("domain").brand_key.apply(list).to_dict()
    order = {key: i for i, key in enumerate(watched.brand_key)}
    watched_names = set(ranked[ranked.watched].brand)

    opportunities = []
    for _, row in opps.iterrows():
        opportunities.append(
            {
                "domain": row.domain,
                "name": clean(row.store_name),
                "city": clean(row.city),
                "state": clean(row.state),
                "score": clean(row.score),
                "knit": clean(row.knit_products),
                "price": clean(row.knit_price_median),
                "currency": clean(row.currency),
                "miles": clean(row.nearest_stockist_miles),
                "territory": TERRITORY[row.territory],
                "email": bool(row.has_email),
                "watched": sorted(carried.get(row.domain, []), key=order.__getitem__),
                "relevant": [b for b in row.relevant_brands.tolist() if b not in watched_names],
            }
        )

    locator = published_list()
    full_lists = {nb.compact(locator["brand"])} if locator else set()
    brands = ranked.merge(overlap.drop(columns=["brand", "stores"]), on="brand_key", how="left")
    brand_rows = []
    for _, row in brands.sort_values("rank_score", ascending=False).iterrows():
        brand_rows.append(
            {
                "key": row.brand_key,
                "brand": names[row.brand_key],
                "kind": KIND[row.kind],
                "watched": bool(row.watched),
                "stores": clean(row.stores),
                "shared": clean(row.shared),
                "not_ours": clean(row.not_ours),
                "open": clean(row.open_territory),
                "knit_share": clean(row.knit_share),
                "price": clean(row.price_position),
                "rank": clean(row.rank_score),
                "full": row.brand_key in full_lists,
            }
        )

    with_watched = opps[opps.watched_brands > 0]
    regions = nb.load("regions").sort_values(["opportunities", "open_territory"], ascending=False)
    return {
        "run_id": nb.run_id(),
        "stores": len(stores),
        "readable": int(stores.readable.sum()),
        "radius_miles": Options().territory_miles,
        "watched": [
            {"key": key, "brand": names[key], "stores": int(n)}
            for key, n in zip(watched.brand_key, watched.stores, strict=True)
        ],
        "watched_stores": int(watched_pairs.domain.nunique()),
        "watched_customers": int(
            stores[stores.domain.isin(watched_pairs.domain)].is_customer.sum()
        ),
        "watched_not_ours": len(with_watched),
        "watched_email": int(with_watched.has_email.sum()),
        "watched_territory": {
            TERRITORY[k]: int(v) for k, v in with_watched.territory.value_counts().items()
        },
        "located": int(opps.state.notna().sum()),
        "opportunities": opportunities,
        "brands": brand_rows,
        "regions": records(regions, ["state", "opportunities", "open_territory", "stockists"]),
        "survey": [
            {"brand": brand, "locator": locator_name, "status": status, "locations": locations}
            for brand, locator_name, status, locations in SURVEY
        ],
        "locator": locator,
    }


def published_list() -> dict | None:
    """The one brand list notebook 03 matched; None when no list was in data/locators/."""
    try:
        matched = nb.load("locator_match")
        by_state = nb.load("locator_states")
    except FileNotFoundError:
        return None
    return {
        "brand": str(matched.brand.iloc[0]),
        "total": len(matched),
        "groups": {GROUP[k]: int(v) for k, v in matched.group.value_counts().items()},
        "states": records(
            by_state.sort_values("gap", ascending=False),
            ["state", "brand_retailers", "stockists", "gap"],
        ),
    }


def main() -> None:
    data = page_data()
    as_json = nb.process_dir() / "retailer_map.json"
    as_json.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    print(f"page data: {as_json.relative_to(nb.ROOT)}")
    html = (PARTS / "template.html").read_text()
    fills = {
        "/*APP_CSS*/": (nb.ROOT / "web" / "src" / "styles.css").read_text(),
        "/*PAGE_CSS*/": (PARTS / "page.css").read_text(),
        "/*PAGE_JS*/": (PARTS / "page.js").read_text(),
        "/*ICONS*/": (PARTS / "icons.json").read_text(),
        "/*DATA*/": json.dumps(data, ensure_ascii=False).replace("</", "<\\/"),
    }
    for mark, text in fills.items():
        html = html.replace(mark, text)
    out = nb.process_dir() / "dashboard.html"
    out.write_text(html)
    print(f"dashboard: {out.relative_to(nb.ROOT)}")


if __name__ == "__main__":
    main()

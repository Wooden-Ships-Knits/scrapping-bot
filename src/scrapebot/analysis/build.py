"""Turn a finished run and the operator's files into the wholesale analysis.

Segments, in the order they are decided:

    not_read            the run could not read the store (blocked, error, no products...)
    existing_customer   a stockist or an account already, or it sells Wooden Ships
    not_relevant        not a shop (news, directories...), or a marketplace or resale shop
    not_a_fit           a chain or department store
    competitor          sells its own label of knitwear (or is a brand listed as competitor)
    b2b_partner         a hotel, resort or club shop, gift or museum shop, outfitter,
                        promotional or corporate supplier, showroom or agency
    retail_partner      a boutique that resells other brands

Retail and B2B partners get a score from 0 to 100, with every point explained in
`reasons`: knitwear on offer, peer brands carried, price fit, no stockist nearby, how many
brands, a way to reach them, a wholesale page, recent new products.
"""

import html
import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ..store import JsonlRows
from .attributes import attributes
from .business import B2B_TYPES, business_type
from .inputs import Customer, Inputs, compact, core_name, digits, domain_core
from .location import Geocoder, Location, from_identity, from_meta, from_pages, miles
from .tables import BrandRow, CompetitorRow, KnitAnalysisRow, StoreAnalysisRow

WOODEN_SHIPS = "woodenships"
NAME_COLUMNS = ("name", "store_name", "Account name", "title", "company")
PAGE_KINDS = ("home", "about", "contact", "stockist")
FIT_BELOW, FIT_ABOVE = 0.75, 1.35  # store knit median / Wooden Ships retail
RECENT_DAYS = 90
COMPETITOR_MIN_KNIT = 5  # an own label with fewer knitwear products is not a rival
BRANDS_KEPT = 15


@dataclass
class Options:
    territory_miles: float = 15.0  # a stockist closer than this is a territory conflict
    geocoder: Geocoder | None = None  # None: no points, so no distances
    today: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class Analysis:
    stores: list[StoreAnalysisRow]
    knit: list[KnitAnalysisRow]
    competitors: list[CompetitorRow]
    brands: list[BrandRow]
    notes: list[str]


@dataclass
class _Store:
    """What one store adds up to while the tables are streamed."""

    products: int = 0
    vendors: Counter[str] = field(default_factory=Counter)
    spelling: dict[str, str] = field(default_factory=dict)
    knit_vendors: Counter[str] = field(default_factory=Counter)
    knit_prices: list[float] = field(default_factory=list)
    knit_kinds: Counter[str] = field(default_factory=Counter)
    categories: Counter[str] = field(default_factory=Counter)
    materials: Counter[str] = field(default_factory=Counter)
    genders: Counter[str] = field(default_factory=Counter)
    sale: list[bool] = field(default_factory=list)
    stock: list[bool] = field(default_factory=list)
    newest: str = ""
    contacts: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    pages: list[tuple[str, str]] = field(default_factory=list)
    wholesale: list[str] = field(default_factory=list)


def _rows(root: Path, table: str) -> Iterable[dict[str, Any]]:
    path = root / "tables" / f"{table}.jsonl"
    return JsonlRows(path) if path.exists() else []


def _quartiles(values: list[float]) -> tuple[float | None, float | None, float | None]:
    if not values:
        return None, None, None
    if len(values) < 4:
        mid = statistics.median(values)
        return min(values), mid, max(values)
    low, mid, high = statistics.quantiles(values, n=4)
    return round(low, 2), round(mid, 2), round(high, 2)


def analyze(root: Path, inputs: Inputs, options: Options | None = None) -> Analysis:
    options = options or Options()
    stores = {s["domain"]: s for s in _rows(root, "stores")}
    readable = {d for d, s in stores.items() if s["status"] == "ok"}
    names, metas = _input_names(_rows(root, "inputs"))
    acc: dict[str, _Store] = {d: _Store() for d in stores}
    knit_rows: list[dict[str, Any]] = []

    for p in _rows(root, "products"):
        if p["domain"] not in readable:
            continue
        s = acc[p["domain"]]
        s.products += 1
        vendor = (p.get("vendor") or "").strip()
        if vendor:
            s.vendors[compact(vendor)] += 1
            s.spelling.setdefault(compact(vendor), vendor)
        a = attributes(p)
        if a.on_sale is not None:
            s.sale.append(a.on_sale)
        if a.in_stock is not None:
            s.stock.append(a.in_stock)
        s.newest = max(s.newest, a.launched)
        if not p.get("knit_kind"):
            continue
        s.knit_kinds[p["knit_kind"]] += 1
        if vendor:
            s.knit_vendors[compact(vendor)] += 1
        if a.price is not None and a.price > 0:
            s.knit_prices.append(a.price)
        if a.category:
            s.categories[a.category] += 1
        if a.main_material:
            s.materials[a.main_material] += 1
        if a.gender:
            s.genders[a.gender] += 1
        knit_rows.append({**p, "_a": a})

    for c in _rows(root, "contacts"):
        if c["domain"] in acc and c["value"] not in acc[c["domain"]].contacts[c["type"]]:
            acc[c["domain"]].contacts[c["type"]].append(c["value"])
    for page in _rows(root, "pages"):
        if page["domain"] not in readable or page.get("error"):
            continue
        kind = page.get("page_kind", "")
        if kind in PAGE_KINDS:
            acc[page["domain"]].pages.append((kind, page.get("text") or ""))
        if kind in ("wholesale", "stockist"):
            acc[page["domain"]].wholesale.append(page["url"])

    stockists = [c for c in inputs.stockists if c.lat is not None and c.lng is not None]
    rows: list[StoreAnalysisRow] = []
    for domain, s in stores.items():
        rows.append(_store_row(domain, s, acc[domain], names, metas, inputs, stockists, options))
    segment_of = {r.domain: r.segment for r in rows}

    knit = [_knit_row(p, segment_of.get(p["domain"], "")) for p in knit_rows]
    competitors = [_competitor_row(r, acc[r.domain]) for r in rows if r.segment == "competitor"]
    brands = _brand_rows(acc, inputs)
    return Analysis(rows, knit, competitors, brands, _notes(inputs, options))


def _input_names(
    inputs: Iterable[dict[str, Any]],
) -> tuple[dict[int, str], dict[int, dict[str, Any]]]:
    names, metas = {}, {}
    for row in inputs:
        meta = row.get("meta") or {}
        metas[row["input_id"]] = meta
        name = next((str(meta[c]).strip() for c in NAME_COLUMNS if meta.get(c)), "")
        if name:
            names[row["input_id"]] = name
    return names, metas


def _store_row(
    domain: str,
    s: dict[str, Any],
    a: _Store,
    names: dict[int, str],
    metas: dict[int, dict[str, Any]],
    inputs: Inputs,
    stockists: list[Customer],
    options: Options,
) -> StoreAnalysisRow:
    ids = s.get("input_ids", [])
    identity = s.get("identity") or {}  # runs before 2026-10-10 have none
    orgs = identity.get("organizations") or []
    name = next((names[i] for i in ids if names.get(i)), "")
    name = name or next((o["name"] for o in orgs if o.get("name")), "")
    name = html.unescape(name or identity.get("site_name", ""))  # "Hill&#39;s" in markup
    location = next((loc for i in ids if (loc := from_meta(metas.get(i, {})))), None)
    location = location or from_identity(identity) or from_pages(a.pages) or Location()
    phones = [*a.contacts.get("phone", []), *(o["telephone"] for o in orgs if o.get("telephone"))]
    if options.geocoder and location.known and location.lat is None:
        point = options.geocoder.point(location)
        if point:
            location.lat, location.lng = point

    text = " ".join(t for k, t in a.pages if k in ("home", "about"))
    kind = business_type(domain, name, text, s.get("store_type", ""), s["status"],
                         s.get("product_count", 0))  # fmt: skip
    customer, method = _match(domain, name, location, phones, inputs)
    carries_ws = WOODEN_SHIPS in a.vendors
    nearest, nearest_mi, nearby = _territory(location, stockists, customer, options)
    low, mid, high = _quartiles(a.knit_prices)
    knit_total = sum(a.knit_kinds.values())
    fit, ratio = _price_fit(mid, s.get("currency", ""), a.categories, inputs)
    peers = sorted(v for v in a.vendors if v in inputs.peer_brands)
    rivals = sorted(v for v in a.vendors if v in inputs.competitor_brands)

    row = StoreAnalysisRow(
        run_id=s["run_id"],
        domain=domain,
        url=s.get("url", ""),
        store_name=name,
        status=s["status"],
        segment="unknown",
        business_type=kind.kind,
        business_reason=kind.reason,
        b2b_hints=list(kind.hints),
        store_type=s.get("store_type", ""),
        relationship=(
            f"existing_{customer.kind}"
            if customer
            else ("carries_wooden_ships" if carries_ws else "")
        ),
        matched_customer=customer.name if customer else "",
        match_method=method,
        rep=customer.rep if customer else "",
        territory=customer.territory if customer else "",
        account_status=customer.status if customer else "",
        address=location.address,
        city=location.city,
        state=location.state,
        postal=location.postal,
        country=location.country,
        location_source=location.source,
        lat=location.lat,
        lng=location.lng,
        nearest_stockist=nearest,
        nearest_stockist_miles=nearest_mi,
        stockists_nearby=nearby,
        platform=s.get("platform", ""),
        currency=s.get("currency", ""),
        product_count=a.products,
        knit_products=knit_total,
        knit_garments=a.knit_kinds["garment"],
        knit_accessories=a.knit_kinds["accessory"],
        knit_share=round(knit_total / a.products, 3) if a.products else None,
        knit_price_low=low,
        knit_price_median=mid,
        knit_price_high=high,
        price_fit=fit,
        price_ratio=ratio,
        brand_count=len(a.vendors),
        brands=[a.spelling[v] for v, _ in a.vendors.most_common(BRANDS_KEPT)],
        peer_brands=[a.spelling[v] for v in peers],
        competitor_brands=[a.spelling[v] for v in rivals],
        carries_wooden_ships=carries_ws,
        on_sale_share=round(sum(a.sale) / len(a.sale), 3) if a.sale else None,
        in_stock_share=round(sum(a.stock) / len(a.stock), 3) if a.stock else None,
        newest_launch=a.newest,
        main_materials=[m for m, _ in a.materials.most_common(3)],
        genders=[g for g, _ in a.genders.most_common()],
        emails=a.contacts.get("email", [])[:5],
        phones=a.contacts.get("phone", [])[:5],
        instagram=a.contacts.get("instagram", [])[:3],
        facebook=a.contacts.get("facebook", [])[:3],
        wholesale_pages=a.wholesale[:5],
    )
    _segment(row, inputs, options)
    return row


def _match(
    domain: str, name: str, location: Location, phones: list[str], inputs: Inputs
) -> tuple[Customer | None, str]:
    """The customer this store is, by domain, then phone, then name in the same place."""
    for c in inputs.customers:
        if c.domain and c.domain == domain:
            return c, "domain"
    wanted = {digits(p) for p in phones if len(digits(p)) == 10}
    for c in inputs.customers:
        if c.phone and c.phone in wanted:
            return c, "phone"
    label = core_name(name) if name else domain_core(domain)
    if len(label) < 4:
        return None, ""
    for c in inputs.customers:
        other = core_name(c.name)
        if len(other) < 4:
            continue
        conflict = (location.state and c.state and location.state != c.state) or (
            location.postal and c.postal and location.postal[:5] != c.postal[:5]
        )
        if conflict:
            continue
        if other == label:
            return c, "name"
        # "martins" inside "aldomartins" is a match only where the state is known to agree.
        overlap = len(other) >= 6 and (other in label or label in other)
        if overlap and location.state and location.state == c.state:
            return c, "name+state"
    return None, ""


def _territory(
    location: Location, stockists: list[Customer], customer: Customer | None, options: Options
) -> tuple[str, float | None, int | None]:
    if location.lat is None or location.lng is None or not stockists:
        return "", None, None
    lat, lng = location.lat, location.lng
    distances = sorted(
        (miles(lat, lng, c.lat, c.lng), c.name)  # type: ignore[arg-type]
        for c in stockists
        if c is not customer
    )
    nearby = sum(1 for d, _ in distances if d <= options.territory_miles)
    return distances[0][1], round(distances[0][0], 1), nearby


def _price_fit(
    median: float | None, currency: str, categories: Counter[str], inputs: Inputs
) -> tuple[str, float | None]:
    """Compare the store's knitwear median with Wooden Ships' retail price. Only in US
    dollars: prices are never converted here (raw means raw)."""
    if median is None or not inputs.prices or (currency and currency != "USD"):
        return "", None
    main = categories.most_common(1)[0][0] if categories else "sweater"
    retail = (inputs.prices.get(main) or inputs.prices.get("sweater") or (None, None))[1]
    if not retail:
        retail = next((r for _, r in inputs.prices.values() if r), None)
    if not retail:
        return "", None
    ratio = round(median / retail, 2)
    return ("below" if ratio < FIT_BELOW else "above" if ratio > FIT_ABOVE else "fits"), ratio


def _segment(row: StoreAnalysisRow, inputs: Inputs, options: Options) -> None:
    reasons: list[str] = []
    kind = row.business_type
    if row.status != "ok":
        row.segment, row.reasons = "not_read", [f"run status {row.status}"]
        return
    if row.relationship:
        how = f" ({row.match_method})" if row.match_method else ""
        row.segment, row.reasons = "existing_customer", [f"{row.relationship}{how}"]
        return
    if kind in ("non_retail", "marketplace_resale"):
        row.segment, row.reasons = "not_relevant", [f"{kind}: {row.business_reason}"]
        return
    if kind == "department_store":
        row.segment, row.reasons = "not_a_fit", [row.business_reason]
        return
    own_name = compact(row.domain.split(".")[0])
    if kind == "own_label" or own_name in inputs.competitor_brands:
        if row.knit_products >= COMPETITOR_MIN_KNIT:
            row.segment = "competitor"
            row.reasons = [f"own label with {row.knit_products} knitwear products"]
        else:
            row.segment = "not_relevant"
            row.reasons = [f"own label with {row.knit_products} knitwear products"]
        return

    row.segment = "b2b_partner" if kind in B2B_TYPES else "retail_partner"
    reasons.append(
        f"{kind}: {row.business_reason}" if kind in B2B_TYPES else "resells other brands"
    )
    score = 0
    knit_points = round(min(row.knit_products, 50) / 50 * 25)
    score += knit_points
    reasons.append(f"+{knit_points} knitwear ({row.knit_products} products)")
    if row.peer_brands:
        peer_points = min(10 * len(row.peer_brands), 25)
        score += peer_points
        reasons.append(f"+{peer_points} carries peer brands: {', '.join(row.peer_brands[:5])}")
    if row.price_fit:
        price_points = {"fits": 20, "above": 15, "below": 0}[row.price_fit]
        score += price_points
        reasons.append(f"+{price_points} price {row.price_fit} (x{row.price_ratio})")
    if row.nearest_stockist_miles is not None:
        if row.nearest_stockist_miles <= options.territory_miles:
            score -= 20
            reasons.append(
                f"-20 stockist {row.nearest_stockist} {row.nearest_stockist_miles} mi away"
            )
        else:
            score += 10
            reasons.append(f"+10 no stockist within {options.territory_miles:.0f} mi")
    if row.brand_count >= 10:
        score += 10
        reasons.append(f"+10 {row.brand_count} brands")
    elif row.brand_count >= 3:
        score += 5
        reasons.append(f"+5 {row.brand_count} brands")
    if row.emails:
        score += 5
        reasons.append("+5 email found")
    if row.instagram:
        score += 3
        reasons.append("+3 Instagram found")
    if row.wholesale_pages:
        score += 5
        reasons.append("+5 wholesale or stockist page")
    if row.newest_launch:
        try:
            launched = datetime.fromisoformat(row.newest_launch).replace(tzinfo=UTC)
            if options.today - launched <= timedelta(days=RECENT_DAYS):
                score += 5
                reasons.append(f"+5 new products since {row.newest_launch}")
        except ValueError:
            pass
    row.score = max(0, min(100, score))
    row.reasons = reasons


def _knit_row(p: dict[str, Any], segment: str) -> KnitAnalysisRow:
    a = p["_a"]
    return KnitAnalysisRow(
        run_id=p["run_id"],
        domain=p["domain"],
        segment=segment,
        title=p["title"],
        vendor=p.get("vendor", ""),
        knit_kind=p["knit_kind"],
        category=a.category,
        main_material=a.main_material,
        materials=a.materials,
        gender=a.gender,
        price=a.price,
        currency=p.get("currency", ""),
        compare_at=a.compare_at,
        on_sale=a.on_sale,
        in_stock=a.in_stock,
        launched=a.launched,
        product_type=p.get("product_type", ""),
        url=p.get("url", ""),
    )


def _competitor_row(r: StoreAnalysisRow, a: _Store) -> CompetitorRow:
    label = a.spelling[a.knit_vendors.most_common(1)[0][0]] if a.knit_vendors else ""
    return CompetitorRow(
        run_id=r.run_id,
        domain=r.domain,
        store_name=r.store_name,
        label=label,
        city=r.city,
        state=r.state,
        knit_products=r.knit_products,
        knit_price_low=r.knit_price_low,
        knit_price_median=r.knit_price_median,
        knit_price_high=r.knit_price_high,
        currency=r.currency,
        price_ratio=r.price_ratio,
        main_materials=r.main_materials,
        categories=[c for c, _ in a.categories.most_common(5)],
        on_sale_share=r.on_sale_share,
        newest_launch=r.newest_launch,
        url=r.url,
    )


def _brand_rows(acc: dict[str, _Store], inputs: Inputs) -> list[BrandRow]:
    stores: dict[str, list[str]] = defaultdict(list)
    products: Counter[str] = Counter()
    knit: Counter[str] = Counter()
    spelling: dict[str, str] = {}
    for domain, s in acc.items():
        for vendor, n in s.vendors.items():
            stores[vendor].append(domain)
            products[vendor] += n
            knit[vendor] += s.knit_vendors[vendor]
            spelling.setdefault(vendor, s.spelling[vendor])

    def relation(vendor: str) -> str:
        if vendor == WOODEN_SHIPS:
            return "wooden_ships"
        if vendor in inputs.peer_brands:
            return "peer"
        return "competitor" if vendor in inputs.competitor_brands else ""

    rows = [
        BrandRow(
            brand=spelling[v],
            relation=relation(v),
            stores=len(domains),
            products=products[v],
            knit_products=knit[v],
            store_domains=sorted(domains)[:25],
        )
        for v, domains in stores.items()
    ]
    return sorted(rows, key=lambda r: (r.relation == "", -r.stores, -r.knit_products))


def _notes(inputs: Inputs, options: Options) -> list[str]:
    notes = [f"{what}: {where}" for what, where in inputs.sources.items()]
    missing = {
        "stockists": "no territory distances, and existing stockists are not recognised",
        "accounts": "existing accounts are not recognised (only stockists and the vendor)",
        "brands": "no peer or competitor brands: those score points are left out",
        "prices": "no price fit: those score points are left out",
    }
    notes += [
        f"MISSING {what}: {why}" for what, why in missing.items() if what not in inputs.sources
    ]
    if options.geocoder is None:
        notes.append("Geocoding off: no distances to stockists.")
    return notes

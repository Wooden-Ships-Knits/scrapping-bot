"""The operator's own files: who already sells Wooden Ships, which brands matter, and
Wooden Ships' prices. They hold customer data, so they live in data/inputs/ (gitignored)
and are only ever read.

    stockists   data/inputs/stockists.json or .csv   the store locator's list
    accounts    data/inputs/accounts.csv             a Salesforce account export
    brands      data/inputs/brands.csv               brand,relation (peer | competitor)
    prices      data/inputs/price_points.csv         category,wholesale_usd,retail_usd

Column names are matched loosely ("Billing City", "city", "City" all work), so an export
can be used as it comes.
"""

import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..discover.geo import normalize_postal, state_code
from ..inputs.resolve import canonical_domain

DEFAULT_DIR = Path("data/inputs")
# A "website" that is a profile or a listing says nothing about the store's own domain.
NOT_A_SITE = frozenset(
    {"facebook.com", "instagram.com", "linktr.ee", "yelp.com", "google.com", "goo.gl",
     "tiktok.com", "pinterest.com", "etsy.com", "squareup.com", "square.site", "wixsite.com",
     "mapquest.com", "yellowpages.com", "yp.com", "bing.com", "apple.com", "foursquare.com",
     "tripadvisor.com", "nextdoor.com", "bbb.org", "manta.com", "chamberofcommerce.com"}
)  # fmt: skip


def site_domain(website: str) -> str:
    domain = canonical_domain(website) if website else ""
    return "" if domain in NOT_A_SITE else domain


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")


def _rows(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        rows = data.get("stores", data) if isinstance(data, dict) else data
    else:
        with path.open(newline="", encoding="utf-8-sig") as fh:
            rows = list(csv.DictReader(fh))
    return [{_key(k): v for k, v in r.items()} for r in rows if isinstance(r, dict)]


def _pick(row: dict[str, Any], *names: str) -> str:
    return next((str(row[n]).strip() for n in names if str(row.get(n) or "").strip()), "")


def _number(value: str) -> float | None:
    try:
        return float(re.sub(r"[^0-9.\-]", "", value)) if value else None
    except ValueError:
        return None


def digits(phone: str) -> str:
    """The last ten digits of a phone number: enough to compare US and Canadian numbers."""
    return re.sub(r"\D", "", phone)[-10:]


@dataclass
class Customer:
    """A stockist or an account: someone who already buys Wooden Ships."""

    kind: str  # stockist | account
    name: str
    domain: str = ""
    phone: str = ""
    city: str = ""
    state: str = ""
    postal: str = ""
    lat: float | None = None
    lng: float | None = None
    rep: str = ""  # accounts: the owner in Salesforce
    territory: str = ""
    status: str = ""  # accounts: type or status


@dataclass
class Inputs:
    customers: list[Customer] = field(default_factory=list)
    peer_brands: set[str] = field(default_factory=set)  # compact names
    competitor_brands: set[str] = field(default_factory=set)
    prices: dict[str, tuple[float | None, float | None]] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)  # what was loaded from where

    @property
    def stockists(self) -> list[Customer]:
        return [c for c in self.customers if c.kind == "stockist"]


def compact(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


# Words a store adds around its name: "The Tango Boutique" and "shoptango.com" are "tango".
STORE_WORDS = frozenset(
    {"the", "shop", "shoppe", "boutique", "boutiques", "store", "stores", "clothing", "co",
     "company", "collection", "apparel", "inc", "llc", "ltd", "online", "and"}
)  # fmt: skip


def core_name(name: str) -> str:
    """A name without the words stores add around it, compacted."""
    words = re.findall(r"[a-z0-9]+", name.lower())
    core = "".join(w for w in words if w not in STORE_WORDS)
    return core or compact(name)


def domain_core(domain: str) -> str:
    """The name in a domain, without "shop", "boutique" and the like around it."""
    label = compact(domain.split(".")[0])
    for word in sorted(STORE_WORDS, key=len, reverse=True):
        if len(word) > 2 and label.startswith(word) and len(label) > len(word) + 3:
            label = label[len(word) :]
        if len(word) > 2 and label.endswith(word) and len(label) > len(word) + 3:
            label = label[: -len(word)]
    return label


def load_stockists(path: Path) -> list[Customer]:
    out = []
    for r in _rows(path):
        out.append(
            Customer(
                kind="stockist",
                name=_pick(r, "name", "store_name", "location_name"),
                domain=site_domain(_pick(r, "website", "url", "web")),
                phone=digits(_pick(r, "phone", "telephone")),
                city=_pick(r, "city"),
                state=state_code(_pick(r, "prov_state", "state", "province")),
                postal=normalize_postal(_pick(r, "postal_zip", "zip", "postal_code")),
                lat=_number(_pick(r, "lat", "latitude")),
                lng=_number(_pick(r, "lng", "lon", "longitude")),
            )
        )
    return out


def load_accounts(path: Path) -> list[Customer]:
    out = []
    for r in _rows(path):
        out.append(
            Customer(
                kind="account",
                name=_pick(r, "account_name", "name", "account"),
                domain=site_domain(_pick(r, "website", "account_website", "url")),
                phone=digits(_pick(r, "phone", "account_phone", "billing_phone")),
                city=_pick(r, "billing_city", "city", "shipping_city"),
                state=state_code(_pick(r, "billing_state_province", "billing_state", "state",
                                       "shipping_state_province", "state_province")),
                postal=normalize_postal(_pick(r, "billing_zip_postal_code", "billing_postal_code",
                                              "zip", "zipcode", "postal_code")),
                lat=_number(_pick(r, "billing_latitude", "latitude", "lat")),
                lng=_number(_pick(r, "billing_longitude", "longitude", "lng")),
                rep=_pick(r, "account_owner", "owner", "sales_rep", "rep"),
                territory=_pick(r, "territory", "sales_territory", "region"),
                status=_pick(r, "account_type", "type", "status", "account_status"),
            )
        )  # fmt: skip
    return out


def load_brands(path: Path) -> tuple[set[str], set[str]]:
    """(peers, competitors). A file with one name per line counts every name as a peer."""
    peers: set[str] = set()
    competitors: set[str] = set()
    text = path.read_text(encoding="utf-8-sig")
    first = text.splitlines()[0].lower() if text.strip() else ""
    rows = _rows(path) if "brand" in first else [{"brand": line} for line in text.splitlines()]
    for r in rows:
        name = compact(_pick(r, "brand", "name"))
        if not name:
            continue
        relation = _pick(r, "relation", "type", "kind").lower()
        (competitors if relation.startswith("comp") else peers).add(name)
    return peers, competitors


def load_prices(path: Path) -> dict[str, tuple[float | None, float | None]]:
    """category -> (wholesale, retail) in US dollars."""
    out = {}
    for r in _rows(path):
        category = _pick(r, "category", "type", "product_type").lower()
        if category:
            out[category] = (
                _number(_pick(r, "wholesale_usd", "wholesale", "wholesale_price")),
                _number(_pick(r, "retail_usd", "retail", "retail_price", "msrp")),
            )
    return out


def load(
    stockists: Path | None = None,
    accounts: Path | None = None,
    brands: Path | None = None,
    prices: Path | None = None,
    folder: Path = DEFAULT_DIR,
) -> Inputs:
    """Each file given, or found in `folder` under its default name; a missing one is
    left out and the analysis says which columns it could not fill."""

    def found(given: Path | None, *names: str) -> Path | None:
        if given is not None:
            return given
        return next((folder / n for n in names if (folder / n).exists()), None)

    out = Inputs()
    if path := found(stockists, "stockists.json", "stockists.csv"):
        out.customers += load_stockists(path)
        out.sources["stockists"] = str(path)
    if path := found(accounts, "accounts.csv"):
        out.customers += load_accounts(path)
        out.sources["accounts"] = str(path)
    if path := found(brands, "brands.csv", "brands.txt"):
        out.peer_brands, out.competitor_brands = load_brands(path)
        out.sources["brands"] = str(path)
    if path := found(prices, "price_points.csv"):
        out.prices = load_prices(path)
        out.sources["prices"] = str(path)
    return out

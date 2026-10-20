"""Which brands a store sells, from the vendor of each product (ADR 0010).

A multi-brand store (a boutique that resells other labels) is a possible partner; a
store that sells its own label, Nike or a small designer alike, is not. Feeds name a
vendor for most products, so the rule reads them first:

- Vendors that are the store's own name ("Bluenvy Boutique" on bluenvy.ca) are not
  outside brands: boutiques often put their own name on every product, labels do too.
- Placeholders ("Default Vendor", "Gift Card") are ignored.
- Three or more outside brands, none of them nearly all the catalogue, and together
  a real share of it, is a multi-brand store. On the 2026-10-08 run this settled 176
  of 267 readable stores. A label with a few collaborations is not one: lazyoaf.com,
  2026-10-13, had 1,993 of 2,000 products under its own name and 7 under three others.

Anything else is `unknown` and goes to the LLM when one is set (pipeline): one outside
brand can be a boutique's only label or a chain's sub-brand, and an own-name vendor can
be a label or a boutique. The rule never says `own_brand` on its own.
"""

import re
from collections import Counter
from dataclasses import dataclass, field

from ..models import Product

# Share of products that must name a vendor before the vendors are trusted at all.
MIN_VENDOR_SHARE = 0.5
MIN_OUTSIDE_BRANDS = 3
# One outside brand above this share of the branded products makes the store a
# single-brand shop that stocks a few extras, or a chain listing its sub-brands.
MAX_TOP_BRAND_SHARE = 0.9
# Outside brands must carry at least this share of the products that name a real vendor
# (own name included). Measured 2026-10-20 on 249 stores the vendors called multi-brand:
# 7 were below 9% (lazyoaf.com 0.4%, matchmadestores.com 1.3%), the next was at 18%.
MIN_OUTSIDE_SHARE = 0.1
BRANDS_KEPT = 10  # outside brands listed per store, most products first

PLACEHOLDER_VENDORS = frozenset(
    {
        "", "default", "default vendor", "vendor", "unknown", "none", "n a", "na", "other",
        "others", "various", "misc", "miscellaneous", "wholesale", "gift card", "gift cards",
        "giftcard", "e gift card", "shopify", "sample", "test", "my store", "store", "shop",
        "sale", "clearance", "brand", "no brand", "unbranded",
    }
)  # fmt: skip
# Words a store adds to its own name: "The Lyla Shop", "Bluenvy Boutique".
STORE_WORDS = frozenset(
    {
        "the", "boutique", "boutiques", "shop", "shoppe", "store", "stores", "co", "company",
        "clothing", "clothiers", "apparel", "collection", "collections", "collective",
        "designs", "by", "and", "inc", "llc", "ltd", "online", "official",
    }
)  # fmt: skip
MIN_NAME_CHARS = 4  # a shorter own-name match is a coincidence ("co", "jb")


@dataclass(frozen=True)
class BrandMix:
    store_type: str  # multi_brand | unknown
    brands: list[str] = field(default_factory=list)  # outside brands, most products first
    brand_count: int = 0  # distinct outside brands
    reason: str = ""  # why the rule could not decide; "" when it did


def _key(vendor: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", vendor.lower()).strip()


def _compact(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def store_name(domain: str) -> str:
    """The name part of a registrable domain: "bluenvy.ca" -> "bluenvy"."""
    return _compact(domain.split(".", 1)[0])


def is_own_name(vendor_key: str, name: str) -> bool:
    """Whether a vendor is the store's own name, with or without "boutique", "shop"..."""
    if len(name) < MIN_NAME_CHARS:
        return False
    whole = vendor_key.replace(" ", "")
    core = "".join(w for w in vendor_key.split() if w not in STORE_WORDS)
    return name in whole or (len(core) >= MIN_NAME_CHARS and (core in name or name in core))


def brand_mix(domain: str, products: list[Product]) -> BrandMix:
    """Multi-brand when the vendors show it; otherwise unknown, with the reason."""
    if not products:
        return BrandMix("unknown", reason="no products")
    name = store_name(domain)
    named = [p.vendor.strip() for p in products if _key(p.vendor or "")]
    if len(named) < MIN_VENDOR_SHARE * len(products):
        return BrandMix("unknown", reason="few products name a vendor")
    outside: Counter[str] = Counter()
    spelling: dict[str, Counter[str]] = {}
    own = 0
    for vendor in named:
        key = _key(vendor)
        if key in PLACEHOLDER_VENDORS:
            continue
        if is_own_name(key, name):
            own += 1
            continue
        outside[key] += 1
        spelling.setdefault(key, Counter())[vendor] += 1
    brands = [spelling[k].most_common(1)[0][0] for k, _ in outside.most_common(BRANDS_KEPT)]
    if not outside:
        return BrandMix("unknown", reason="vendors are only the store's own name")
    outside_products = sum(outside.values())
    top_share = outside.most_common(1)[0][1] / outside_products
    outside_share = outside_products / (outside_products + own)
    if (
        len(outside) >= MIN_OUTSIDE_BRANDS
        and top_share < MAX_TOP_BRAND_SHARE
        and outside_share >= MIN_OUTSIDE_SHARE
    ):
        return BrandMix("multi_brand", brands, len(outside))
    if outside_share < MIN_OUTSIDE_SHARE:
        reason = "the store's own name is on nearly every product"
    elif top_share >= MAX_TOP_BRAND_SHARE:
        reason = "one brand is nearly the whole catalogue"
    else:
        reason = f"only {len(outside)} outside brand(s)"
    return BrandMix("unknown", brands, len(outside), reason)

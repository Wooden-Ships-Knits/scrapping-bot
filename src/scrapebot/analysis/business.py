"""What kind of business a store is, for telling retail partners from B2B partners.

    boutique              multi-brand apparel shop: the retail partner profile
    own_label             sells its own label: a competitor when it sells knitwear
    department_store      chains and department stores: rarely open to a small brand
    resort_hotel_club     hotel, resort, inn, golf or country club, marina, ski shop
    gift_museum           museum, gallery, gift and souvenir shops
    outdoor_sporting      outfitters, outdoor, ski, running and sporting goods
    promo_corporate       custom, promotional and corporate apparel
    showroom_agency       showrooms, rep groups, distributors, sales agencies
    marketplace_resale    marketplaces, aggregators, resale and consignment
    non_retail            not a shop: news, directories, government, services
    unknown

Read from the domain, the store's name, its home and about text, and what the run already
knows (store type, product count). Rules only, each with its reason: cheap, repeatable,
and easy to correct when a store is filed wrongly.
"""

import re
from dataclasses import dataclass

B2B_TYPES = frozenset(
    {"resort_hotel_club", "gift_museum", "outdoor_sporting", "promo_corporate", "showroom_agency"}
)

CHAINS = (
    "nordstrom", "macys", "dillards", "bloomingdales", "saks", "neiman", "neimanmarcus",
    "anthropologie", "jcrew", "madewell", "bananarepublic", "gap", "gapfactory", "oldnavy",
    "uniqlo", "zara", "hm", "mango", "revolve", "shopbop", "farfetch", "netaporter", "theoutnet",
    "ssense", "llbean", "landsend", "talbots", "chicos", "freepeople", "urbanoutfitters",
    "abercrombie", "holtrenfrew", "thebay", "simons", "walmart", "target", "marshalls",
    "tjmaxx", "kohls", "belk", "vonmaur", "bealls", "dillards", "jcpenney", "lululemon",
    "allsaints", "theory", "ralphlauren", "tommy", "luckybrand", "roots", "reitmans",
    "penningtons", "suzyshier", "laura", "rw-co", "northernreflections", "aritzia",
    "brooksbrothers", "vineyardvines", "lillypulitzer", "tommybahama", "jmclaughlin",
    "stjohnknits", "eileenfisher", "isabelmarant", "thewhitecompany", "mrporter",
)  # fmt: skip
MARKETPLACES = (
    "ebay", "etsy", "poshmark", "mercari", "depop", "thredup", "therealreal", "tise",
    "garmentory", "lyst", "stylight", "shop.app", "editorialist", "trustpilot", "amazon",
    "wolfandbadger", "shoptiques", "renttherunway", "steals", "thingtesting",
)  # fmt: skip
NON_RETAIL_TLDS = (".gov", ".edu", ".mil")


def _rule(*words: str) -> re.Pattern[str]:
    return re.compile(r"\b(" + "|".join(words) + r")\b", re.I)


# Words that file a store by its own name or domain ("Keeneland Shop", "golfclub.com").
# Order matters: first wins.
NAME_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("showroom_agency", _rule(r"showroom", r"rep group", r"agency", r"distributors?")),
    ("promo_corporate", _rule(r"promo(tional)?", r"corporate", r"embroidery", r"screen ?print")),
    ("resort_hotel_club", _rule(r"hotels?", r"resorts?", r"inn", r"lodge", r"golf", r"club",
                                r"marina", r"yacht", r"keeneland", r"racecourse", r"pro ?shop")),
    ("gift_museum", _rule(r"museum", r"gifts?", r"souvenirs?", r"gallery", r"aquarium")),
    ("outdoor_sporting", _rule(r"outfitters?", r"outdoors?", r"ski", r"sports?", r"running",
                               r"surf", r"tackle", r"fly ?shop", r"climbing")),
    ("marketplace_resale", _rule(r"consign(ment|or)?", r"resale", r"thrift", r"exchange",
                                 r"pre-?owned", r"second ?hand", r"closet ?exchange")),
    ("non_retail", _rule(r"news", r"magazine", r"realty", r"law", r"attorneys?", r"salons?",
                         r"staffing", r"ministr(y|ies)", r"foundation", r"church", r"schools?",
                         r"hospital", r"healthcare", r"tourism", r"visit", r"chamber",
                         r"directory", r"podcast", r"capital", r"realestate")),
)  # fmt: skip
# The same inside a domain written as one word ("keenelandshop.com"): long, unambiguous
# pieces only, since "ski" sits in "skirt" and "inn" in "winner".
DOMAIN_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("showroom_agency", ("showroom", "repgroup", "distributor")),
    ("promo_corporate", ("promotional", "embroidery", "screenprint", "corporategift")),
    ("resort_hotel_club", ("hotel", "resort", "lodge", "golf", "marina", "keeneland",
                           "racecourse", "proshop")),  # not "countryclub": countryclubprep.com
    ("gift_museum", ("museum", "giftshop", "souvenir", "aquarium")),
    ("outdoor_sporting", ("outfitter", "outdoor", "skishop", "sportinggoods", "surfshop",
                          "flyshop", "tackle")),
    ("marketplace_resale", ("consign", "resale", "thrift", "closetexchange", "preowned")),
)  # fmt: skip
# Phrases on the home or about page that say the same thing unambiguously ("resort wear"
# or "running a family business" must not make a boutique a resort or a running shop).
TEXT_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("showroom_agency", _rule(r"(our|a) showroom", r"rep group", r"sales agency",
                              r"wholesale only", r"trade only", r"we represent")),
    ("promo_corporate", _rule(r"promotional products", r"corporate (gifts|apparel|wear)",
                              r"custom (apparel|embroidery|logo)", r"branded merchandise")),
    ("resort_hotel_club", _rule(r"(our|the) (hotel|resort|inn|lodge|club)'?s? "
                                r"(shop|store|boutique)",
                                r"guests? of (the|our) (hotel|resort|inn)",
                                r"pro shop",
                                r"golf (shop|club|course)", r"country club", r"yacht club")),
    ("gift_museum", _rule(r"museum (shop|store)", r"gift shop", r"souvenirs?",
                          r"visitor cent(er|re)")),
    ("outdoor_sporting", _rule(r"sporting goods", r"ski (shop|rental)", r"fly fishing",
                               r"outdoor (gear|equipment)")),
    ("marketplace_resale", _rule(r"consignment", r"resale shop", r"thrift (store|shop)",
                                 r"gently used", r"pre-?owned designer")),
)  # fmt: skip


@dataclass(frozen=True)
class BusinessType:
    kind: str
    reason: str
    # Phrases on the home or about page that hint at a B2B kind ("our hotel's shop",
    # "consignment"): shown for a person to check, never deciding the kind on their own.
    # Measured on 2026-10-08: boutiques mention "golf shop" and "country club" too.
    hints: tuple[str, ...] = ()


def compact(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def business_type(
    domain: str,
    name: str,
    text: str,
    store_type: str,
    status: str,
    product_count: int,
) -> BusinessType:
    """The kind of business, and the evidence for it."""
    label = compact(domain.split(".")[0])
    if domain.endswith(NON_RETAIL_TLDS) or (domain.endswith(".org") and product_count == 0):
        return BusinessType("non_retail", f"domain {domain}")
    for chain in CHAINS:
        if label == chain or (len(chain) >= 6 and label.startswith(chain)):
            return BusinessType("department_store", f"known chain: {chain}")
    for market in MARKETPLACES:
        if domain == market or domain.startswith(market + ".") or label == compact(market):
            return BusinessType("marketplace_resale", f"marketplace: {market}")
    hints = tuple(
        f"{kind}: '{m.group(0).lower()}'"
        for kind, pattern in TEXT_RULES
        if (m := pattern.search(text[:4000]))
    )
    if store_type != "own_brand" and any(h.startswith("marketplace_resale") for h in hints):
        return BusinessType("marketplace_resale", hints[0].split(": ", 1)[1], hints)  # consignment
    # Fibres first out of the way: "thecashmeresale" is a cashmere sale, not a resale shop.
    bare = re.sub(r"cashmere|merino|alpaca|mohair", "-", label)
    for kind, pieces in DOMAIN_RULES:
        if piece := next((p for p in pieces if p in bare), ""):
            return BusinessType(kind, f"domain: '{piece}'", hints)
    own_words = " ".join([name, re.sub(r"[.\-]", " ", domain.rsplit(".", 1)[0])])
    for kind, pattern in NAME_RULES:
        if m := pattern.search(own_words):
            if kind == "non_retail" and product_count > 0:
                continue  # a shop named "... News" still sells
            return BusinessType(kind, f"name: '{m.group(0).lower()}'", hints)
    if status == "ok" and store_type == "own_brand":
        return BusinessType("own_label", "sells its own label", hints)
    if status == "ok" and store_type == "multi_brand":
        return BusinessType("boutique", "sells other brands", hints)
    if status == "ok" and product_count > 0:
        return BusinessType("boutique", "sells products; brands unclear", hints)
    return BusinessType("unknown", "", hints)

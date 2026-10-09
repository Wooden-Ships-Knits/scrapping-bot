"""Strict knitwear: products that are a knitted garment or accessory, for the final list.

`signals.is_knit` is a broad flag: any knit word in the title, type, tags or the start
of the description. On a real run (2026-10-08, 45,108 flagged products) that took in
tees, trousers, socks, candles and denim "jumpers" through a tag or a fabric line.
The final list (ADR 0010) needs the products a knitwear maker would call knitwear, so
this test reads only the product's own name and category:

- `garment`: a sweater, cardigan, pullover, knit jumper, turtleneck, poncho, or a knit
  or cashmere/wool top, vest, polo or hoodie.
- `accessory`: a beanie, or a scarf, hat, glove or wrap that says it is knitted or
  made of a knit fibre.
- "": anything else, including sweatshirts, jersey basics, woven wool coats, yarn and
  knitting supplies, and home goods.

Nothing is dropped: the kind is a column beside the raw values (`products.knit_kind`).
"""

import re
from typing import Literal

from ..models import Product

KnitKind = Literal["garment", "accessory", ""]


def _words(*words: str) -> re.Pattern[str]:
    return re.compile(r"\b(?:" + "|".join(words) + r")\b", re.I)


# Garments that are knitwear by name.
CORE = _words(
    r"sweaters?", r"cardigans?", r"cardis?", r"pullovers?", r"knitwear", r"ponchos?", r"shrugs?"
)
# "Jumper" is a sweater in British English and a pinafore dress or overall in American.
JUMPER = _words(r"jumpers?")
NOT_A_SWEATER_JUMPER = _words(
    r"overalls?", r"denim", r"jumpsuits?", r"rompers?", r"pinafores?", r"smock", r"dungarees?",
    r"jeans?",
)  # fmt: skip
TURTLENECK = _words(
    r"turtle[\s-]?necks?", r"mock[\s-]?necks?", r"roll[\s-]?necks?", r"polo[\s-]?necks?"
)
KNIT = _words(
    r"knit", r"knits", r"knitted", r"hand[\s-]?knit", r"cable[\s-]?knit", r"crochet(?:ed)?"
)
FIBRE = _words(
    r"cashmere", r"merino", r"alpaca", r"mohair", r"lambswool", r"wool", r"angora", r"yak",
    r"cashwool", r"camel hair",
)  # fmt: skip
# Tops a knit word or a knit fibre turns into knitwear.
TOP = _words(
    r"tops?", r"vests?", r"polos?", r"hood(?:ie|y)s?", r"crew(?:[\s-]?neck)?s?", r"v[\s-]?necks?",
    r"henleys?", r"tunics?", r"wraps?", r"dusters?", r"capes?", r"kimonos?",
    r"(?:quarter|half|full)[\s-]?zips?", r"zip[\s-]?ups?", r"sleeveless",
)  # fmt: skip
# A jacket is knitwear only when it says it is knitted: a "wool jacket" is woven.
JACKET = _words(r"jackets?", r"shackets?")
ACCESSORY = _words(
    r"beanies?", r"toques?", r"tuques?", r"scar(?:f|ves)", r"snoods?", r"cowls?", r"mittens?",
    r"gloves?", r"hats?", r"headbands?", r"ear[\s-]?warmers?", r"balaclavas?", r"shawls?",
    r"wraps?", r"leg[\s-]?warmers?", r"arm[\s-]?warmers?",
)  # fmt: skip
ALWAYS_KNIT_ACCESSORY = _words(r"beanies?", r"toques?", r"tuques?", r"pom[\s-]?pom")
WOVEN_ACCESSORY = _words(r"silk", r"satin", r"linen", r"leather", r"felt", r"straw", r"suede")
# Jersey and woven garments a knit word or fibre does not make knitwear.
NOT_KNITWEAR = _words(
    r"tees?", r"t[\s-]?shirts?", r"tshirts?", r"tanks?", r"camis?", r"camisoles?", r"bodysuits?",
    r"leggings?", r"pants?", r"trousers?", r"joggers?", r"sweatpants?", r"shorts?", r"skirts?",
    r"skorts?", r"jeans?", r"denim", r"blazers?", r"coats?", r"overcoats?", r"peacoats?",
    r"parkas?", r"shirts?", r"overshirts?", r"shackets?", r"dress(?:es)?", r"jumpsuits?",
    r"rompers?", r"socks?", r"bras?", r"bralettes?", r"briefs?", r"underwear", r"boxers?",
    r"swim\w*", r"bikinis?", r"pajamas?", r"pyjamas?", r"sleep\w*", r"robes?", r"sweatshirts?",
    r"slippers?", r"boots?", r"shoes?", r"sneakers?",
)  # fmt: skip
# Goods a knit word appears on that are never clothing, even beside "sweater":
# "Sweater Comb", "Sweater Weather Candle", "Sweater Storage Bag", "Meow Sweater - Pets".
NOT_CLOTHING = _words(
    r"combs?", r"shavers?", r"defuzzers?", r"candles?", r"ornaments?", r"mugs?", r"books?",
    r"gift\s?cards?", r"stickers?", r"keychains?", r"blankets?", r"throws?", r"pillows?",
    r"cushions?", r"rugs?", r"coasters?", r"toys?", r"dolls?", r"storage", r"needles?",
    r"skeins?", r"soap", r"detergent", r"pets?", r"totes?", r"bags?",
    r"dog\s(?:sweaters?|jumpers?)",
)  # fmt: skip
# Knitting supplies, unless the title also names a garment: "Merino Yarn" and "Hat
# Pattern" are supplies, "Tape Yarn Sweater" and "Mineral Wash Cardigan" are not.
SUPPLIES = _words(r"yarns?", r"patterns?", r"kits?", r"knitting", r"wash")
# A sweater word on these is not a sweater: "Sweatshirt Cardigan" is terry,
# "Snowed In Sweater Crew Socks" are socks. "Sweater Tee" is a knitted top and stays.
NOT_A_SWEATER = _words(r"sweatshirts?", r"socks?", r"t[\s-]?shirt\s+cardigans?")
# Category names that mean knitwear: Shopify product types such as "Sweaters" or "Knits".
CORE_TYPE = _words(
    r"sweaters?", r"cardigans?", r"pullovers?", r"knitwear", r"knits", r"jumpers?", r"knit tops?"
)


def knit_kind(product: Product) -> KnitKind:
    """Whether the product is a knitted garment, a knitted accessory, or neither."""
    title = product.title or ""
    if NOT_CLOTHING.search(title):
        return ""
    if SUPPLIES.search(title) and not (CORE.search(title) or JUMPER.search(title)):
        return ""
    if _is_garment(title):
        return "garment"
    if _is_accessory(title):
        return "accessory"
    if CORE_TYPE.search(product.product_type or "") and not NOT_KNITWEAR.search(title):
        return "accessory" if ACCESSORY.search(title) else "garment"
    return ""


def _is_garment(title: str) -> bool:
    if CORE.search(title):
        # "Sweater" wins over a garment word: "Sweater Dress", "Sweater Vest", "Sweater
        # Coat", "Sweater Tee".
        return not NOT_A_SWEATER.search(title)
    if JUMPER.search(title):
        return not NOT_A_SWEATER_JUMPER.search(title)
    if NOT_KNITWEAR.search(title):
        return False
    if TURTLENECK.search(title):
        return True
    if KNIT.search(title):
        return bool(TOP.search(title) or JACKET.search(title))
    return bool(FIBRE.search(title) and TOP.search(title))


def _is_accessory(title: str) -> bool:
    if NOT_KNITWEAR.search(title) or not ACCESSORY.search(title):
        return False
    if ALWAYS_KNIT_ACCESSORY.search(title) or KNIT.search(title):
        return True
    return bool(FIBRE.search(title) and not WOVEN_ACCESSORY.search(title))

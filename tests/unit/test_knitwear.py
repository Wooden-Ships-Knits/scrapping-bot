"""Strict knitwear for the final list. Titles are from the 2026-10-08 run unless noted."""

import pytest

from scrapebot.extract.knitwear import knit_kind
from scrapebot.models import Product


def kind(title: str, product_type: str = "") -> str:
    return knit_kind(Product(title=title, product_type=product_type))


@pytest.mark.parametrize(
    "title",
    [
        "Moher Ladies Traditional Aran Sweater",
        "Kari Striped Cardigan",
        "ESCAPE BY HABITAT  TWIST & SHOUT EASY PULLOVER IN BAJA BLUE",
        "Papillon Long Sleeve Sweater Dress - Emerald",
        "Feather Yarn Sweater Coat with Pearl Trim",
        "Sanctuary Perfect Sweater Tee - Heather Dark Bone",
        "Tape Yarn Sweater",
        "Zaket & Plover Peekaboo Cat Cardigan- ZP8509U",
        "Solstice Mineral Wash Cardigan",
        "KNITTED CARDIGAN W/PIN",
        "Lyla & Luxe Novelty Fur Collar Cardi Navy",
        "Moher Aran Jumper",
        "La Ligne Striped Mock Neck Sweater, Small",
        "Kerri Rosenthal - Marley Cashmere Sweater",
        "Cashmere Crew",
        "Alpaca Button Down Vest / Basalt",
        "Knit Jacket",
        "London Imports Handmade Crochet Top",
    ],
)
def test_knitted_garments(title):
    assert kind(title) == "garment"


@pytest.mark.parametrize(
    "title",
    [
        "Linda Richards Knit Stripe Pom-pom Hat HA-81 | Taupe",
        "PAUL Beanie in Merino Wool - Chocolate",
        "Dinadi | Merino Handknit Mittens",
        "Kuna Cardenal Baby Alpaca Scarf",
        "Knit with Pearls Toque",
        "Cable Knit Beanie",
    ],
)
def test_knitted_accessories(title):
    assert kind(title) == "accessory"


@pytest.mark.parametrize(
    "title",
    [
        # Jersey basics and woven garments that the broad flag took in.
        "Lani Rib Knit Tank - Malt",
        "Lucius Twill Knit Flare Pant - Black",
        "L'agence Catie V-Neck Knit Blazer",
        "Knit Woven Combo Dress - White",
        "Wool Blend Plaid Reversible Coat",
        "Wool Jacket",
        "Filson Wool Jac Shirt, Men's XXLarge Long",
        "Classic Straight Pants - Vanilla",
        # Sweatshirts are terry or fleece, not knitwear.
        "Frank & Eileen | Jackie Sweatshirt Cardigan | Triple Terry",
        "Last Boat Sweatshirt",
        "Smartwool Everyday Cozy Snowed In Sweater Crew Socks - SW002186Q51",
        # An American jumper is a pinafore or an overall.
        "Ali Golden Overall Jumper - Black Denim",
        # Not clothing at all.
        "Sweater Comb",
        "Meow Sweater - Pets",
        "Dog Sweater",
        "Merino Yarn",  # invented: a yarn shop's skein
        "Hat Pattern",  # invented: a knitting pattern
        "Apothecary Guild 11oz Boxed Candle - Sea Salt & Coastal Mist",
        # A woven scarf: silk names the weave.
        "Cashmere & Silk Scarf in Indigo",
    ],
)
def test_not_knitwear(title):
    assert kind(title) == ""


def test_a_knitwear_category_counts_when_the_title_is_only_a_name():
    assert kind("Olivia", "Sweaters") == "garment"
    assert kind("Avery Hat", "Knitwear") == "accessory"
    assert kind("Olivia Tee", "Sweaters") == "", "the title still rules out a tee"


def test_description_and_tags_are_not_read():
    """The broad flag read them, and took in trousers tagged 'knit'."""
    pants = Product(title="Bootcut Pull-On Pant", tags=["knit", "sweaters"], description="knit")
    assert knit_kind(pants) == ""

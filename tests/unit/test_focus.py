"""Which chosen items a product is (extract/focus.py)."""

import pytest

from scrapebot.config import FocusConfig
from scrapebot.extract.focus import matched_items, search_phrase
from scrapebot.models import Product

ALL = ["knitwear", "cashmere_wool", "fall_winter", "spring_summer"]


@pytest.mark.parametrize(
    ("product", "expected"),
    [
        (Product(title="Cher Sweater"), ["knitwear"]),
        (Product(title="Isola Cashmere Pullover"), ["knitwear", "cashmere_wool"]),
        (Product(title="Wool Coat"), ["cashmere_wool"]),
        (Product(title="Linen Dress", tags=["Spring 2026"]), ["spring_summer"]),
        (Product(title="Cable Cardigan", tags=["FW25"]), ["knitwear", "fall_winter"]),
        (Product(title="Holiday Sequin Top"), ["fall_winter"]),
        (Product(title="Waterfall Earrings"), []),
        (Product(title="Leather Bag"), []),
    ],
)
def test_products_match_the_items_they_are(product, expected):
    assert matched_items(product, ALL, []) == expected


def test_only_chosen_items_are_reported():
    assert matched_items(Product(title="Cashmere Sweater"), ["cashmere_wool"], []) == [
        "cashmere_wool"
    ]


def test_other_matches_the_operator_s_own_words():
    poncho = Product(title="Fringe Poncho")
    assert matched_items(poncho, ["other"], ["poncho", "cape"]) == ["other"]
    assert matched_items(Product(title="Scarf"), ["other"], ["poncho"]) == []


def test_search_phrase_follows_the_items():
    assert search_phrase(["knitwear", "fall_winter"], []) == (
        "sweaters and knitwear, fall and winter collections"
    )
    assert search_phrase(["other"], ["ponchos"]) == "ponchos"
    assert search_phrase([], []) == "sweaters and knitwear"


def test_focus_config_rejects_unknown_items_and_tidies_terms():
    assert FocusConfig(items=["knitwear", "knitwear"], terms=[" poncho ", ""]).model_dump() == {
        "items": ["knitwear"],
        "terms": ["poncho"],
    }
    with pytest.raises(ValueError, match="unknown item"):
        FocusConfig(items=["hats"])

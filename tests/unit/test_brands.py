"""Which brands a store sells, from product vendors (ADR 0010)."""

from scrapebot.extract.brands import brand_mix, is_own_name, store_name
from scrapebot.models import Product


def products(*vendors: str, each: int = 1) -> list[Product]:
    return [Product(title=f"Item {i}", vendor=v) for v in vendors for i in range(each)]


def test_three_outside_brands_make_a_multi_brand_store():
    mix = brand_mix("evielou.com", products("Rundholz", "Porto", "Prairie Underground", each=3))
    assert mix.store_type == "multi_brand"
    assert mix.brand_count == 3
    assert mix.brands[0] == "Rundholz"


def test_the_stores_own_name_is_not_an_outside_brand():
    """bluenvy.ca, 2026-10-08: 1,631 products under its own name, 41 other brands."""
    mix = brand_mix(
        "bluenvy.ca",
        products("Bluenvy Boutique", each=50) + products("Guess", "FDJ", "Gentle Fawn"),
    )
    assert mix.store_type == "multi_brand"
    assert "Bluenvy Boutique" not in mix.brands


def test_only_the_own_name_is_unclear():
    """Could be a label (frenchkyss.com) or a boutique that tags everything with its
    name (lylasclothing.com): the LLM decides."""
    mix = brand_mix("lylasclothing.com", products("Lyla's: Clothing, Decor & More", each=5))
    assert (mix.store_type, mix.reason) == ("unknown", "vendors are only the store's own name")


def test_placeholder_vendors_are_ignored():
    mix = brand_mix("shop.com", products("Default Vendor", "Gift Card", "Wholesale", each=4))
    assert mix.store_type == "unknown"
    assert mix.brands == []


def test_one_brand_that_is_nearly_everything_is_unclear():
    """gapfactory.ca lists its sub-brands as vendors; a chain is not a boutique."""
    mix = brand_mix(
        "gapfactory.ca", products("Banana Republic Factory", each=95) + products("A", "B", "C")
    )
    assert (mix.store_type, mix.reason) == ("unknown", "one brand is nearly the whole catalogue")


def test_too_few_vendors_are_not_trusted():
    items = products("A", "B", "C") + [Product(title=f"x{i}") for i in range(10)]
    assert brand_mix("x.com", items).reason == "few products name a vendor"


def test_two_outside_brands_are_unclear():
    assert brand_mix("x.com", products("A", "B", each=3)).store_type == "unknown"


def test_own_name_matching():
    assert store_name("clothesmentor.com") == "clothesmentor"
    assert is_own_name("clothes mentor bloomington illinois", "clothesmentor")
    assert is_own_name("bluenvy boutique", "bluenvy")
    assert is_own_name("rose", "roseboutique")
    assert not is_own_name("guess", "bluenvy")
    assert not is_own_name("co", "co"), "short names match too easily"

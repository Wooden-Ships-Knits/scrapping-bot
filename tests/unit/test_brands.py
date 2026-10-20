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
        products("Bluenvy Boutique", each=50) + products("Guess", "FDJ", "Gentle Fawn", each=5),
    )
    assert mix.store_type == "multi_brand"
    assert "Bluenvy Boutique" not in mix.brands


def test_a_label_with_a_few_collaborations_is_unclear():
    """lazyoaf.com, 2026-10-13: three outside brands on 7 of 2,000 products. The
    validation sheet found a single label; the vendors alone had called it multi-brand."""
    items = (
        products("Lazy Oaf", each=1993)
        + products("G.E.M.", each=4)
        + products("Stone", each=2)
        + products("Creightons")
    )
    mix = brand_mix("lazyoaf.com", items)
    assert (mix.store_type, mix.reason) == (
        "unknown",
        "the store's own name is on nearly every product",
    )
    assert mix.brand_count == 3, "the brands are still listed for the LLM and the export"


def test_a_boutique_that_tags_its_own_name_goes_to_the_llm():
    """matchmadestores.com, 2026-10-13: 302 of 306 products under its own name. It may be
    a boutique that relabels everything, so the rule does not call it own-brand."""
    items = (
        products("Match Made Stores", each=302)
        + products("ASTR the Label", each=2)
        + products("RAISONNEL", "BLANKNYC")
    )
    assert brand_mix("matchmadestores.com", items).store_type == "unknown"


def test_outside_brands_at_the_minimum_share_are_enough():
    items = products("Rose Boutique", each=27) + products("A", "B", "C")
    assert brand_mix("roseboutique.com", items).store_type == "multi_brand"


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

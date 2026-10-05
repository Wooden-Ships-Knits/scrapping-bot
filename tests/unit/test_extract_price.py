from scrapebot.extract.prices import parse_price, price_stats
from scrapebot.models import Product


def test_parse_price_handles_common_formats():
    assert parse_price("139.00") == 139.0
    assert parse_price("$1,395.00") == 1395.0
    assert parse_price("USD 45") == 45.0
    assert parse_price(139) == 139.0
    assert parse_price(" $38.50 ") == 38.5


def test_parse_price_rejects_junk():
    assert parse_price("") is None
    assert parse_price(None) is None
    assert parse_price("Sold out") is None
    assert parse_price("0") is None, "zero price is not a real price"
    assert parse_price("0.00") is None


def test_parse_price_takes_first_number_in_a_range():
    assert parse_price("$120.00 - $180.00") == 120.0


def test_price_stats_returns_min_max_median():
    items = [
        Product(title="a", price=10.0),
        Product(title="b", price=30.0),
        Product(title="c", price=20.0),
        Product(title="d", price=None),
    ]
    assert price_stats(items) == (10.0, 30.0, 20.0)


def test_price_stats_on_empty_input():
    assert price_stats([]) == (None, None, None)
    assert price_stats([Product(title="a", price=None)]) == (None, None, None)

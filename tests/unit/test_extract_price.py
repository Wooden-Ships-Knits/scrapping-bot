from scrapebot.extract.prices import parse_price


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


def test_parse_price_reads_a_decimal_comma():
    """herrlicher.com, 7 Oct 2026: '119,99 €' was stored as 11999.0."""
    assert parse_price("119,99 €") == 119.99
    assert parse_price("€ 49,95") == 49.95
    assert parse_price("€ 24,-") == 24.0
    assert parse_price("1.299,00 €") == 1299.0


def test_parse_price_reads_thousands_separators():
    assert parse_price("1 299,00 kr") == 1299.0
    assert parse_price("1 299,00 kr") == 1299.0
    assert parse_price("CHF 1'299.00") == 1299.0
    assert parse_price("Rp 139.000") == 139000.0
    assert parse_price("$1,234,567") == 1234567.0


def test_a_space_joins_only_groups_of_three_digits():
    assert parse_price("36 38") == 36.0

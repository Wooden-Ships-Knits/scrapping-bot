"""Reading numbers out of price strings."""

import re
from typing import Any

# A number with its separators: '1,395.00', '119,99', '1.299,00', '1 299,00', "1'299".
# A space joins only a group of exactly three digits, so '36 38' stays two numbers.
NUMBER_RE = re.compile(r"\d+(?:(?:[.,'\u2019]|[ \u00a0\u202f](?=\d{3}(?!\d)))\d+)*")
_GROUPING_RE = re.compile(r"[ \u00a0\u202f'\u2019]")


def read_number(token: str) -> float:
    """One NUMBER_RE match as a float. The decimal mark is the last separator when the
    number has both '.' and ',' ('1,395.00', '1.299,00'), or when its only separator
    appears once with one or two digits after it ('119,99'); otherwise every separator
    groups thousands ('1,395', 'Rp 139.000')."""
    digits = _GROUPING_RE.sub("", token)
    marks = [c for c in digits if c in ".,"]
    decimal = ""
    if len(set(marks)) == 2:
        decimal = marks[-1]
    elif len(marks) == 1 and len(digits) - digits.index(marks[0]) - 1 in (1, 2):
        decimal = marks[0]
    whole, _, fraction = digits.rpartition(decimal) if decimal else (digits, "", "")
    whole = whole.replace(".", "").replace(",", "")
    return float(f"{whole}.{fraction}" if fraction else whole)


def parse_price(raw: Any) -> float | None:
    """First positive number in the input, or None. Handles '$1,395.00', '119,99 €' and ranges."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, int | float):
        return float(raw) or None
    m = NUMBER_RE.search(str(raw))
    if not m:
        return None
    value = read_number(m.group())
    return value if value > 0 else None

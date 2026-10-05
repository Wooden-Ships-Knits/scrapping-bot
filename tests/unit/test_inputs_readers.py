import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from openpyxl import Workbook

from scrapebot.inputs.readers import InputError, extract_urls, read_file, read_text

LINKS = ["https://monkees.com", "https://www.saracampbell.com/pages/naples", "boutique-x.com"]
ROWS = [
    {"store_name": "Monkees", "website": LINKS[0], "address": "Naples FL"},
    {"store_name": "Sara Campbell", "website": LINKS[1], "address": "Naples FL"},
    {"store_name": "Boutique X", "website": LINKS[2], "address": "Miami FL"},
]


def test_free_text_yields_every_url_even_inside_sentences():
    """PRD IN-01: ten URLs in the middle of sentences give ten URLs."""
    domains = [f"store{i}.com" for i in range(10)]
    text = "Try " + ", then ".join(domains) + ". Thanks! Mail me at owner@agency.com."
    assert extract_urls(text) == domains


def test_free_text_strips_trailing_punctuation():
    assert extract_urls("See https://a.com/shop?x=1, and (https://b.com).") == [
        "https://a.com/shop?x=1",
        "https://b.com",
    ]


def write_all_formats(tmp_path):
    """The same list in every supported file format."""
    paths = {}
    paths["txt"] = tmp_path / "in.txt"
    paths["txt"].write_text("\n".join(LINKS) + "\n")
    for suffix, sep in (("csv", ","), ("tsv", "\t")):
        path = tmp_path / f"in.{suffix}"
        lines = [sep.join(ROWS[0])] + [sep.join(r.values()) for r in ROWS]
        path.write_text("\n".join(lines) + "\n")
        paths[suffix] = path
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.append(list(ROWS[0]))
    for r in ROWS:
        ws.append(list(r.values()))
    paths["xlsx"] = tmp_path / "in.xlsx"
    wb.save(paths["xlsx"])
    paths["json"] = tmp_path / "in.json"
    paths["json"].write_text(json.dumps(ROWS))
    paths["jsonl"] = tmp_path / "in.jsonl"
    paths["jsonl"].write_text("\n".join(json.dumps(r) for r in ROWS) + "\n")
    paths["parquet"] = tmp_path / "in.parquet"
    pq.write_table(pa.Table.from_pylist(ROWS), paths["parquet"])
    return paths


def test_every_format_yields_the_same_links(tmp_path):
    """PRD IN-02: the same list in all seven formats gives identical URL lists."""
    for suffix, path in write_all_formats(tmp_path).items():
        assert [r.value for r in read_file(path)] == LINKS, suffix


def test_tabular_formats_keep_every_column_as_metadata(tmp_path):
    """PRD IN-03: other columns come through untouched."""
    for suffix, path in write_all_formats(tmp_path).items():
        if suffix == "txt":
            continue
        assert [r.meta for r in read_file(path)] == ROWS, suffix


def test_url_column_is_found_from_content_when_the_header_says_nothing(tmp_path):
    path = tmp_path / "in.csv"
    path.write_text("name,where\nA,https://a.com\nB,b-shop.com\nC,\n")
    assert [r.value for r in read_file(path)] == ["https://a.com", "b-shop.com", ""]


def test_named_url_column_must_exist(tmp_path):
    path = tmp_path / "in.csv"
    path.write_text("name,site_link\nA,https://a.com\n")
    assert [r.value for r in read_file(path, url_column="site_link")] == ["https://a.com"]
    with pytest.raises(InputError, match="not found"):
        read_file(path, url_column="website")


def test_a_cell_holding_a_sentence_yields_the_url_in_it(tmp_path):
    path = tmp_path / "in.csv"
    path.write_text('name,website\nA,"Our site is a-shop.com, come visit"\n')
    assert read_file(path)[0].value == "a-shop.com"


def test_json_list_of_links(tmp_path):
    path = tmp_path / "in.json"
    path.write_text(json.dumps({"links": LINKS}))
    assert [r.value for r in read_file(path)] == LINKS


def test_unsupported_format_is_refused(tmp_path):
    path = tmp_path / "in.pdf"
    path.write_text("x")
    with pytest.raises(InputError, match="Unsupported"):
        read_file(path)


def test_read_text_has_no_metadata():
    assert [r.meta for r in read_text("a.com b.com")] == [{}, {}]

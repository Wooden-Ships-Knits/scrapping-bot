import pytest
from pydantic import ValidationError

from scrapebot.store import RunStore
from scrapebot.tables import TABLES, Column, ContactRow, ProductRow, columns


def test_the_tables_come_in_a_fixed_order():
    """The PRD's seven, then llm_calls (PRD LM-11)."""
    assert list(TABLES) == [
        "runs",
        "inputs",
        "stores",
        "products",
        "pages",
        "contacts",
        "changes",
        "llm_calls",
    ]


def test_every_table_joins_on_run_id_and_all_but_runs_and_inputs_on_domain():
    for name, model in TABLES.items():
        names = [c.name for c in columns(model)]
        assert names[0] == "run_id", name
        if name not in ("runs", "inputs"):
            assert names[1] == "domain", name


def test_column_kinds_come_from_annotations():
    kinds = {c.name: c for c in columns(ProductRow)}
    assert kinds["title"] == Column("title", "str", False)
    assert kinds["price"] == Column("price", "float", True)
    assert kinds["needs_review"] == Column("needs_review", "bool", False)
    assert kinds["tags"].kind == "json"
    assert kinds["raw"].kind == "json"


def test_rows_reject_unknown_columns():
    with pytest.raises(ValidationError):
        ContactRow(run_id="r", domain="d", type="email", value="v", source_url="u", extra="x")  # pyright: ignore[reportCallIssue]


def test_store_appends_and_reads_back(tmp_path):
    store = RunStore(tmp_path / "run")
    assert all(store.path(name).exists() for name in TABLES), "empty tables exist from the start"
    row = ContactRow(
        run_id="r", domain="ü.com", type="email", value="a@ü.com", source_url="https://ü.com"
    )
    store.append([row])
    store.append([row])
    assert store.read("contacts") == [row.model_dump(mode="json")] * 2
    assert "ü" in store.path("contacts").read_text(encoding="utf-8"), "UTF-8, not escaped"
    tables = {t.name: t for t in store.load_tables()}
    assert len(list(tables["contacts"].rows)) == 2
    assert list(tables["changes"].rows) == []
    assert list(tables["contacts"].rows) == list(tables["contacts"].rows), "re-iterable"

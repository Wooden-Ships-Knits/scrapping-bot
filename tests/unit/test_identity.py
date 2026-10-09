"""Who a store says it is in its own markup (extract.identity), and the chores around the
data (housekeeping)."""

import zipfile
from pathlib import Path

from scrapebot import cli
from scrapebot.analysis.location import from_identity
from scrapebot.extract.identity import store_identity
from scrapebot.housekeeping import BACKUP_PREFIX, backup, init_inputs
from scrapebot.models import Page

FIXTURES = Path(__file__).parents[1] / "fixtures/http"


def home(name, url):
    return Page(url=url, html=(FIXTURES / name).read_text(errors="replace"), kind="home")


def test_a_clothing_store_with_its_address_and_position():
    """blissboutiques.com, 2026-10-09: a schema.org ClothingStore on the home page."""
    identity = store_identity(
        [
            home(
                "blissboutiques.com-2026-10-09-home-clothingstore.html",
                "https://www.blissboutiques.com",
            )
        ]
    )
    [store] = identity["organizations"]
    assert (store["type"], store["name"], store["telephone"]) == (
        "ClothingStore", "Bliss Boutiques", "207-879-7125",
    )  # fmt: skip
    assert store["address"] == {
        "streetAddress": "119 Middle Street", "addressLocality": "Portland",
        "addressRegion": "ME", "postalCode": "04101", "addressCountry": "US",
    }  # fmt: skip
    assert store["geo"] == {"latitude": "43.6589098", "longitude": "-70.2527145"}
    assert identity["site_name"] == "Bliss Boutiques"
    assert identity["title"].startswith("Bliss:")


def test_an_organization_with_email_and_no_address():
    identity = store_identity(
        [
            home(
                "dearprudence.com-2026-10-09-home-cloudflare-jsd.html",
                "https://www.dearprudence.com",
            )
        ]
    )
    [org] = identity["organizations"]
    assert (org["name"], org["email"]) == ("Dear Prudence Shops", "orders@dearprudence.com")
    assert "address" not in org


def test_only_identity_pages_are_read_and_nothing_breaks_without_markup():
    product_page = Page(url="https://x.com/p/1", html="<title>Sweater</title>", kind="product")
    assert store_identity([product_page]) == {}
    assert store_identity([Page(url="https://x.com", html="<p>hi</p>", kind="home")]) == {}


def test_the_analysis_takes_the_declared_address_and_position():
    identity = store_identity(
        [
            home(
                "blissboutiques.com-2026-10-09-home-clothingstore.html",
                "https://www.blissboutiques.com",
            )
        ]
    )
    found = from_identity(identity)
    assert found is not None
    assert (found.city, found.state, found.postal, found.source) == (
        "Portland", "ME", "04101", "site_data",
    )  # fmt: skip
    assert (found.lat, found.lng) == (43.6589098, -70.2527145), "no geocoding needed"
    assert from_identity({}) is None


def test_init_inputs_writes_examples_once_and_never_real_names(tmp_path):
    written = init_inputs(tmp_path)
    assert sorted(p.name for p in written) == [
        "README.txt", "accounts.example.csv", "brands.example.csv", "price_points.example.csv",
    ]  # fmt: skip
    assert not (tmp_path / "accounts.csv").exists(), "the analysis must never read an example"
    assert init_inputs(tmp_path) == []


def test_backup_zips_the_data_without_caches_and_keeps_the_newest(tmp_path):
    data = tmp_path / "data"
    for path in ("runs/r1/tables/stores.jsonl", "inputs/accounts.csv", "discover/d1/stores.csv",
                 ".cache/x.com/page.json", "runs/r1/export/r1-csv.zip"):  # fmt: skip
        (data / path).parent.mkdir(parents=True, exist_ok=True)
        (data / path).write_text("x")
    dest = tmp_path / "drive"
    first = backup(dest, data=data, keep=2, now=1_000_000)
    with zipfile.ZipFile(first) as zf:
        assert sorted(zf.namelist()) == [
            "data/discover/d1/stores.csv", "data/inputs/accounts.csv",
            "data/runs/r1/tables/stores.jsonl",
        ]  # fmt: skip
    backup(dest, data=data, keep=2, now=1_000_100)
    backup(dest, data=data, keep=2, now=1_000_200)
    kept = sorted(p.name for p in dest.glob(f"{BACKUP_PREFIX}*.zip"))
    assert len(kept) == 2
    assert first.name not in kept, "the oldest went"


def test_the_commands(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["init-inputs"]) == 0
    assert (tmp_path / "data/inputs/brands.example.csv").exists()
    assert cli.main(["backup", "--to", str(tmp_path / "out")]) == 0
    assert "Backup: " in capsys.readouterr().out

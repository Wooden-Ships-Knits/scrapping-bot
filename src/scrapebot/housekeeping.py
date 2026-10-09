"""Two chores around the data: starting the analysis inputs from templates, and backing up
everything that lives only on this machine.

`data/` is never in git (it holds customer records), so a broken disk loses every run.
`scrapebot backup --to <folder>` zips the runs, the inputs and the discovery results (the
caches are left out: they refill themselves) into a dated file, and keeps the newest few.
A synced folder such as Google Drive for desktop makes that an off-site copy.
"""

import time
import zipfile
from collections.abc import Iterator
from pathlib import Path

DATA = Path("data")
BACKUP_FOLDERS = ("runs", "inputs", "discover")
SKIP_SUFFIXES = (".zip", ".part")  # download zips are rebuilt from the run on demand
BACKUP_PREFIX = "scrapebot-backup-"

# Templates for data/inputs/: one example row each, written as *.example.csv so the
# analysis never reads them as real data. Copy one to its real name and replace the row.
TEMPLATES = {
    "accounts.example.csv": (
        "Account Name,Website,Phone,Billing Street,Billing City,Billing State/Province,"
        "Billing Zip/Postal Code,Billing Country,Account Owner,Territory,Type\n"
        "Example Boutique,www.example-boutique.com,(239) 555-0100,1 Main St,Naples,FL,34102,"
        "United States,Jane Rep,Southeast,Customer\n"
    ),
    "brands.example.csv": (
        "brand,relation\nExample Peer Brand,peer\nExample Rival Label,competitor\n"
    ),
    "price_points.example.csv": (
        "category,wholesale_usd,retail_usd\nsweater,85,195\ncardigan,90,210\naccessory,30,70\n"
    ),
    "README.txt": (
        "Inputs for `scrapebot analyze` (see the project README, Wholesale analysis).\n"
        "These files hold customer data and are never committed.\n\n"
        "accounts.csv      A Salesforce account export, as it comes. Columns are matched\n"
        "                  loosely; Website, Phone and the Billing address matter most.\n"
        "brands.csv        brand,relation  with relation = peer (a brand like ours) or\n"
        "                  competitor. A plain list of names counts every name as a peer.\n"
        "price_points.csv  category,wholesale_usd,retail_usd  per knitwear category\n"
        "                  (sweater, cardigan, vest, poncho_wrap, hat, scarf, gloves...).\n"
        "stockists.json    The store locator's list (or stockists.csv).\n\n"
        "Start from the .example.csv files: copy one to its real name, then replace the\n"
        "example row with real ones.\n"
    ),
}


def init_inputs(folder: Path = DATA / "inputs") -> list[Path]:
    """Write the templates that are not there yet; returns the ones written."""
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for name, text in TEMPLATES.items():
        path = folder / name
        if not path.exists():
            path.write_text(text, encoding="utf-8")
            written.append(path)
    return written


def _files(data: Path) -> Iterator[Path]:
    for folder in BACKUP_FOLDERS:
        root = data / folder
        if root.is_dir():
            for path in sorted(root.rglob("*")):
                if path.is_file() and not path.name.endswith(SKIP_SUFFIXES):
                    yield path


def backup(to: Path, data: Path = DATA, keep: int = 5, now: float | None = None) -> Path:
    """Zip the data into `to`, then delete the oldest backups beyond `keep`."""
    to.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now))
    target = to / f"{BACKUP_PREFIX}{stamp}.zip"
    partial = target.with_suffix(".zip.part")
    with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in _files(data):
            zf.write(path, arcname=str(path.relative_to(data.parent)))
    partial.rename(target)  # a half-written backup never looks finished
    backups = sorted(to.glob(f"{BACKUP_PREFIX}*.zip"))
    for old in backups[: max(0, len(backups) - keep)]:
        old.unlink()
    return target

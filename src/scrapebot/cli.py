"""Command line: `scrapebot run <input>`. Builds the same RunConfig the web API will."""

import argparse
import logging
import sys
from pathlib import Path

from pydantic import ValidationError

from . import __version__
from .config import RunConfig, load_config
from .inputs.readers import SUPPORTED_SUFFIXES, InputError
from .outputs import available_writers
from .pipeline import run


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scrapebot", description="Collect raw product and contact data from store websites."
    )
    parser.add_argument("--version", action="version", version=f"scrapebot {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    r = sub.add_parser("run", help="visit every store in a list of links")
    r.add_argument(
        "input",
        nargs="?",
        help=f"links file ({', '.join(SUPPORTED_SUFFIXES)}), or '-' to read pasted text "
        "from stdin. Optional when the config file names one",
    )
    r.add_argument("-c", "--config", type=Path, help="YAML run config; flags override it")
    r.add_argument(
        "-l", "--limit", type=int, help="test mode: visit only the first N stores (try 2)"
    )
    r.add_argument(
        "-f",
        "--format",
        help=f"comma-separated output formats: {','.join(available_writers())}",
    )
    r.add_argument("--url-column", help="column holding the links (default: found automatically)")
    r.add_argument("--max-links", type=int, help="refuse inputs with more links (default 1000)")
    r.add_argument("--runs-dir", type=Path, help="where run folders go (default data/runs)")
    r.add_argument("--cache-dir", type=Path, help="HTTP cache (default data/.cache)")
    r.add_argument("-v", "--verbose", action="store_true", help="log every request decision")
    return parser


def build_config(args: argparse.Namespace) -> RunConfig:
    data = load_config(args.config).model_dump() if args.config else RunConfig().model_dump()
    if args.input == "-":
        data["input"].update(text=sys.stdin.read(), source=None)
    elif args.input:
        data["input"].update(source=args.input, text=None)
    if args.url_column:
        data["input"]["url_column"] = args.url_column
    if args.max_links:
        data["input"]["max_links"] = args.max_links
    if args.format:
        data["output"]["writers"] = [f.strip() for f in args.format.split(",") if f.strip()]
    if args.runs_dir:
        data["output"]["runs_dir"] = args.runs_dir
    if args.cache_dir:
        data["fetch"]["cache_dir"] = args.cache_dir
    if args.limit is not None:
        data["limit"] = args.limit
    return RunConfig.model_validate(data)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    try:
        config = build_config(args)
        result = run(config)
    except (InputError, ValidationError) as exc:
        print(f"scrapebot: {exc}", file=sys.stderr)
        return 2

    print(
        f"\nLinks in: {result.links_in} = processed {result.processed} "
        f"+ skipped {result.skipped}. Stores visited: {result.stores}."
    )
    print(f"Run folder: {result.root}")
    print(f"Report:     {result.report_path}")
    print(f"Summary:    {result.summary_path}")
    return 0

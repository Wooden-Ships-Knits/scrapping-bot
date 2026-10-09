"""Command line: `scrapebot run <input>`. Builds the same RunConfig the web API will."""

import argparse
import logging
import sys
import threading
import webbrowser
from pathlib import Path

from pydantic import ValidationError

from . import __version__
from .config import RunConfig, load_config
from .inputs.readers import SUPPORTED_SUFFIXES, InputError
from .keys import install_redaction, load_keys
from .outputs import available_writers
from .pipeline import execute, resume, run

# The repo's web/dist, where `make web-build` puts the interface.
DEFAULT_WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scrapebot",
        description="Find knitwear stores, then collect raw product and contact data from "
        "their websites.",
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
    r.add_argument(
        "--llm",
        metavar="PROVIDER/MODEL",
        help="the model that reads stores nothing else could and judges unclear store types "
        "(default openai/gpt-4o-mini), e.g. gemini/gemini-2.5-flash or ollama/qwen2.5:3b. "
        "Keys come from .env or the environment",
    )
    r.add_argument("--no-llm", action="store_true", help="never call a model (no API cost)")
    r.add_argument("--llm-fallback", action="append", metavar="MODEL", help="tried in order")
    r.add_argument("--llm-budget", type=float, metavar="USD", help="stop LLM calls at this cost")
    r.add_argument("--llm-api-base", metavar="URL", help="server for local models (Ollama)")
    r.add_argument(
        "--no-render",
        action="store_true",
        help="never open the browser; JavaScript-only stores stay js_required",
    )
    r.add_argument("-v", "--verbose", action="store_true", help="log every request decision")

    d = sub.add_parser("discover", help="find stores to scrape with paid search APIs (ADR 0008)")
    d.add_argument(
        "-c",
        "--config",
        type=Path,
        required=True,
        help="YAML discovery config (copy discover.example.yaml)",
    )
    d.add_argument(
        "--only",
        help="comma-separated steps to run: google_places, web_search, social_search, "
        "ai_agent, resolve (default: all that have a key)",
    )
    d.add_argument("--out", type=Path, help="where discovery folders go (default data/discover)")
    d.add_argument("-v", "--verbose", action="store_true", help="debug logging")

    sv = sub.add_parser("survey", help="measure which stage can read which store (read-only)")
    sv.add_argument("input", nargs="?", help="links file, or '-' for pasted text on stdin")
    sv.add_argument("-c", "--config", type=Path, help="YAML run config; flags override it")
    sv.add_argument("--out", type=Path, help="folder for survey.csv and survey.md")
    sv.add_argument("--url-column", help="column holding the links")
    sv.add_argument("--cache-dir", type=Path, help="HTTP cache (default data/.cache)")
    sv.add_argument("-v", "--verbose", action="store_true", help="debug logging")

    res = sub.add_parser("resume", help="continue a stopped or interrupted run")
    res.add_argument("run", type=Path, help="the run folder, e.g. data/runs/<run_id>")
    res.add_argument("-v", "--verbose", action="store_true", help="debug logging")

    an = sub.add_parser(
        "analyze", help="wholesale analysis of a finished run: partners, competitors (ADR 0011)"
    )
    an.add_argument("run", type=Path, help="the run folder, e.g. data/runs/<run_id>")
    an.add_argument(
        "--inputs",
        type=Path,
        default=Path("data/inputs"),
        help="folder with stockists.json, accounts.csv, brands.csv, price_points.csv",
    )
    an.add_argument("--stockists", type=Path, help="stockist list (.json or .csv)")
    an.add_argument("--accounts", type=Path, help="Salesforce account export (.csv)")
    an.add_argument("--brands", type=Path, help="brand,relation (peer | competitor)")
    an.add_argument("--prices", type=Path, help="category,wholesale_usd,retail_usd")
    an.add_argument(
        "--territory-miles",
        type=float,
        default=15.0,
        help="a stockist closer than this is a territory conflict (default 15)",
    )
    an.add_argument(
        "--no-geocode",
        action="store_true",
        help="do not look up store locations (no distances to stockists)",
    )
    an.add_argument("-f", "--format", default="xlsx,csv", help="output formats (default xlsx,csv)")
    an.add_argument("-v", "--verbose", action="store_true", help="debug logging")

    sub.add_parser("init-inputs", help="write templates for the analysis inputs in data/inputs")
    bk = sub.add_parser("backup", help="zip runs, inputs and discovery results to a folder")
    bk.add_argument(
        "--to",
        type=Path,
        required=True,
        help="where the backup goes, e.g. a Google Drive for desktop folder",
    )
    bk.add_argument("--keep", type=int, default=5, help="backups kept there (default 5)")

    s = sub.add_parser("serve", help="start the local web interface")
    s.add_argument("-c", "--config", type=Path, help="YAML config for fetch and output defaults")
    s.add_argument("-p", "--port", type=int, default=8765, help="port on 127.0.0.1 (default 8765)")
    s.add_argument(
        "--web-dist",
        type=Path,
        default=DEFAULT_WEB_DIST,
        help="built web app to serve (default web/dist; build it with `make web-build`)",
    )
    s.add_argument("--open", action="store_true", help="open the interface in the browser")
    s.add_argument("-v", "--verbose", action="store_true", help="debug logging")
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
    if getattr(args, "llm", None):
        data["llm"].update(enabled=True, model=args.llm)
    if getattr(args, "llm_fallback", None):
        data["llm"]["fallbacks"] = args.llm_fallback
    if getattr(args, "llm_budget", None) is not None:
        data["llm"]["budget_usd"] = args.llm_budget
    if getattr(args, "llm_api_base", None):
        data["llm"]["api_base"] = args.llm_api_base
    if getattr(args, "no_llm", False):
        data["llm"]["enabled"] = False
    if getattr(args, "no_render", False):
        data["render"]["enabled"] = False
    return RunConfig.model_validate(data)


def serve(args: argparse.Namespace) -> int:
    """The web interface on 127.0.0.1 only: it is a single-user local tool (ADR 0007)."""
    try:
        import uvicorn

        from .api import ApiSettings, create_app
    except ImportError:
        print(
            "scrapebot: the web interface needs the ui extra: uv sync --extra ui", file=sys.stderr
        )
        return 2
    try:
        base = load_config(args.config) if args.config else RunConfig()
    except ValidationError as exc:
        print(f"scrapebot: {exc}", file=sys.stderr)
        return 2
    if not (args.web_dist / "index.html").exists():
        print(
            f"scrapebot: no built web app in {args.web_dist}; only the API is served. "
            "Build it with `make web-build`.",
            file=sys.stderr,
        )
    app = create_app(ApiSettings(base=base, web_dist=args.web_dist))
    url = f"http://127.0.0.1:{args.port}"
    print(f"scrapebot interface: {url}  (Ctrl+C to stop)")
    if args.open:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    return 0


def survey(args: argparse.Namespace) -> int:
    from datetime import UTC, datetime

    from .survey import run_survey

    for flag in ("limit", "format", "max_links", "runs_dir"):
        setattr(args, flag, None)
    try:
        config = build_config(args)
    except ValidationError as exc:
        print(f"scrapebot: {exc}", file=sys.stderr)
        return 2
    out = args.out or Path("data/surveys") / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    try:
        result = run_survey(config, out)
    except InputError as exc:
        print(f"scrapebot: {exc}", file=sys.stderr)
        return 2
    print(f"\nSurvey of {len(result.rows)} stores: {result.report_path}")
    print(f"Browser candidates: {len(result.browser_candidates)}")
    return 0


def discover(args: argparse.Namespace) -> int:
    from .discover import load_discover_config, run_discover
    from .discover.run import STEP_NAMES

    try:
        config = load_discover_config(args.config)
    except (OSError, ValidationError) as exc:
        print(f"scrapebot: {exc}", file=sys.stderr)
        return 2
    if args.out:
        config.out_dir = args.out
    only = [s.strip() for s in args.only.split(",") if s.strip()] if args.only else None
    unknown = [s for s in only or [] if s not in STEP_NAMES]
    if unknown:
        print(
            f"scrapebot: unknown step(s) {unknown}; choose from {', '.join(STEP_NAMES)}",
            file=sys.stderr,
        )
        return 2
    try:
        result = run_discover(config, load_keys(), only=only)
    except KeyboardInterrupt:
        print(
            "\nStopped. Paid answers so far are cached: running the same discovery again "
            "repeats them for free.",
            file=sys.stderr,
        )
        return 130

    print(f"\n{'source':<15}{'status':<16}{'found':>7}{'paid':>7}{'cached':>8}{'cost $':>9}")
    for r in result.sources:
        print(
            f"{r.name:<15}{r.status:<16}{r.candidates:>7}{r.requests_sent:>7}"
            f"{r.requests_cached:>8}{r.cost_usd:>9.4f}"
        )
        if r.error:
            print(f"  {r.error}")
    print(
        f"\nStores: {len(result.stores)}, with a website: {result.with_website} "
        f"({result.websites_looked_up} found by name lookup)."
    )
    print(f"Stores file: {result.stores_csv}")
    print(f"Report:      {result.report_path}")
    if not any(r.status in ("ok", "budget_reached") for r in result.sources):
        print("No source ran: add the keys to .env or check the errors above.", file=sys.stderr)
        return 1
    print(f"Next, scrape them (test mode first): scrapebot run {result.stores_csv} --limit 2")
    return 0


def analyze(args: argparse.Namespace) -> int:
    """The wholesale analysis of a finished run (ADR 0011)."""
    from .analysis import inputs as analysis_inputs
    from .analysis.build import Options
    from .analysis.build import analyze as build_analysis
    from .analysis.location import Geocoder
    from .analysis.write import write

    if not (args.run / "tables" / "stores.jsonl").exists():
        print(f"scrapebot: {args.run} is not a run folder", file=sys.stderr)
        return 2
    inputs = analysis_inputs.load(
        args.stockists, args.accounts, args.brands, args.prices, folder=args.inputs
    )
    geocoder = None if args.no_geocode else Geocoder(Path("data/.cache/geocode.json"))
    result = build_analysis(args.run, inputs, Options(args.territory_miles, geocoder))
    writers = [w.strip() for w in args.format.split(",") if w.strip()]
    written = write(result, args.run, writers)
    print((args.run / "analysis" / "README.md").read_text(encoding="utf-8"))
    for name, paths in written.items():
        print(f"{name}: {', '.join(str(p) for p in paths) or 'FAILED, see the log'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if getattr(args, "verbose", False) else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    install_redaction()
    if args.command == "serve":
        return serve(args)
    if args.command == "survey":
        return survey(args)
    if args.command == "discover":
        return discover(args)
    if args.command == "analyze":
        return analyze(args)
    if args.command == "init-inputs":
        from .housekeeping import init_inputs

        written = init_inputs()
        print("\n".join(f"wrote {p}" for p in written) or "data/inputs already has the templates")
        return 0
    if args.command == "backup":
        from .housekeeping import backup

        target = backup(args.to.expanduser(), keep=args.keep)
        print(f"Backup: {target} ({target.stat().st_size / 1e6:.0f} MB)")
        return 0
    try:
        keys = load_keys()
        if args.command == "resume":
            result = execute(resume(args.run), keys=keys)
        else:
            result = run(build_config(args), keys=keys)
    except (InputError, ValidationError) as exc:
        print(f"scrapebot: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print(
            "\nStopped. Finished stores are saved; continue with "
            "`scrapebot resume data/runs/<run_id>` (the run id is in the log above).",
            file=sys.stderr,
        )
        return 130

    print(
        f"\nLinks in: {result.links_in} = processed {result.processed} "
        f"+ skipped {result.skipped}. Stores visited: {result.stores}."
    )
    print(f"Run folder: {result.root}")
    if result.stopped:
        print(f"Stopped before the end. Continue with: scrapebot resume {result.root}")
        return 0
    print(f"Report:     {result.report_path}")
    print(f"Summary:    {result.summary_path}")
    return 0

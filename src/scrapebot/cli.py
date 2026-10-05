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
    r.add_argument(
        "--llm",
        metavar="PROVIDER/MODEL",
        help="read stores nothing else could with this model, e.g. gemini/gemini-2.5-flash "
        "or ollama/qwen2.5:3b. Keys come from .env or the environment",
    )
    r.add_argument("--llm-fallback", action="append", metavar="MODEL", help="tried in order")
    r.add_argument("--llm-budget", type=float, metavar="USD", help="stop LLM calls at this cost")
    r.add_argument("--llm-api-base", metavar="URL", help="server for local models (Ollama)")
    r.add_argument("-v", "--verbose", action="store_true", help="log every request decision")

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


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    install_redaction()
    if args.command == "serve":
        return serve(args)
    if args.command == "survey":
        return survey(args)
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

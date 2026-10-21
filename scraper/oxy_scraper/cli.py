"""Command-line entry point: `uv run python -m oxy_scraper <command>`."""

import argparse
import logging
from collections.abc import Sequence

from oxy_scraper import paths
from oxy_scraper.client import CountsClient
from oxy_scraper.exclusions import load_exclusions
from oxy_scraper.fetch import AbortRun, Fetcher
from oxy_scraper.parsed import parse_terms
from oxy_scraper.store import RawStore

log = logging.getLogger("oxy_scraper")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="oxy_scraper",
        description="Scrape counts.oxy.edu and import the course catalog.",
    )
    commands = parser.add_subparsers(dest="command", metavar="<command>")

    fetch = commands.add_parser(
        "fetch", help="download list and detail pages into data/raw (cached, resumable)"
    )
    fetch.add_argument(
        "--terms", help="comma-separated term codes, e.g. 202602,202603 (default: all listed)"
    )
    fetch.add_argument(
        "--refresh", action="store_true", help="re-download lists of the chosen terms"
    )
    fetch.add_argument(
        "--delay", type=float, default=1.0, help="minimum seconds between requests (default 1.0)"
    )
    fetch.add_argument("--skip-details", action="store_true", help="only fetch list pages")
    fetch.add_argument(
        "--dry-run", action="store_true", help="fetch lists, then only report pending details"
    )
    parse = commands.add_parser(
        "parse", help="turn data/raw into data/parsed/<term>.json (offline)"
    )
    parse.add_argument(
        "--terms", help="comma-separated term codes (default: every term in data/raw)"
    )
    return parser


def run_parse(args: argparse.Namespace) -> int:
    store = RawStore(paths.RAW_DIR)
    cached = store.cached_terms()
    chosen = args.terms.split(",") if args.terms else cached
    unknown = [t for t in chosen if t not in cached]
    if unknown:
        log.error("no raw data for term(s): %s (run fetch first)", ", ".join(unknown))
        return 2
    summaries = parse_terms(store, paths.PARSED_DIR, chosen)
    log.info(
        "done: %d terms, %d sections -> %s",
        len(summaries),
        sum(s.sections for s in summaries),
        paths.PARSED_DIR,
    )
    return 0


def run_fetch(args: argparse.Namespace) -> int:
    store = RawStore(paths.RAW_DIR)
    with CountsClient(min_interval=args.delay) as client:
        fetcher = Fetcher(client, store, load_exclusions())
        try:
            listed = fetcher.fetch_terms()
            labels = dict(listed)
            chosen = args.terms.split(",") if args.terms else [code for code, _ in listed]
            unknown = [t for t in chosen if t not in labels]
            if unknown:
                log.error("unknown term code(s): %s", ", ".join(unknown))
                return 2
            metas = [fetcher.fetch_lists(t, labels[t], refresh=args.refresh) for t in chosen]
            failed_lists = sum(len(m.failed_subjects) for m in metas)
            if not args.skip_details:
                fetcher.fetch_all_details(chosen, dry_run=args.dry_run)
        except AbortRun as exc:
            log.error("%s", exc)
            return 1
        log.info(
            "done: %d requests, %d failed subject lists, %d failed details",
            client.requests_made,
            failed_lists,
            len(fetcher.failed_details),
        )
        return 1 if failed_lists or fetcher.failed_details else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per request is too noisy
    if args.command == "fetch":
        return run_fetch(args)
    if args.command == "parse":
        return run_parse(args)
    parser.print_help()
    return 0

"""Command-line entry point: `uv run python -m oxy_scraper <command>`."""

import argparse
import logging
from collections.abc import Sequence

from oxy_scraper import paths
from oxy_scraper.client import CountsClient
from oxy_scraper.exclusions import load_exclusions
from oxy_scraper.fetch import AbortRun, Fetcher
from oxy_scraper.load import (
    CatalogDiff,
    TooManyRemovals,
    load_catalog,
    read_catalog,
    write_diff_reports,
)
from oxy_scraper.normalize import Normalizer, load_parsed, write_result
from oxy_scraper.overrides import load_overrides
from oxy_scraper.parsed import parse_terms
from oxy_scraper.store import RawStore
from oxy_scraper.sync import sync

log = logging.getLogger("oxy_scraper")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="oxy_scraper",
        description="Scrape counts.oxy.edu and import the course catalog.",
    )
    commands = parser.add_subparsers(dest="command", metavar="<command>")

    update = commands.add_parser(
        "update",
        help="bring data/raw up to date with the site (changed and new terms), then parse, "
        "normalize and report what an import would change (writes nothing to the database)",
    )
    update.add_argument(
        "--terms",
        help="comma-separated term codes to re-download (default: new and changed terms of "
        "the current academic year and later)",
    )
    update.add_argument("--all", action="store_true", help="re-download every term the site lists")
    fetch = commands.add_parser(
        "fetch",
        help="download what data/raw is missing (first download; cached, resumable)",
    )
    fetch.add_argument(
        "--terms", help="comma-separated term codes, e.g. 202602,202603 (default: all listed)"
    )
    for p in (update, fetch):
        p.add_argument(
            "--delay",
            type=float,
            default=1.0,
            help="minimum seconds between requests (default 1.0)",
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
    commands.add_parser(
        "normalize",
        help="group data/parsed into courses/sections/professors (data/normalized) and write "
        "review reports (data/reports)",
    )
    load = commands.add_parser(
        "load",
        help="make the Postgres catalog tables match data/normalized (one transaction) and "
        "write the changes to data/reports/update/",
    )
    load.add_argument(
        "--dry-run", action="store_true", help="only report the changes, write nothing"
    )
    load.add_argument(
        "--max-removed",
        type=float,
        default=0.2,
        help="refuse to delete more than this share of a term's sections (default 0.2)",
    )
    load.add_argument("--force", action="store_true", help="import even past --max-removed")
    return parser


def run_load(*, dry_run: bool = False, max_removed: float = 0.2, force: bool = False) -> int:
    from app.db.session import SessionLocal  # connects to DATABASE_URL; only needed here

    if not (paths.NORMALIZED_DIR / "courses.json").exists():
        log.error("no data in %s (run normalize first)", paths.NORMALIZED_DIR)
        return 2
    catalog = read_catalog(paths.NORMALIZED_DIR)
    with SessionLocal() as session:

        def report(diff: CatalogDiff) -> None:
            folder = write_diff_reports(
                session, diff, paths.REPORTS_DIR / "update", max_removed=max_removed
            )
            log.info("changes (+added ~changed -deleted): %s", diff.summary())
            log.info("details: %s", folder)

        try:
            load_catalog(
                session,
                catalog,
                max_removed=max_removed,
                force=force,
                dry_run=dry_run,
                on_diff=report,
            )
        except TooManyRemovals as exc:
            log.error("%s", exc)
            return 1
        if dry_run:
            log.info("dry run: database not changed (import with `make import`)")
            return 0
        session.commit()
    log.info("database updated")
    return 0


def run_normalize() -> int:
    parsed = load_parsed(paths.PARSED_DIR)
    if not parsed:
        log.error("no files in %s (run parse first)", paths.PARSED_DIR)
        return 2
    result = Normalizer(parsed, load_exclusions(), load_overrides()).run()
    write_result(result, paths.NORMALIZED_DIR, paths.REPORTS_DIR)
    log.info(
        "done: %d terms, %d departments, %d courses, %d sections, %d professors -> %s",
        len(result.terms),
        len(result.departments),
        len(result.courses),
        len(result.sections),
        len(result.professors),
        paths.NORMALIZED_DIR,
    )
    for name, (_, rows) in result.reports.items():
        log.info("report %s: %d rows", name, len(rows))
    return 0


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
            metas = [fetcher.fetch_lists(t, labels[t]) for t in chosen]
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


def run_update(args: argparse.Namespace) -> int:
    main_store, staging = RawStore(paths.RAW_DIR), RawStore(paths.STAGING_DIR)
    with CountsClient(min_interval=args.delay) as client:
        try:
            result = sync(
                client,
                main_store,
                staging,
                load_exclusions(),
                terms=args.terms.split(",") if args.terms else None,
                everything=args.all,
            )
        except (AbortRun, ValueError) as exc:
            log.error("%s", exc)
            return 1
        log.info("%d requests", client.requests_made)
    if result.failed:
        return 1
    for term in result.refreshed:
        log.info("re-downloaded %s (%s)", term, result.reasons[term])
    log.info("unchanged: %s", ", ".join(result.unchanged) or "-")
    if result.skipped:
        log.info("not checked (older academic years; use --all): %s", ", ".join(result.skipped))
    # Parse every saved term, so all parsed files come from the current parser.
    parse_terms(main_store, paths.PARSED_DIR, main_store.cached_terms())
    status = run_normalize()
    if status:
        return status
    return run_load(dry_run=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per request is too noisy
    if args.command == "update":
        return run_update(args)
    if args.command == "fetch":
        return run_fetch(args)
    if args.command == "parse":
        return run_parse(args)
    if args.command == "normalize":
        return run_normalize()
    if args.command == "load":
        return run_load(dry_run=args.dry_run, max_removed=args.max_removed, force=args.force)
    parser.print_help()
    return 0

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import db
from .aea import (
    apply_issue_calendar,
    clean_truncated_aea_abstracts,
    fix_issue_months,
    harvest_aea,
)
from .authors import resolve_all_authors
from .career import assign_cv_careers, assign_orcid_careers, infer_byline_career
from .classify import classify_papers
from .cv import (
    collect_orcid_urls,
    discover_cv_links,
    fetch_cv_documents,
    parse_cv_sources,
    queue_landing_links,
)
from .config import DB_PATH, LOGS_DIR, REPORTS_DIR
from .coverage import generate_m6_report
from .crossref import harvest
from .identity import ensure_identity_ledger
from .openalex import (
    apply_author_links,
    clean_openalex_abstracts,
    enrich_openalex,
    merge_openalex_supported_authors,
)
from .orcid import (
    apply_openalex_orcids,
    assign_author_orcids,
    fetch_orcid_records,
    revalidate_orcid_records,
)
from .pages import normalize_page_ranges
from .quality import generate_m3_report, generate_m4_report, generate_report
from .review import resolve_merge_candidates, resolve_multi_id_authors


def link_openalex_authors(conn) -> None:
    stats = apply_author_links(conn)
    print(f"Author OpenAlex links: {stats}")
    merge_stats = merge_openalex_supported_authors(conn)
    print(f"OpenAlex-supported merges: {merge_stats}")
    if merge_stats.get("merged"):
        print(f"Author OpenAlex links (post-merge): {apply_author_links(conn)}")


def setup_logging() -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOGS_DIR / "econpub.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_path, encoding="utf-8"),
        ],
        force=True,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="econpub", description="EconPub data pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    harvest_parser = subparsers.add_parser("harvest", help="Harvest Crossref metadata")
    harvest_parser.add_argument("--rows", type=int, default=1000)
    harvest_parser.add_argument("--max-pages", type=int)
    harvest_parser.add_argument("--resume", action="store_true")
    harvest_parser.add_argument("--refresh", action="store_true")
    harvest_parser.add_argument("--db", type=Path, default=DB_PATH)

    report_parser = subparsers.add_parser("report", help="Generate the M1 quality report")
    report_parser.add_argument("--db", type=Path, default=DB_PATH)

    all_parser = subparsers.add_parser("all", help="Harvest, then generate the report")
    all_parser.add_argument("--rows", type=int, default=1000)
    all_parser.add_argument("--max-pages", type=int)
    all_parser.add_argument("--resume", action="store_true")
    all_parser.add_argument("--refresh", action="store_true")
    all_parser.add_argument("--db", type=Path, default=DB_PATH)

    aea_parser = subparsers.add_parser(
        "aea", help="Fetch AEA article pages for JEL codes, abstracts, and issue months"
    )
    aea_parser.add_argument("--limit", type=int)
    aea_parser.add_argument("--year-from", type=int)
    aea_parser.add_argument("--year-to", type=int)
    aea_parser.add_argument("--resume", action="store_true")
    aea_parser.add_argument("--refresh", action="store_true")
    aea_parser.add_argument("--delay", type=float, default=0.5)
    aea_parser.add_argument("--workers", type=int, default=1)
    aea_parser.add_argument("--db", type=Path, default=DB_PATH)

    openalex_parser = subparsers.add_parser(
        "openalex", help="Enrich works and authors with DOI-keyed OpenAlex metadata"
    )
    openalex_parser.add_argument("--limit", type=int)
    openalex_parser.add_argument("--batch-size", type=int, default=50)
    openalex_parser.add_argument("--resume", action="store_true")
    openalex_parser.add_argument("--refresh", action="store_true")
    openalex_parser.add_argument("--db", type=Path, default=DB_PATH)

    m2_parser = subparsers.add_parser(
        "m2",
        help="Run issue-month fixes, AEA JEL/abstract crawl, OpenAlex enrichment, and report",
    )
    m2_parser.add_argument("--limit", type=int)
    m2_parser.add_argument("--batch-size", type=int, default=50)
    m2_parser.add_argument("--year-from", type=int)
    m2_parser.add_argument("--year-to", type=int)
    m2_parser.add_argument("--resume", action="store_true")
    m2_parser.add_argument("--refresh", action="store_true")
    m2_parser.add_argument("--delay", type=float, default=0.5)
    m2_parser.add_argument("--workers", type=int, default=1)
    m2_parser.add_argument("--skip-aea", action="store_true")
    m2_parser.add_argument("--skip-openalex", action="store_true")
    m2_parser.add_argument("--db", type=Path, default=DB_PATH)

    pages_parser = subparsers.add_parser(
        "pages", help="Expand abbreviated page ranges in the existing corpus"
    )
    pages_parser.add_argument("--db", type=Path, default=DB_PATH)

    calendar_parser = subparsers.add_parser(
        "calendar", help="Apply the AEA all-issues cover-month calendar"
    )
    calendar_parser.add_argument("--refresh", action="store_true")
    calendar_parser.add_argument("--db", type=Path, default=DB_PATH)

    m3_parser = subparsers.add_parser(
        "m3",
        help="Stabilise author identity, resolve OpenAlex review cases, and infer byline careers",
    )
    m3_parser.add_argument("--db", type=Path, default=DB_PATH)

    m4_parser = subparsers.add_parser(
        "m4",
        help="Enrich ORCID employment/education timelines and infer career stages",
    )
    m4_parser.add_argument("--limit", type=int)
    m4_parser.add_argument("--workers", type=int, default=4)
    m4_parser.add_argument("--refresh", action="store_true")
    m4_parser.add_argument("--skip-orcid", action="store_true")
    m4_parser.add_argument("--db", type=Path, default=DB_PATH)

    cvs_parser = subparsers.add_parser(
        "cvs",
        help="Discover public CVs/faculty pages and extract dated career events",
    )
    cvs_parser.add_argument("--limit", type=int)
    cvs_parser.add_argument("--workers", type=int, default=4)
    cvs_parser.add_argument("--refresh", action="store_true")
    cvs_parser.add_argument("--retry-failed", action="store_true")
    cvs_parser.add_argument("--skip-seed", action="store_true")
    cvs_parser.add_argument("--skip-discover", action="store_true")
    cvs_parser.add_argument("--skip-fetch", action="store_true")
    cvs_parser.add_argument("--skip-parse", action="store_true")
    cvs_parser.add_argument("--skip-careers", action="store_true")
    cvs_parser.add_argument("--db", type=Path, default=DB_PATH)

    wayback_parser = subparsers.add_parser(
        "wayback",
        help="Collect archive.org faculty-page snapshots and infer historical ranks",
    )
    wayback_parser.add_argument("--limit", type=int, default=250)
    wayback_parser.add_argument("--max-years", type=int, default=3)
    wayback_parser.add_argument("--workers", type=int, default=3)
    wayback_parser.add_argument("--skip-collect", action="store_true")
    wayback_parser.add_argument("--skip-fetch", action="store_true")
    wayback_parser.add_argument("--skip-parse", action="store_true")
    wayback_parser.add_argument("--db", type=Path, default=DB_PATH)

    serve_parser = subparsers.add_parser(
        "serve",
        help="Run the read-only JSON API for the frontend",
    )
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8000)
    serve_parser.add_argument("--reload", action="store_true")
    serve_parser.add_argument("--db", type=Path, default=DB_PATH)

    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    setup_logging()
    if args.command == "serve":
        try:
            import uvicorn
        except ImportError as exc:
            raise RuntimeError(
                "The API server needs FastAPI and Uvicorn. "
                "Install them with: pip install -e '.[api]'"
            ) from exc
        from .api import create_app

        if args.reload:
            import os

            os.environ["ECONPUB_DB"] = str(args.db)
            uvicorn.run(
                "econpub.api:app",
                host=args.host,
                port=args.port,
                reload=True,
            )
        else:
            uvicorn.run(
                create_app(args.db),
                host=args.host,
                port=args.port,
            )
        return
    conn = db.connect(args.db)
    db.init_db(conn)
    try:
        if args.command in {"harvest", "all"}:
            harvest(
                conn,
                rows=args.rows,
                max_pages=args.max_pages,
                resume=args.resume,
                refresh=args.refresh,
            )
            classification = classify_papers(conn)
            author_stats = resolve_all_authors(conn)
            print(f"Classification: {classification}")
            print(f"Authors: {author_stats}")

        elif args.command in {"aea", "openalex", "m2", "pages", "calendar", "m3", "m4", "cvs"}:
            # M1 must exist before enrichment. Rebuilding authors would erase
            # OpenAlex links and review evidence, so only do it on an empty
            # author layer.
            if conn.execute("SELECT COUNT(*) FROM authors").fetchone()[0] == 0:
                classification = classify_papers(conn)
                author_stats = resolve_all_authors(conn)
                print(f"Classification: {classification}")
                print(f"Authors: {author_stats}")

        if args.command == "aea":
            resume = args.resume or not args.refresh
            print(f"Issue calendar: {apply_issue_calendar(conn, refresh=args.refresh)}")
            print(
                "AEA:",
                harvest_aea(
                    conn,
                    limit=args.limit,
                    year_from=args.year_from,
                    year_to=args.year_to,
                    resume=resume,
                    refresh=args.refresh,
                    request_interval=args.delay,
                    workers=args.workers,
                ),
            )
            print(f"AEA abstract cleanup: {clean_truncated_aea_abstracts(conn)}")
        elif args.command == "openalex":
            resume = args.resume or not args.refresh
            print(
                "OpenAlex:",
                enrich_openalex(
                    conn,
                    limit=args.limit,
                    batch_size=args.batch_size,
                    resume=resume,
                    refresh=args.refresh,
                ),
            )
            print(f"Abstract cleanup: {clean_openalex_abstracts(conn)}")
            link_openalex_authors(conn)
        elif args.command == "pages":
            print(f"Page ranges: {normalize_page_ranges(conn)}")
        elif args.command == "calendar":
            print(f"Issue calendar: {apply_issue_calendar(conn, refresh=args.refresh)}")
        elif args.command == "m3":
            if conn.execute("SELECT COUNT(*) FROM authors").fetchone()[0] == 0:
                raise RuntimeError("No authors found; run `python run.py all` and `m2` first")
            print(f"Stable IDs: {ensure_identity_ledger(conn)}")
            print(f"OpenAlex author links: {apply_author_links(conn)}")
            print(f"OpenAlex-supported merges: {merge_openalex_supported_authors(conn)}")
            print(f"Merge candidates: {resolve_merge_candidates(conn)}")
            print(f"Multi-ID review: {resolve_multi_id_authors(conn)}")
            print(f"Career: {infer_byline_career(conn)}")
            markdown_path, metrics_path = generate_m3_report(conn)
            print(f"Report:  {markdown_path}")
            print(f"Metrics: {metrics_path}")
        elif args.command == "m4":
            if conn.execute("SELECT COUNT(*) FROM authors").fetchone()[0] == 0:
                raise RuntimeError("No authors found; run `python run.py all`, `m2`, and `m3` first")
            print(f"Byline careers: {infer_byline_career(conn)}")
            print(f"OpenAlex ORCIDs: {apply_openalex_orcids(conn)}")
            print(f"Author ORCIDs: {assign_author_orcids(conn)}")
            if not args.skip_orcid:
                print(
                    "ORCID:",
                    fetch_orcid_records(
                        conn,
                        limit=args.limit,
                        workers=args.workers,
                        refresh=args.refresh,
                    ),
                )
            print(f"ORCID validation: {revalidate_orcid_records(conn)}")
            print(f"ORCID careers: {assign_orcid_careers(conn)}")
            markdown_path, metrics_path = generate_m4_report(conn)
            print(f"Report:  {markdown_path}")
            print(f"Metrics: {metrics_path}")
        elif args.command == "cvs":
            if conn.execute("SELECT COUNT(*) FROM authors").fetchone()[0] == 0:
                raise RuntimeError("No authors found; run `all`, `m2`, `m3`, and `m4` first")
            if not args.skip_seed:
                print(f"CV seed URLs: {collect_orcid_urls(conn)}")
            if not args.skip_discover:
                print(
                    "CV links:",
                    discover_cv_links(
                        conn,
                        limit=args.limit,
                        workers=args.workers,
                        refresh=args.refresh,
                        retry_failed=args.retry_failed,
                    ),
                )
            if not args.skip_fetch:
                print(f"CV landing links: {queue_landing_links(conn, limit=args.limit)}")
                print(f"CV documents: {fetch_cv_documents(conn, limit=args.limit, workers=args.workers)}")
            if not args.skip_parse:
                print(f"CV parse: {parse_cv_sources(conn, limit=args.limit)}")
            if not args.skip_careers:
                print(f"CV careers: {assign_cv_careers(conn)}")
            markdown_path, metrics_path = generate_m4_report(conn)
            print(f"Report:  {markdown_path}")
            print(f"Metrics: {metrics_path}")
            coverage_path, coverage_metrics = generate_m6_report(conn)
            print(f"Coverage: {coverage_path}")
            print(f"Coverage metrics: {coverage_metrics}")
        elif args.command == "wayback":
            from .wayback import run_wayback

            print(
                "Wayback:",
                run_wayback(
                    conn,
                    limit=args.limit,
                    max_years=args.max_years,
                    workers=args.workers,
                    skip_collect=args.skip_collect,
                    skip_fetch=args.skip_fetch,
                    skip_parse=args.skip_parse,
                ),
            )
            markdown_path, metrics_path = generate_m4_report(conn)
            print(f"Report:  {markdown_path}")
            print(f"Metrics: {metrics_path}")
            coverage_path, coverage_metrics = generate_m6_report(conn)
            print(f"Coverage: {coverage_path}")
            print(f"Coverage metrics: {coverage_metrics}")
        elif args.command == "m2":
            resume = args.resume or not args.refresh
            print(f"Page ranges: {normalize_page_ranges(conn)}")
            print(f"Issue calendar: {apply_issue_calendar(conn, refresh=args.refresh)}")
            print(f"Issue months fallback: {fix_issue_months(conn)}")
            if not args.skip_aea:
                print(
                    "AEA:",
                    harvest_aea(
                        conn,
                        limit=args.limit,
                        year_from=args.year_from,
                        year_to=args.year_to,
                        resume=resume,
                        refresh=args.refresh,
                        request_interval=args.delay,
                        workers=args.workers,
                    ),
                )
                print(f"AEA abstract cleanup: {clean_truncated_aea_abstracts(conn)}")
            if not args.skip_openalex:
                print(
                    "OpenAlex:",
                    enrich_openalex(
                        conn,
                        limit=args.limit,
                        batch_size=args.batch_size,
                        resume=resume,
                        refresh=args.refresh,
                    ),
                )
                print(f"Abstract cleanup: {clean_openalex_abstracts(conn)}")
                link_openalex_authors(conn)

        if args.command in {"m2", "report", "all"}:
            report_path = REPORTS_DIR / ("m2_quality.md" if args.command == "m2" else "m1_quality.md")
            markdown_path, metrics_path = generate_report(conn, path=report_path)
            print(f"Report:  {markdown_path}")
            print(f"Metrics: {metrics_path}")
    finally:
        conn.close()

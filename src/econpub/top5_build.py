from __future__ import annotations

import logging
from typing import Any

from .authors import resolve_all_authors
from .career import assign_orcid_careers
from .classify import classify_papers
from .config import JOURNALS
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
from .review import resolve_merge_candidates, resolve_multi_id_authors
from .top5_report import generate_top5_report

log = logging.getLogger(__name__)


def _has_career_events(conn) -> bool:
    return bool(conn.execute("SELECT COUNT(*) FROM career_events").fetchone()[0])


def build_top5(
    conn,
    *,
    skip_harvest: bool = False,
    skip_openalex: bool = False,
    skip_orcid: bool = False,
    workers: int = 4,
    batch_size: int = 50,
) -> dict[str, Any]:
    """Build or refresh the combined top-five dataset.

    Intended for a fresh database. If career events already exist, the
    author table is not rebuilt (career events are author-keyed); incremental
    ORCID refreshes still update validation and assignments.
    """
    stats: dict[str, Any] = {}
    if not skip_harvest:
        for code in JOURNALS:
            stats[f"harvest_{code}"] = harvest(conn, journal=code, resume=True)

    stats["classify"] = classify_papers(conn)
    can_rebuild = not _has_career_events(conn)
    if can_rebuild:
        stats["authors"] = resolve_all_authors(conn)

    if not skip_openalex:
        openalex_stats = enrich_openalex(conn, batch_size=batch_size, resume=True)
        stats["openalex"] = openalex_stats
        stats["abstract_cleanup"] = clean_openalex_abstracts(conn)
        if openalex_stats.get("authorships_created") and can_rebuild:
            stats["authors_after_backfill"] = resolve_all_authors(conn)

    ensure_identity_ledger(conn)
    stats["author_links"] = apply_author_links(conn)
    stats["merges"] = merge_openalex_supported_authors(conn)
    stats["author_links_post_merge"] = apply_author_links(conn)
    stats["merge_candidates"] = resolve_merge_candidates(conn)
    stats["multi_id"] = resolve_multi_id_authors(conn)

    if not skip_orcid:
        stats["openalex_orcids"] = apply_openalex_orcids(conn)
        stats["author_orcids"] = assign_author_orcids(conn)
        stats["orcid_fetch"] = fetch_orcid_records(conn, workers=workers)
        stats["orcid_validation"] = revalidate_orcid_records(conn)
        stats["orcid_careers"] = assign_orcid_careers(conn)

    markdown_path, metrics_path = generate_top5_report(conn)
    stats["report"] = str(markdown_path)
    stats["metrics"] = str(metrics_path)
    log.info("Top-five build complete: %s", stats)
    return stats

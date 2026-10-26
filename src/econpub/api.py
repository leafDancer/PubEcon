from __future__ import annotations

import json
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import DB_PATH, JOURNALS, START_YEAR
from .network import build_graph, edge_papers, graph_counts, shortest_path
from .normalize import normalize_doi

STAGE_ORDER = [
    "phd_student",
    "postdoc",
    "research_fellow",
    "assistant_professor",
    "associate_professor",
    "full_professor",
    "emeritus",
    "lecturer_other_academic",
    "non_academic",
]

CONFIDENCE_ORDER = {"high": 0, "medium": 1, "low": 2}

_EMAIL_SUFFIX = re.compile(r"\s*\(email:\s*\)\s*", re.IGNORECASE)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = _EMAIL_SUFFIX.sub("", str(value)).strip().strip(",;")
    return text or None


def _pct(part: int | float, total: int | float) -> float:
    return round(100.0 * part / total, 1) if total else 0.0


def _db_path(value: Path | str | None = None) -> Path:
    if value is not None:
        return Path(value)
    return Path(os.environ.get("ECONPUB_DB", DB_PATH))


def _ro_connect(database: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def _paper_columns() -> str:
    return """
        p.paper_id, p.doi, p.title, p.content_type, p.journal_code, p.is_pp, p.volume, p.issue,
        p.page_first, p.page_last, p.published_year, p.published_month,
        p.published_date, p.abstract, p.abstract_available, p.abstract_source,
        p.citation_count, p.openalex_cited_by_count, p.openalex_id,
        p.retraction_status, p.retracts_paper_id, p.retracted_by_paper_id,
        p.date_source, p.date_confidence, p.aea_url, p.url
    """


def _paper_summary(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "doi": row["doi"],
        "title": row["title"],
        "journal": row["journal_code"] or "AER",
        "year": row["published_year"],
        "month": row["published_month"],
        "date": row["published_date"],
        "volume": row["volume"],
        "issue": row["issue"],
        "pages": _pages(row["page_first"], row["page_last"]),
        "is_pp": bool(row["is_pp"]),
        "citation_count": row["citation_count"],
        "openalex_cited_by_count": row["openalex_cited_by_count"],
        "abstract_available": bool(row["abstract_available"]),
        "retraction_status": row["retraction_status"],
        "url": row["url"] or f"https://doi.org/{row['doi']}",
    }


def _pages(first: str | None, last: str | None) -> str | None:
    if first and last:
        return f"{first}–{last}"
    return first or last


def _stage_rank(stage: str | None) -> int:
    try:
        return STAGE_ORDER.index(stage or "")
    except ValueError:
        return len(STAGE_ORDER)


def _confidence_rank(confidence: str | None) -> int:
    return CONFIDENCE_ORDER.get(confidence or "", 3)


def _author_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "stable_id": row["stable_id"],
        "name": row["canonical_name"],
        "orcid": row["orcid"],
        "orcid_source": row["orcid_source"],
        "orcid_confidence": row["orcid_match_confidence"],
        "openalex_id": row["openalex_id"],
        "review_status": row["review_status"],
        "needs_review": bool(row["needs_review"]),
    }


def _paper_authors(conn: sqlite3.Connection, paper_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    if not paper_ids:
        return {}
    placeholders = ",".join("?" for _ in paper_ids)
    rows = conn.execute(
        f"""
        SELECT s.paper_id, s.authorship_id, s.author_order, s.full_name,
               s.affiliation_raw, s.institution_hint, s.rank_raw,
               s.openalex_institution_name, s.institution_source,
               a.stable_id, a.canonical_name, a.orcid,
               ca.stage, ca.evidence_type, ca.confidence AS career_confidence,
               ca.source_url, ca.notes
        FROM authorships s
        LEFT JOIN authors a ON a.author_id=s.author_id
        LEFT JOIN career_assignments ca ON ca.authorship_id=s.authorship_id
        WHERE s.paper_id IN ({placeholders})
        ORDER BY s.paper_id, s.author_order
        """,
        paper_ids,
    ).fetchall()
    grouped: dict[int, list[dict[str, Any]]] = {paper_id: [] for paper_id in paper_ids}
    for row in rows:
        grouped[int(row["paper_id"])].append(
            {
                "stable_id": row["stable_id"],
                "name": row["canonical_name"] or row["full_name"],
                "order": row["author_order"],
                "orcid": row["orcid"],
                "affiliation": _clean(row["affiliation_raw"]),
                "institution": _clean(row["openalex_institution_name"])
                or _clean(row["institution_hint"]),
                "institution_source": row["institution_source"],
                "rank": _clean(row["rank_raw"]),
                "stage": row["stage"],
                "evidence_type": row["evidence_type"],
                "confidence": row["career_confidence"],
                "source_url": row["source_url"],
                "notes": row["notes"],
            }
        )
    return grouped


def _stats_payload(conn: sqlite3.Connection) -> dict[str, Any]:
    counts = conn.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM papers WHERE content_type='article' AND is_duplicate=0) AS papers,
            (SELECT COUNT(*) FROM papers WHERE content_type='article' AND is_duplicate=0 AND is_pp=1) AS pp_papers,
            (SELECT COUNT(*) FROM authors a WHERE EXISTS (
                SELECT 1 FROM authorships s JOIN papers p ON p.paper_id=s.paper_id
                WHERE s.author_id=a.author_id AND p.content_type='article'
                  AND p.is_duplicate=0)) AS authors,
            (SELECT COUNT(*) FROM authorships s JOIN papers p ON p.paper_id=s.paper_id
                WHERE p.content_type='article' AND p.is_duplicate=0) AS authorships,
            (SELECT COUNT(*) FROM coauthorship_edges) AS coauthorship_edges,
            (SELECT COUNT(*) FROM career_assignments) AS career_assignments,
            (SELECT COUNT(*) FROM papers WHERE content_type='article' AND is_duplicate=0
                AND abstract IS NOT NULL AND abstract<>'') AS abstracts,
            (SELECT COUNT(*) FROM authors WHERE orcid IS NOT NULL) AS orcid_authors,
            (SELECT COUNT(*) FROM authors WHERE orcid_source IN
                ('verified_doi','verified_title','verified_institution','field_economics')) AS orcid_accepted,
            (SELECT COUNT(*) FROM authors WHERE orcid_source='orcid_unverified') AS orcid_unverified,
            (SELECT COUNT(*) FROM author_cv_sources) AS cv_sources,
            (SELECT COUNT(*) FROM papers WHERE content_type='article' AND is_duplicate=0
                AND published_year IS NOT NULL) AS dated_papers
        """
    ).fetchone()

    year_rows = conn.execute(
        """
        SELECT p.published_year AS year, COUNT(*) AS papers, SUM(p.is_pp) AS pp
        FROM papers p
        WHERE p.content_type='article' AND p.is_duplicate=0 AND p.published_year IS NOT NULL
        GROUP BY p.published_year
        ORDER BY p.published_year
        """
    ).fetchall()
    year_assignments = conn.execute(
        """
        SELECT p.published_year AS year, COUNT(*) AS assignments,
               COUNT(DISTINCT ca.author_id) AS authors
        FROM career_assignments ca
        JOIN papers p ON p.paper_id=ca.paper_id
        WHERE p.content_type='article' AND p.is_duplicate=0
        GROUP BY p.published_year
        """
    ).fetchall()
    assignment_by_year = {int(row["year"]): dict(row) for row in year_assignments}
    years = []
    for row in year_rows:
        year = int(row["year"])
        extra = assignment_by_year.get(year, {})
        years.append(
            {
                "year": year,
                "papers": row["papers"],
                "pp": row["pp"] or 0,
                "assignments": extra.get("assignments", 0),
                "assigned_authors": extra.get("authors", 0),
                "coverage": _pct(extra.get("assignments", 0), row["papers"]),
            }
        )

    stages = [
        dict(row)
        for row in conn.execute(
            "SELECT stage, COUNT(*) AS n FROM career_assignments GROUP BY stage ORDER BY n DESC"
        )
    ]
    evidence = [
        dict(row)
        for row in conn.execute(
            """
            SELECT evidence_type, confidence, COUNT(*) AS n
            FROM career_assignments
            GROUP BY evidence_type, confidence
            ORDER BY n DESC
            """
        )
    ]
    orcid_tiers = [
        dict(row)
        for row in conn.execute(
            """
            SELECT orcid_source, orcid_match_confidence, COUNT(*) AS n
            FROM authors WHERE orcid IS NOT NULL
            GROUP BY orcid_source, orcid_match_confidence
            ORDER BY n DESC
            """
        )
    ]
    institutions = [
        dict(row)
        for row in conn.execute(
            """
            SELECT i.display_name, i.country, COUNT(*) AS slots
            FROM authorship_institutions ai
            JOIN institutions i ON i.institution_id=ai.institution_id
            JOIN authorships s ON s.authorship_id=ai.authorship_id
            JOIN papers p ON p.paper_id=s.paper_id
            WHERE p.content_type='article' AND p.is_duplicate=0
            GROUP BY i.institution_id
            ORDER BY slots DESC, i.display_name
            LIMIT 12
            """
        )
    ]
    journal_rows = conn.execute(
        """
        SELECT COALESCE(p.journal_code,'AER') AS code,
               COUNT(*) AS papers,
               SUM(CASE WHEN p.abstract IS NOT NULL AND p.abstract<>'' THEN 1 ELSE 0 END) AS abstracts
        FROM papers p
        WHERE p.content_type='article' AND p.is_duplicate=0
        GROUP BY COALESCE(p.journal_code,'AER')
        ORDER BY papers DESC, code
        """
    ).fetchall()
    career_rows = conn.execute(
        """
        SELECT p.journal_code AS code,
               COUNT(*) AS slots,
               SUM(CASE WHEN ca.authorship_id IS NOT NULL THEN 1 ELSE 0 END) AS assignments
        FROM authorships s
        JOIN papers p ON p.paper_id=s.paper_id
        LEFT JOIN career_assignments ca ON ca.authorship_id=s.authorship_id
        WHERE p.content_type='article' AND p.is_duplicate=0
        GROUP BY p.journal_code
        """
    ).fetchall()
    career_by_journal = {row["code"]: row for row in career_rows}
    journals = []
    for row in journal_rows:
        career_row = career_by_journal.get(row["code"])
        slots = career_row["slots"] if career_row else 0
        assignments = career_row["assignments"] if career_row else 0
        journals.append(
            {
                "code": row["code"],
                "name": JOURNALS.get(row["code"]).name
                if row["code"] in JOURNALS
                else row["code"],
                "issn": JOURNALS.get(row["code"]).issn
                if row["code"] in JOURNALS
                else None,
                "papers": row["papers"],
                "abstracts": row["abstracts"] or 0,
                "slots": slots,
                "assignments": assignments,
                "career_coverage": _pct(assignments, slots),
            }
        )
    scope_label = (
        journals[0]["name"] if len(journals) == 1 else "Top five economics journals"
    )
    scope_issn = journals[0]["issn"] if len(journals) == 1 else None
    return {
        "generated_at": _utcnow(),
        "dataset": {
            "journal": scope_label,
            "issn": scope_issn,
            "journals": journals,
            "start_year": START_YEAR,
        },
        "counts": {
            "papers": counts["papers"],
            "pp_papers": counts["pp_papers"],
            "authors": counts["authors"],
            "authorships": counts["authorships"],
            "coauthorship_edges": counts["coauthorship_edges"],
            "career_assignments": counts["career_assignments"],
            "abstracts": counts["abstracts"],
            "orcid_authors": counts["orcid_authors"],
            "orcid_accepted": counts["orcid_accepted"],
            "orcid_unverified": counts["orcid_unverified"],
            "cv_sources": counts["cv_sources"],
        },
        "coverage": {
            "career": _pct(counts["career_assignments"], counts["authorships"]),
            "abstract": _pct(counts["abstracts"], counts["papers"]),
            "orcid": _pct(counts["orcid_authors"], counts["authors"]),
            "dated": _pct(counts["dated_papers"], counts["papers"]),
        },
        "years": years,
        "stages": stages,
        "evidence": evidence,
        "orcid_tiers": orcid_tiers,
        "institutions": institutions,
        "top_authors": _top_authors(conn, limit=10),
        "recent_papers": _recent_papers(conn, limit=6),
        "most_cited": _most_cited(conn, limit=6),
    }


def _top_authors(conn: sqlite3.Connection, limit: int = 10) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT a.stable_id, a.canonical_name, a.orcid_match_confidence,
               COUNT(DISTINCT s.paper_id) AS papers,
               MIN(p.published_year) AS first_year,
               MAX(p.published_year) AS last_year,
               COALESCE(a.openalex_last_institution_name,
                   (SELECT COALESCE(si.openalex_institution_name, si.institution_hint)
                    FROM authorships si JOIN papers pi ON pi.paper_id=si.paper_id
                    WHERE si.author_id=a.author_id AND pi.content_type='article'
                      AND pi.is_duplicate=0
                    ORDER BY pi.published_year DESC, si.author_order LIMIT 1)) AS institution
        FROM authors a
        JOIN authorships s ON s.author_id=a.author_id
        JOIN papers p ON p.paper_id=s.paper_id
        WHERE p.content_type='article' AND p.is_duplicate=0
        GROUP BY a.author_id
        ORDER BY papers DESC, a.canonical_name
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [
        {
            "stable_id": row["stable_id"],
            "name": row["canonical_name"],
            "papers": row["papers"],
            "first_year": row["first_year"],
            "last_year": row["last_year"],
            "institution": _clean(row["institution"]),
            "orcid_confidence": row["orcid_match_confidence"],
        }
        for row in rows
    ]


def _recent_papers(conn: sqlite3.Connection, limit: int = 6) -> list[dict[str, Any]]:
    rows = conn.execute(
        f"""
        SELECT {_paper_columns()}
        FROM papers p
        WHERE p.content_type='article' AND p.is_duplicate=0
        ORDER BY p.published_year DESC, p.published_month DESC, p.doi DESC
        LIMIT ?
        """,
        (limit * 20,),
    ).fetchall()
    # Diversify the front page by journal: the newest row overall is usually
    # AER simply because it has the most papers, which would make a
    # multi-journal record look AER-only.
    selected: list[sqlite3.Row] = []
    used: set[int] = set()
    seen_journals: set[str] = set()
    for row in rows:
        journal = row["journal_code"] or "AER"
        if journal in seen_journals:
            continue
        selected.append(row)
        used.add(int(row["paper_id"]))
        seen_journals.add(journal)
        if len(selected) == limit:
            break
    for row in rows:
        if len(selected) >= limit:
            break
        if int(row["paper_id"]) in used:
            continue
        selected.append(row)
        used.add(int(row["paper_id"]))
    selected.sort(
        key=lambda row: (
            row["published_year"] or 0,
            row["published_month"] or 0,
            row["doi"] or "",
        ),
        reverse=True,
    )
    authors = _paper_authors(conn, [int(row["paper_id"]) for row in selected])
    items = []
    for row in selected:
        item = _paper_summary(row)
        item["authors"] = authors.get(int(row["paper_id"]), [])
        items.append(item)
    return items


def _most_cited(conn: sqlite3.Connection, limit: int = 6) -> list[dict[str, Any]]:
    rows = conn.execute(
        f"""
        SELECT {_paper_columns()}
        FROM papers p
        WHERE p.content_type='article' AND p.is_duplicate=0
        ORDER BY COALESCE(p.openalex_cited_by_count, p.citation_count, 0) DESC,
                 p.published_year DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    authors = _paper_authors(conn, [int(row["paper_id"]) for row in rows])
    items = []
    for row in rows:
        item = _paper_summary(row)
        item["authors"] = authors.get(int(row["paper_id"]), [])
        items.append(item)
    return items


_INSTITUTION_SQL = """
    COALESCE(a.openalex_last_institution_name,
        (SELECT COALESCE(si.openalex_institution_name, si.institution_hint)
         FROM authorships si JOIN papers pi ON pi.paper_id=si.paper_id
         WHERE si.author_id=a.author_id AND pi.content_type='article'
           AND pi.is_duplicate=0
         ORDER BY pi.published_year DESC, si.author_order LIMIT 1))
"""


def _rankings(conn: sqlite3.Connection, limit: int = 10) -> dict[str, Any]:
    assistant = conn.execute(
        f"""
        SELECT a.author_id, a.stable_id, a.canonical_name,
               COUNT(DISTINCT ca.paper_id) AS assistant_papers,
               (SELECT COUNT(DISTINCT s.paper_id)
                FROM authorships s JOIN papers p2 ON p2.paper_id=s.paper_id
                WHERE s.author_id=a.author_id AND p2.content_type='article'
                  AND p2.is_duplicate=0) AS total_papers,
               (SELECT COUNT(DISTINCT ca2.paper_id)
                FROM career_assignments ca2 JOIN papers p3 ON p3.paper_id=ca2.paper_id
                WHERE ca2.author_id=a.author_id AND p3.content_type='article'
                  AND p3.is_duplicate=0) AS known_papers,
               {_INSTITUTION_SQL} AS institution
        FROM authors a
        JOIN career_assignments ca ON ca.author_id=a.author_id
        JOIN papers p ON p.paper_id=ca.paper_id
        WHERE ca.stage='assistant_professor'
          AND ca.confidence IN ('high','medium')
          AND p.content_type='article' AND p.is_duplicate=0
        GROUP BY a.author_id
        ORDER BY assistant_papers DESC, total_papers DESC, a.canonical_name
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    five_journal = conn.execute(
        f"""
        SELECT a.author_id, a.stable_id, a.canonical_name,
               COUNT(DISTINCT p.paper_id) AS papers,
               COUNT(DISTINCT p.journal_code) AS journals,
               GROUP_CONCAT(DISTINCT p.journal_code) AS journal_codes,
               {_INSTITUTION_SQL} AS institution
        FROM authors a
        JOIN authorships s ON s.author_id=a.author_id
        JOIN papers p ON p.paper_id=s.paper_id
        WHERE p.content_type='article' AND p.is_duplicate=0
        GROUP BY a.author_id
        HAVING journals=5
        ORDER BY papers DESC, a.canonical_name
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    coauthors = conn.execute(
        f"""
        WITH pairs AS (
            SELECT author_a_id AS author_id, author_b_id AS other_id
            FROM coauthorship_edges
            UNION ALL
            SELECT author_b_id, author_a_id FROM coauthorship_edges
        )
        SELECT a.author_id, a.stable_id, a.canonical_name,
               COUNT(DISTINCT pairs.other_id) AS coauthors,
               (SELECT COUNT(DISTINCT s.paper_id)
                FROM authorships s JOIN papers p2 ON p2.paper_id=s.paper_id
                WHERE s.author_id=a.author_id AND p2.content_type='article'
                  AND p2.is_duplicate=0) AS papers,
               {_INSTITUTION_SQL} AS institution
        FROM pairs
        JOIN authors a ON a.author_id=pairs.author_id
        GROUP BY a.author_id
        ORDER BY coauthors DESC, papers DESC, a.canonical_name
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    pair_rows = conn.execute(
        f"""
        SELECT e.author_a_id, e.author_b_id,
               COUNT(DISTINCT e.paper_id) AS shared_papers,
               MIN(e.year) AS first_year, MAX(e.year) AS last_year,
               a.stable_id AS a_stable, a.canonical_name AS a_name,
               b.stable_id AS b_stable, b.canonical_name AS b_name,
               COALESCE(a.openalex_last_institution_name,
                   (SELECT COALESCE(si.openalex_institution_name, si.institution_hint)
                    FROM authorships si JOIN papers pi ON pi.paper_id=si.paper_id
                    WHERE si.author_id=a.author_id AND pi.content_type='article'
                      AND pi.is_duplicate=0
                    ORDER BY pi.published_year DESC, si.author_order LIMIT 1)) AS a_institution,
               COALESCE(b.openalex_last_institution_name,
                   (SELECT COALESCE(si.openalex_institution_name, si.institution_hint)
                    FROM authorships si JOIN papers pi ON pi.paper_id=si.paper_id
                    WHERE si.author_id=b.author_id AND pi.content_type='article'
                      AND pi.is_duplicate=0
                    ORDER BY pi.published_year DESC, si.author_order LIMIT 1)) AS b_institution
        FROM coauthorship_edges e
        JOIN authors a ON a.author_id=e.author_a_id
        JOIN authors b ON b.author_id=e.author_b_id
        GROUP BY e.author_a_id, e.author_b_id
        ORDER BY shared_papers DESC, a_name, b_name
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    largest_teams = conn.execute(
        """
        SELECT p.doi, p.title, p.published_year, p.journal_code,
               COUNT(s.authorship_id) AS authors
        FROM papers p
        JOIN authorships s ON s.paper_id=p.paper_id
        WHERE p.content_type='article' AND p.is_duplicate=0
        GROUP BY p.paper_id
        HAVING SUM(CASE WHEN s.openalex_match_method='openalex_backfill' THEN 1 ELSE 0 END)=0
        ORDER BY authors DESC, p.published_year DESC, p.doi
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    longest_careers = conn.execute(
        f"""
        SELECT a.author_id, a.stable_id, a.canonical_name,
               MIN(p.published_year) AS first_year,
               MAX(p.published_year) AS last_year,
               COUNT(DISTINCT p.paper_id) AS papers,
               MAX(p.published_year) - MIN(p.published_year) AS span,
               {_INSTITUTION_SQL} AS institution
        FROM authors a
        JOIN authorships s ON s.author_id=a.author_id
        JOIN papers p ON p.paper_id=s.paper_id
        WHERE p.content_type='article' AND p.is_duplicate=0
          AND p.published_year IS NOT NULL
        GROUP BY a.author_id
        HAVING papers>=2 AND span IS NOT NULL
        ORDER BY span DESC, papers DESC, a.canonical_name
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    institutions = conn.execute(
        """
        SELECT i.display_name, i.country,
               COUNT(DISTINCT ai.authorship_id) AS slots,
               COUNT(DISTINCT s.author_id) AS authors,
               COUNT(DISTINCT p.paper_id) AS papers
        FROM authorship_institutions ai
        JOIN institutions i ON i.institution_id=ai.institution_id
        JOIN authorships s ON s.authorship_id=ai.authorship_id
        JOIN papers p ON p.paper_id=s.paper_id
        WHERE ai.is_primary=1
          AND p.content_type='article' AND p.is_duplicate=0
        GROUP BY i.institution_id
        ORDER BY slots DESC, i.display_name
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    return {
        "assistant_professor": [
            {
                "id": row["stable_id"],
                "name": row["canonical_name"],
                "institution": _clean(row["institution"]),
                "assistant_papers": row["assistant_papers"],
                "papers": row["total_papers"],
                "known_papers": row["known_papers"],
                "coverage": _pct(row["known_papers"], row["total_papers"]),
            }
            for row in assistant
        ],
        "five_journal": [
            {
                "id": row["stable_id"],
                "name": row["canonical_name"],
                "institution": _clean(row["institution"]),
                "papers": row["papers"],
                "journals": row["journals"],
                "journal_codes": sorted(set((row["journal_codes"] or "").split(","))),
            }
            for row in five_journal
        ],
        "most_coauthors": [
            {
                "id": row["stable_id"],
                "name": row["canonical_name"],
                "institution": _clean(row["institution"]),
                "coauthors": row["coauthors"],
                "papers": row["papers"],
            }
            for row in coauthors
        ],
        "strongest_pair": [
            {
                "a": {
                    "id": row["a_stable"],
                    "name": row["a_name"],
                    "institution": _clean(row["a_institution"]),
                },
                "b": {
                    "id": row["b_stable"],
                    "name": row["b_name"],
                    "institution": _clean(row["b_institution"]),
                },
                "shared_papers": row["shared_papers"],
                "first_year": row["first_year"],
                "last_year": row["last_year"],
                "papers": edge_papers(
                    conn,
                    int(row["author_a_id"]),
                    int(row["author_b_id"]),
                    limit=3,
                ),
            }
            for row in pair_rows
        ],
        "largest_teams": [
            {
                "doi": row["doi"],
                "title": row["title"],
                "year": row["published_year"],
                "journal": row["journal_code"] or "AER",
                "authors": row["authors"],
            }
            for row in largest_teams
        ],
        "longest_careers": [
            {
                "id": row["stable_id"],
                "name": row["canonical_name"],
                "institution": _clean(row["institution"]),
                "first_year": row["first_year"],
                "last_year": row["last_year"],
                "papers": row["papers"],
                "span": row["span"],
            }
            for row in longest_careers
        ],
        "institutions": [
            {
                "name": row["display_name"],
                "country": _clean(row["country"]),
                "slots": row["slots"],
                "authors": row["authors"],
                "papers": row["papers"],
            }
            for row in institutions
        ],
        "definitions": {
            "assistant_professor": (
                "Papers with an explicit assistant-professor assignment at high or "
                "medium confidence. Coverage is known-stage papers divided by all "
                "top-five papers."
            ),
            "five_journal": (
                "Authors with at least one research article in each of AER, QJE, "
                "JPE, RES, and ECMA; ranked by total papers."
            ),
            "most_coauthors": (
                "Distinct coauthors across all top-five research articles."
            ),
            "strongest_pair": (
                "Author pairs with the most shared research articles; up to three "
                "papers are shown per pair."
            ),
            "largest_teams": (
                "Research articles with the most authors, across the five journals."
            ),
            "longest_careers": (
                "Authors ranked by the span between their first and last top-five "
                "research articles. This measures activity in these five journals, "
                "not the full academic career."
            ),
            "institutions": (
                "Institutions ranked by primary publish-time author slots. OpenAlex "
                "resolves the institution; coverage varies by journal and the primary "
                "flag is positional, not an employer-of-record claim."
            ),
        },
    }


def _dominant_stages(
    conn: sqlite3.Connection,
    author_ids: list[int],
    year_from: int | None = None,
    year_to: int | None = None,
) -> dict[int, dict[str, Any]]:
    if not author_ids:
        return {}
    placeholders = ",".join("?" for _ in author_ids)
    clauses = [f"ca.author_id IN ({placeholders})"]
    params: list[Any] = list(author_ids)
    if year_from is not None:
        clauses.append("p.published_year >= ?")
        params.append(year_from)
    if year_to is not None:
        clauses.append("p.published_year <= ?")
        params.append(year_to)
    rows = conn.execute(
        f"""
        SELECT ca.author_id, ca.stage, ca.confidence, COUNT(*) AS n
        FROM career_assignments ca
        JOIN papers p ON p.paper_id=ca.paper_id
        WHERE {' AND '.join(clauses)}
        GROUP BY ca.author_id, ca.stage, ca.confidence
        """,
        params,
    ).fetchall()
    grouped: dict[int, dict[str, Any]] = {}
    for row in rows:
        author_id = int(row["author_id"])
        bucket = grouped.setdefault(author_id, {"counts": {}, "confidence": {}})
        bucket["counts"][row["stage"]] = bucket["counts"].get(row["stage"], 0) + row["n"]
        bucket["confidence"][row["stage"]] = min(
            bucket["confidence"].get(row["stage"], "low"),
            row["confidence"],
            key=lambda value: _confidence_rank(value),
        )
    result: dict[int, dict[str, Any]] = {}
    for author_id, bucket in grouped.items():
        stage = max(
            bucket["counts"],
            key=lambda value: (bucket["counts"][value], -_stage_rank(value)),
        )
        result[author_id] = {
            "stage": stage,
            "confidence": bucket["confidence"].get(stage),
            "assignments": bucket["counts"][stage],
        }
    return result


def _author_list_query(
    conn: sqlite3.Connection,
    *,
    q: str | None,
    stage: str | None,
    journal: str | None,
    year_from: int | None,
    year_to: int | None,
    sort: str,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    where = []
    params: list[Any] = []
    if q:
        where.append("a.canonical_name LIKE ?")
        params.append(f"%{q}%")
    if journal:
        where.append(
            """EXISTS (SELECT 1 FROM authorships sj JOIN papers pj ON pj.paper_id=sj.paper_id
                       WHERE sj.author_id=a.author_id AND pj.journal_code=?
                         AND pj.content_type='article' AND pj.is_duplicate=0)"""
        )
        params.append(journal)
    if stage:
        where.append(
            "EXISTS (SELECT 1 FROM career_assignments ca WHERE ca.author_id=a.author_id AND ca.stage=?)"
        )
        params.append(stage)
    if year_from is not None:
        where.append(
            """EXISTS (SELECT 1 FROM authorships sy JOIN papers py ON py.paper_id=sy.paper_id
                       WHERE sy.author_id=a.author_id AND py.content_type='article'
                         AND py.is_duplicate=0 AND py.published_year>=?)"""
        )
        params.append(year_from)
    if year_to is not None:
        where.append(
            """EXISTS (SELECT 1 FROM authorships sy JOIN papers py ON py.paper_id=sy.paper_id
                       WHERE sy.author_id=a.author_id AND py.content_type='article'
                         AND py.is_duplicate=0 AND py.published_year<=?)"""
        )
        params.append(year_to)
    where_sql = " AND ".join(where) if where else "1=1"

    total = conn.execute(
        f"SELECT COUNT(*) FROM authors a WHERE {where_sql}", params
    ).fetchone()[0]

    year_clause = ""
    paper_params: list[Any] = []
    if journal:
        year_clause += " AND p.journal_code=?"
        paper_params.append(journal)
    if year_from is not None:
        year_clause += " AND p.published_year>=?"
        paper_params.append(year_from)
    if year_to is not None:
        year_clause += " AND p.published_year<=?"
        paper_params.append(year_to)

    sort_sql = {
        "papers": "papers DESC, a.canonical_name",
        "name": "a.canonical_name",
        "first_year": "first_year, a.canonical_name",
        "recent": "last_year DESC, a.canonical_name",
    }.get(sort, "papers DESC, a.canonical_name")

    rows = conn.execute(
        f"""
        SELECT a.author_id, a.stable_id, a.canonical_name, a.orcid,
               a.orcid_source, a.orcid_match_confidence, a.openalex_id,
               a.openalex_last_institution_name, a.review_status, a.needs_review,
               COUNT(DISTINCT s.paper_id) AS papers,
               MIN(p.published_year) AS first_year,
               MAX(p.published_year) AS last_year,
               COUNT(DISTINCT ca.paper_id) AS assigned_papers,
               COALESCE(a.openalex_last_institution_name,
                   (SELECT COALESCE(si.openalex_institution_name, si.institution_hint)
                    FROM authorships si JOIN papers pi ON pi.paper_id=si.paper_id
                    WHERE si.author_id=a.author_id AND pi.content_type='article'
                      AND pi.is_duplicate=0
                    ORDER BY pi.published_year DESC, si.author_order LIMIT 1)) AS institution
        FROM authors a
        JOIN authorships s ON s.author_id=a.author_id
        JOIN papers p ON p.paper_id=s.paper_id
            AND p.content_type='article' AND p.is_duplicate=0 {year_clause}
        LEFT JOIN career_assignments ca ON ca.authorship_id=s.authorship_id
        WHERE {where_sql}
        GROUP BY a.author_id
        ORDER BY {sort_sql}
        LIMIT ? OFFSET ?
        """,
        [*paper_params, *params, page_size, (page - 1) * page_size],
    ).fetchall()
    author_ids = [int(row["author_id"]) for row in rows]
    stages = _dominant_stages(conn, author_ids, year_from, year_to)
    items = []
    for row in rows:
        item = _author_from_row(row)
        item.update(
            {
                "papers": row["papers"],
                "first_year": row["first_year"],
                "last_year": row["last_year"],
                "assigned_papers": row["assigned_papers"],
                "coverage": _pct(row["assigned_papers"], row["papers"]),
                "institution": _clean(row["institution"]),
                "stage": stages.get(int(row["author_id"]), {}).get("stage"),
                "career_confidence": stages.get(int(row["author_id"]), {}).get("confidence"),
            }
        )
        items.append(item)
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
    }


def _author_detail(conn: sqlite3.Connection, stable_id: str) -> dict[str, Any]:
    author = conn.execute(
        "SELECT * FROM authors WHERE stable_id=?", (stable_id,)
    ).fetchone()
    if not author:
        raise HTTPException(status_code=404, detail="Author not found")
    author_id = int(author["author_id"])

    stats = conn.execute(
        """
        SELECT COUNT(DISTINCT s.paper_id) AS papers,
               MIN(p.published_year) AS first_year,
               MAX(p.published_year) AS last_year,
               COUNT(DISTINCT ca.paper_id) AS assigned_papers
        FROM authorships s
        JOIN papers p ON p.paper_id=s.paper_id
        LEFT JOIN career_assignments ca ON ca.authorship_id=s.authorship_id
        WHERE s.author_id=? AND p.content_type='article' AND p.is_duplicate=0
        """,
        (author_id,),
    ).fetchone()

    papers = conn.execute(
        """
        SELECT p.doi, p.title, p.journal_code, p.published_year, p.published_month, p.volume, p.issue,
               p.page_first, p.page_last, p.is_pp,
               s.author_order, ca.stage, ca.evidence_type,
               ca.confidence AS career_confidence, ca.notes, ca.source_url
        FROM authorships s
        JOIN papers p ON p.paper_id=s.paper_id
        LEFT JOIN career_assignments ca ON ca.authorship_id=s.authorship_id
        WHERE s.author_id=? AND p.content_type='article' AND p.is_duplicate=0
        ORDER BY p.published_year DESC, p.published_month DESC, p.doi DESC
        """,
        (author_id,),
    ).fetchall()

    events = conn.execute(
        """
        SELECT event_type, title, institution, start_year, end_year, is_current,
               source_type, confidence, source_url, source_snippet
        FROM career_events
        WHERE author_id=?
        ORDER BY (start_year IS NULL), start_year DESC, event_type
        """,
        (author_id,),
    ).fetchall()

    stage_counts = conn.execute(
        "SELECT stage, COUNT(*) AS n FROM career_assignments WHERE author_id=? GROUP BY stage ORDER BY n DESC",
        (author_id,),
    ).fetchall()
    evidence_counts = conn.execute(
        """
        SELECT evidence_type, confidence, COUNT(*) AS n
        FROM career_assignments WHERE author_id=?
        GROUP BY evidence_type, confidence ORDER BY n DESC
        """,
        (author_id,),
    ).fetchall()

    coauthors = conn.execute(
        """
        WITH pairs AS (
            SELECT CASE WHEN author_a_id=? THEN author_b_id ELSE author_a_id END AS other_id,
                   paper_id, year
            FROM coauthorship_edges
            WHERE author_a_id=? OR author_b_id=?
        )
        SELECT a.stable_id, a.canonical_name, a.orcid_match_confidence,
               COUNT(DISTINCT pairs.paper_id) AS shared,
               MIN(pairs.year) AS first_year, MAX(pairs.year) AS last_year
        FROM pairs
        JOIN authors a ON a.author_id=pairs.other_id
        GROUP BY pairs.other_id
        ORDER BY shared DESC, a.canonical_name
        LIMIT 12
        """,
        (author_id, author_id, author_id),
    ).fetchall()
    coauthor_count = conn.execute(
        """
        SELECT COUNT(DISTINCT CASE WHEN author_a_id=? THEN author_b_id ELSE author_a_id END)
        FROM coauthorship_edges WHERE author_a_id=? OR author_b_id=?
        """,
        (author_id, author_id, author_id),
    ).fetchone()[0]

    institutions = conn.execute(
        """
        SELECT i.display_name, i.country, i.ror, COUNT(*) AS slots,
               MIN(p.published_year) AS first_year, MAX(p.published_year) AS last_year
        FROM authorship_institutions ai
        JOIN institutions i ON i.institution_id=ai.institution_id
        JOIN authorships s ON s.authorship_id=ai.authorship_id
        JOIN papers p ON p.paper_id=s.paper_id
        WHERE s.author_id=? AND p.content_type='article' AND p.is_duplicate=0
        GROUP BY i.institution_id
        ORDER BY slots DESC, i.display_name
        """,
        (author_id,),
    ).fetchall()

    return {
        **_author_from_row(author),
        "papers": stats["papers"],
        "first_year": stats["first_year"],
        "last_year": stats["last_year"],
        "assigned_papers": stats["assigned_papers"],
        "coverage": _pct(stats["assigned_papers"], stats["papers"]),
        "institution": _clean(author["openalex_last_institution_name"]),
        "openalex_works_count": author["openalex_works_count"],
        "openalex_cited_by_count": author["openalex_cited_by_count"],
        "career_events": [dict(row) for row in events],
        "paper_list": [
            {
                "doi": row["doi"],
                "title": row["title"],
                "journal": row["journal_code"] or "AER",
                "year": row["published_year"],
                "month": row["published_month"],
                "volume": row["volume"],
                "issue": row["issue"],
                "pages": _pages(row["page_first"], row["page_last"]),
                "is_pp": bool(row["is_pp"]),
                "author_order": row["author_order"],
                "stage": row["stage"],
                "evidence_type": row["evidence_type"],
                "career_confidence": row["career_confidence"],
                "notes": row["notes"],
                "source_url": row["source_url"],
            }
            for row in papers
        ],
        "stage_counts": [dict(row) for row in stage_counts],
        "evidence_counts": [dict(row) for row in evidence_counts],
        "coauthors": [dict(row) for row in coauthors],
        "coauthor_count": coauthor_count,
        "institutions": [dict(row) for row in institutions],
    }


def _paper_detail(conn: sqlite3.Connection, doi: str) -> dict[str, Any]:
    normalized = normalize_doi(doi)
    paper = conn.execute(
        "SELECT * FROM papers WHERE doi=?", (normalized,)
    ).fetchone()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    paper_id = int(paper["paper_id"])
    authors = _paper_authors(conn, [paper_id]).get(paper_id, [])

    author_rows = conn.execute(
        """
        SELECT s.authorship_id, s.author_order, s.full_name
        FROM authorships s WHERE s.paper_id=? ORDER BY s.author_order
        """,
        (paper_id,),
    ).fetchall()
    authorship_ids = [int(row["authorship_id"]) for row in author_rows]
    institutions_by_authorship: dict[int, list[dict[str, Any]]] = {}
    if authorship_ids:
        placeholders = ",".join("?" for _ in authorship_ids)
        rows = conn.execute(
            f"""
            SELECT ai.authorship_id, ai.source, ai.is_primary, ai.raw_name,
                   i.display_name, i.country, i.ror, i.openalex_id
            FROM authorship_institutions ai
            JOIN institutions i ON i.institution_id=ai.institution_id
            WHERE ai.authorship_id IN ({placeholders})
            ORDER BY ai.authorship_id, ai.is_primary DESC, i.display_name
            """,
            authorship_ids,
        ).fetchall()
        for row in rows:
            institutions_by_authorship.setdefault(int(row["authorship_id"]), []).append(
                dict(row)
            )
    # _paper_authors keeps the public shape; reattach authorship-level institutions.
    for author, row in zip(authors, author_rows):
        author["authorship_id"] = int(row["authorship_id"])
        author["institutions"] = institutions_by_authorship.get(
            int(row["authorship_id"]), []
        )

    topics = conn.execute(
        """
        SELECT scheme, code, label, score, is_primary
        FROM paper_topics WHERE paper_id=?
        ORDER BY scheme, is_primary DESC, score DESC, label
        """,
        (paper_id,),
    ).fetchall()
    jel = [
        {"code": row["code"], "label": row["label"]}
        for row in topics
        if row["scheme"] == "jel"
    ]
    openalex_topics = [
        {
            "code": row["code"],
            "label": row["label"],
            "score": row["score"],
            "primary": bool(row["is_primary"]),
        }
        for row in topics
        if row["scheme"] == "openalex_topic"
    ]

    notice = None
    if paper["retracted_by_paper_id"]:
        notice_row = conn.execute(
            "SELECT doi, title FROM papers WHERE paper_id=?",
            (paper["retracted_by_paper_id"],),
        ).fetchone()
        notice = _row(notice_row)

    return {
        **_paper_summary(paper),
        "abstract": paper["abstract"],
        "abstract_source": paper["abstract_source"],
        "authors": authors,
        "jel": jel,
        "topics": openalex_topics,
        "citation_count": paper["citation_count"],
        "openalex_cited_by_count": paper["openalex_cited_by_count"],
        "retraction": {
            "status": paper["retraction_status"],
            "notice": notice,
        }
        if paper["retraction_status"] or notice
        else None,
        "provenance": {
            "date_source": paper["date_source"],
            "date_confidence": paper["date_confidence"],
            "abstract_source": paper["abstract_source"],
            "source_primary": paper["source_primary"],
            "openalex_id": paper["openalex_id"],
            "aea_url": paper["aea_url"],
        },
    }


def _network_nodes(
    conn: sqlite3.Connection,
    author_ids: list[int],
    year_from: int | None,
    year_to: int | None,
    *,
    center_id: int | None = None,
    journal: str | None = None,
) -> list[dict[str, Any]]:
    if not author_ids:
        return []
    placeholders = ",".join("?" for _ in author_ids)
    year_clause = ""
    params: list[Any] = list(author_ids)
    if journal:
        year_clause += " AND p.journal_code=?"
        params.append(journal)
    if year_from is not None:
        year_clause += " AND p.published_year>=?"
        params.append(year_from)
    if year_to is not None:
        year_clause += " AND p.published_year<=?"
        params.append(year_to)
    rows = conn.execute(
        f"""
        SELECT s.author_id, a.stable_id, a.canonical_name, a.orcid_match_confidence,
               COUNT(DISTINCT s.paper_id) AS papers,
               MIN(p.published_year) AS first_year,
               MAX(p.published_year) AS last_year,
               COALESCE(a.openalex_last_institution_name,
                   (SELECT COALESCE(si.openalex_institution_name, si.institution_hint)
                    FROM authorships si JOIN papers pi ON pi.paper_id=si.paper_id
                    WHERE si.author_id=a.author_id AND pi.content_type='article'
                      AND pi.is_duplicate=0
                    ORDER BY pi.published_year DESC, si.author_order LIMIT 1)) AS institution
        FROM authorships s
        JOIN authors a ON a.author_id=s.author_id
        JOIN papers p ON p.paper_id=s.paper_id
        WHERE s.author_id IN ({placeholders})
          AND p.content_type='article' AND p.is_duplicate=0 {year_clause}
        GROUP BY s.author_id
        """,
        params,
    ).fetchall()
    stages = _dominant_stages(conn, author_ids, year_from, year_to)
    result = []
    for row in rows:
        author_id = int(row["author_id"])
        stage = stages.get(author_id, {})
        result.append(
            {
                "id": row["stable_id"],
                "name": row["canonical_name"],
                "papers": row["papers"],
                "first_year": row["first_year"],
                "last_year": row["last_year"],
                "institution": _clean(row["institution"]),
                "stage": stage.get("stage"),
                "confidence": stage.get("confidence") or "unknown",
                "is_center": center_id is not None and author_id == center_id,
            }
        )
    return result


def _network_edges(
    conn: sqlite3.Connection,
    author_ids: list[int],
    year_from: int | None,
    year_to: int | None,
    journal: str | None = None,
) -> list[dict[str, Any]]:
    if len(author_ids) < 2:
        return []
    placeholders = ",".join("?" for _ in author_ids)
    if journal:
        # The precomputed edge table is cross-journal. For a journal-scoped
        # view, derive edges from the selected papers so a tie is a tie in
        # that journal, not a cross-journal aggregate.
        clauses = [
            f"s1.author_id IN ({placeholders})",
            f"s2.author_id IN ({placeholders})",
            "s1.author_id < s2.author_id",
            "p.content_type='article'",
            "p.is_duplicate=0",
            "p.journal_code=?",
        ]
        params: list[Any] = [*author_ids, *author_ids, journal]
        if year_from is not None:
            clauses.append("p.published_year>=?")
            params.append(year_from)
        if year_to is not None:
            clauses.append("p.published_year<=?")
            params.append(year_to)
        rows = conn.execute(
            f"""
            SELECT s1.author_id AS author_a_id, s2.author_id AS author_b_id,
                   COUNT(DISTINCT p.paper_id) AS weight,
                   MIN(p.published_year) AS first_year,
                   MAX(p.published_year) AS last_year
            FROM authorships s1
            JOIN authorships s2
              ON s1.paper_id=s2.paper_id AND s1.author_id < s2.author_id
            JOIN papers p ON p.paper_id=s1.paper_id
            WHERE {' AND '.join(clauses)}
            GROUP BY s1.author_id, s2.author_id
            ORDER BY weight DESC
            """,
            params,
        ).fetchall()
    else:
        clauses = [f"author_a_id IN ({placeholders})", f"author_b_id IN ({placeholders})"]
        params = [*author_ids, *author_ids]
        if year_from is not None:
            clauses.append("year>=?")
            params.append(year_from)
        if year_to is not None:
            clauses.append("year<=?")
            params.append(year_to)
        rows = conn.execute(
            f"""
            SELECT author_a_id, author_b_id, COUNT(DISTINCT paper_id) AS weight,
                   MIN(year) AS first_year, MAX(year) AS last_year
            FROM coauthorship_edges
            WHERE {' AND '.join(clauses)}
            GROUP BY author_a_id, author_b_id
            ORDER BY weight DESC
            """,
            params,
        ).fetchall()
    stable_rows = conn.execute(
        f"SELECT author_id, stable_id FROM authors WHERE author_id IN ({placeholders})",
        author_ids,
    ).fetchall()
    stable = {int(row["author_id"]): row["stable_id"] for row in stable_rows}
    return [
        {
            "source": stable[row["author_a_id"]],
            "target": stable[row["author_b_id"]],
            "weight": row["weight"],
            "first_year": row["first_year"],
            "last_year": row["last_year"],
        }
        for row in rows
        if row["author_a_id"] in stable and row["author_b_id"] in stable
    ]


def _ego_network(
    conn: sqlite3.Connection,
    stable_id: str,
    limit: int,
    journal: str | None = None,
) -> dict[str, Any]:
    center = conn.execute(
        "SELECT author_id, canonical_name FROM authors WHERE stable_id=?", (stable_id,)
    ).fetchone()
    if not center:
        raise HTTPException(status_code=404, detail="Author not found")
    center_id = int(center["author_id"])
    if journal:
        pairs_sql = """
            WITH pairs AS (
                SELECT CASE WHEN s1.author_id=? THEN s2.author_id ELSE s1.author_id END
                           AS other_id,
                       s1.paper_id, p.published_year AS year
                FROM authorships s1
                JOIN authorships s2
                  ON s2.paper_id=s1.paper_id AND s2.author_id<>s1.author_id
                JOIN papers p ON p.paper_id=s1.paper_id
                WHERE (s1.author_id=? OR s2.author_id=?)
                  AND p.content_type='article' AND p.is_duplicate=0
                  AND p.journal_code=?
            )
        """
        neighbors = conn.execute(
            pairs_sql
            + """
            SELECT other_id, COUNT(DISTINCT paper_id) AS shared,
                   MIN(year) AS first_year, MAX(year) AS last_year
            FROM pairs GROUP BY other_id
            ORDER BY shared DESC, other_id
            LIMIT ?
            """,
            (center_id, center_id, center_id, journal, limit),
        ).fetchall()
        total_coauthors = conn.execute(
            pairs_sql + "SELECT COUNT(DISTINCT other_id) FROM pairs",
            (center_id, center_id, center_id, journal),
        ).fetchone()[0]
    else:
        neighbors = conn.execute(
            """
            WITH pairs AS (
                SELECT CASE WHEN author_a_id=? THEN author_b_id ELSE author_a_id END AS other_id,
                       paper_id, year
                FROM coauthorship_edges WHERE author_a_id=? OR author_b_id=?
            )
            SELECT other_id, COUNT(DISTINCT paper_id) AS shared,
                   MIN(year) AS first_year, MAX(year) AS last_year
            FROM pairs GROUP BY other_id
            ORDER BY shared DESC, other_id
            LIMIT ?
            """,
            (center_id, center_id, center_id, limit),
        ).fetchall()
        total_coauthors = conn.execute(
            """
            SELECT COUNT(DISTINCT CASE WHEN author_a_id=? THEN author_b_id ELSE author_a_id END)
            FROM coauthorship_edges WHERE author_a_id=? OR author_b_id=?
            """,
            (center_id, center_id, center_id),
        ).fetchone()[0]
    ids = [center_id, *[int(row["other_id"]) for row in neighbors]]
    nodes = _network_nodes(
        conn, ids, None, None, center_id=center_id, journal=journal
    )
    shared = {
        int(row["other_id"]): {
            "shared": row["shared"],
            "first_year": row["first_year"],
            "last_year": row["last_year"],
        }
        for row in neighbors
    }
    for node in nodes:
        if node["is_center"]:
            continue
        row = conn.execute(
            "SELECT author_id FROM authors WHERE stable_id=?", (node["id"],)
        ).fetchone()
        if row and int(row["author_id"]) in shared:
            info = shared[int(row["author_id"])]
            node["shared"] = info["shared"]
            node["shared_first_year"] = info["first_year"]
            node["shared_last_year"] = info["last_year"]
    edges = _network_edges(conn, ids, None, None, journal=journal)
    return {
        "mode": "ego",
        "focus": stable_id,
        "center": stable_id,
        "nodes": nodes,
        "edges": edges,
        "meta": {
            "selected": len(nodes),
            "total_coauthors": total_coauthors,
            "truncated": total_coauthors > len(neighbors),
            "limit": limit,
            "journal": journal,
        },
    }


def _top_network(
    conn: sqlite3.Connection,
    *,
    year_from: int | None,
    year_to: int | None,
    limit: int,
    min_papers: int,
    journal: str | None = None,
) -> dict[str, Any]:
    clauses = ["p.content_type='article'", "p.is_duplicate=0"]
    params: list[Any] = []
    if journal:
        clauses.append("p.journal_code=?")
        params.append(journal)
    if year_from is not None:
        clauses.append("p.published_year>=?")
        params.append(year_from)
    if year_to is not None:
        clauses.append("p.published_year<=?")
        params.append(year_to)
    base = f"""
        FROM authorships s
        JOIN papers p ON p.paper_id=s.paper_id
        WHERE {' AND '.join(clauses)}
        GROUP BY s.author_id
        HAVING COUNT(DISTINCT s.paper_id)>=?
    """
    total = conn.execute(
        f"SELECT COUNT(*) FROM (SELECT s.author_id {base})", [*params, min_papers]
    ).fetchone()[0]
    rows = conn.execute(
        f"""
        SELECT s.author_id, COUNT(DISTINCT s.paper_id) AS papers
        {base}
        ORDER BY papers DESC, s.author_id
        LIMIT ?
        """,
        [*params, min_papers, limit],
    ).fetchall()
    ids = [int(row["author_id"]) for row in rows]
    nodes = _network_nodes(conn, ids, year_from, year_to, journal=journal)
    edges = _network_edges(conn, ids, year_from, year_to, journal=journal)
    return {
        "mode": "top",
        "nodes": nodes,
        "edges": edges,
        "meta": {
            "year_from": year_from,
            "year_to": year_to,
            "limit": limit,
            "min_papers": min_papers,
            "journal": journal,
            "selected": len(nodes),
            "total_authors": total,
            "truncated": total > len(nodes),
        },
    }


def _network_stats(conn: sqlite3.Connection, journal: str | None) -> dict[str, Any]:
    scope = journal or "ALL"
    row = conn.execute(
        "SELECT * FROM network_statistics WHERE scope=?", (scope,)
    ).fetchone()
    if not row:
        raise HTTPException(
            status_code=404,
            detail=(
                "Network statistics are not cached. Run `python run.py "
                "network-stats` to compute them."
            ),
        )
    details = {}
    if row["details_json"]:
        try:
            details = json.loads(row["details_json"])
        except ValueError:
            details = {}
    return {
        "scope": row["scope"],
        "journal": None if scope == "ALL" else scope,
        "nodes": row["nodes"],
        "edges": row["edges"],
        "components": row["components"],
        "largest_component": row["largest_component"],
        "average_degree": row["average_degree"],
        "average_path_length": row["average_path_length"],
        "diameter": row["diameter"],
        "average_clustering": row["average_clustering"],
        "pairs": row["pairs"],
        "component_sizes": details.get("component_sizes", []),
        "generated_at": row["generated_at"],
        "definition": (
            "Unweighted coauthorship graph. Average path length and diameter are "
            "over unordered pairs in the largest connected component."
        ),
    }


def _author_path(
    conn: sqlite3.Connection,
    from_id: str,
    to_id: str,
    *,
    journal: str | None,
    max_depth: int,
    papers_per_step: int,
) -> dict[str, Any]:
    authors = conn.execute(
        """
        SELECT author_id, stable_id, canonical_name
        FROM authors WHERE stable_id IN (?, ?)
        """,
        (from_id, to_id),
    ).fetchall()
    by_stable = {row["stable_id"]: row for row in authors}
    if from_id not in by_stable:
        raise HTTPException(status_code=404, detail=f"Author not found: {from_id}")
    if to_id not in by_stable:
        raise HTTPException(status_code=404, detail=f"Author not found: {to_id}")
    source = by_stable[from_id]
    target = by_stable[to_id]
    source_author = int(source["author_id"])
    target_author = int(target["author_id"])
    graph = build_graph(conn, journal)
    nodes_count, edges_count = graph_counts(graph)
    path = shortest_path(
        graph, source_author, target_author, max_depth=max_depth
    )
    if path is None:
        source_size = 0
        target_size = 0
        for start, is_source in ((source_author, True), (target_author, False)):
            if start not in graph:
                continue
            seen = {start}
            queue = [start]
            while queue:
                node = queue.pop()
                for neighbor in graph[node]:
                    if neighbor not in seen:
                        seen.add(neighbor)
                        queue.append(neighbor)
            if is_source:
                source_size = len(seen)
            else:
                target_size = len(seen)
        return {
            "found": False,
            "distance": None,
            "journal": journal,
            "from": {"id": from_id, "name": source["canonical_name"]},
            "to": {"id": to_id, "name": target["canonical_name"]},
            "nodes": [],
            "steps": [],
            "meta": {
                "algorithm": "bfs",
                "max_depth": max_depth,
                "graph_nodes": nodes_count,
                "graph_edges": edges_count,
                "source_component_size": source_size,
                "target_component_size": target_size,
            },
        }

    node_rows = _network_nodes(conn, path, None, None, journal=journal)
    node_by_stable = {row["id"]: row for row in node_rows}
    placeholders = ",".join("?" for _ in path)
    id_map = {
        int(row["author_id"]): row["stable_id"]
        for row in conn.execute(
            f"SELECT author_id, stable_id FROM authors WHERE author_id IN ({placeholders})",
            path,
        )
    }
    nodes = [
        node_by_stable.get(
            id_map[author_id],
            {"id": id_map[author_id], "name": None},
        )
        for author_id in path
    ]
    steps = []
    for left, right in zip(path, path[1:]):
        steps.append(
            {
                "from": id_map[left],
                "to": id_map[right],
                "papers": edge_papers(
                    conn,
                    left,
                    right,
                    journal=journal,
                    limit=papers_per_step,
                ),
            }
        )
    return {
        "found": True,
        "distance": len(path) - 1,
        "journal": journal,
        "from": {"id": from_id, "name": source["canonical_name"]},
        "to": {"id": to_id, "name": target["canonical_name"]},
        "nodes": nodes,
        "steps": steps,
        "meta": {
            "algorithm": "bfs",
            "max_depth": max_depth,
            "graph_nodes": nodes_count,
            "graph_edges": edges_count,
            "unique_shortest_path": False,
            "papers_per_step": papers_per_step,
        },
    }


def create_app(
    database: Path | str | None = None,
    *,
    cors_origins: list[str] | None = None,
) -> FastAPI:
    db_path = _db_path(database)
    allowed = cors_origins or [
        value.strip()
        for value in os.environ.get(
            "ECONPUB_CORS_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173",
        ).split(",")
        if value.strip()
    ]
    app = FastAPI(
        title="EconPub API",
        version="0.1.0",
        description="Read-only API for the top five economics journals, 2000+.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed,
        allow_methods=["GET", "OPTIONS"],
        allow_headers=["*"],
    )

    @contextmanager
    def connection() -> Iterator[sqlite3.Connection]:
        if not db_path.exists():
            raise HTTPException(
                status_code=503,
                detail=f"Database not found at {db_path}. Run the M1–M4 pipeline first.",
            )
        conn = _ro_connect(db_path)
        try:
            yield conn
        finally:
            conn.close()

    def get_conn() -> Iterator[sqlite3.Connection]:
        with connection() as conn:
            yield conn

    @app.middleware("http")
    async def cache_headers(request, call_next):
        response = await call_next(request)
        if request.method == "GET" and response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=60"
        return response

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        with connection() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM papers WHERE content_type='article' AND is_duplicate=0"
            ).fetchone()[0]
        return {
            "status": "ok",
            "database": str(db_path),
            "papers": count,
            "generated_at": _utcnow(),
        }

    @app.get("/api/overview")
    def overview() -> dict[str, Any]:
        with connection() as conn:
            return _stats_payload(conn)

    @app.get("/api/stats")
    def stats() -> dict[str, Any]:
        with connection() as conn:
            return _stats_payload(conn)

    @app.get("/api/papers")
    def papers(
        q: str | None = Query(None, max_length=200),
        journal: str | None = Query(None, pattern="^(AER|QJE|JPE|RES|ECMA)$"),
        year_from: int | None = Query(None, ge=START_YEAR, le=2100),
        year_to: int | None = Query(None, ge=START_YEAR, le=2100),
        is_pp: bool | None = None,
        sort: str = Query("year_desc", pattern="^(year_desc|year_asc|cited|title)$"),
        page: int = Query(1, ge=1),
        page_size: int = Query(25, ge=1, le=100),
    ) -> dict[str, Any]:
        with connection() as conn:
            where = ["p.content_type='article'", "p.is_duplicate=0"]
            params: list[Any] = []
            if q:
                where.append(
                    """(p.title LIKE ? OR p.abstract LIKE ?
                        OR EXISTS (SELECT 1 FROM authorships sx JOIN authors ax
                                   ON ax.author_id=sx.author_id
                                   WHERE sx.paper_id=p.paper_id AND ax.canonical_name LIKE ?))"""
                )
                like = f"%{q}%"
                params.extend([like, like, like])
            if journal:
                where.append("p.journal_code=?")
                params.append(journal)
            if year_from is not None:
                where.append("p.published_year>=?")
                params.append(year_from)
            if year_to is not None:
                where.append("p.published_year<=?")
                params.append(year_to)
            if is_pp is not None:
                where.append("p.is_pp=?")
                params.append(1 if is_pp else 0)
            where_sql = " AND ".join(where)
            total = conn.execute(
                f"SELECT COUNT(*) FROM papers p WHERE {where_sql}", params
            ).fetchone()[0]
            order = {
                "year_desc": "p.published_year DESC, p.published_month DESC, p.doi DESC",
                "year_asc": "p.published_year, p.published_month, p.doi",
                "cited": "COALESCE(p.openalex_cited_by_count,p.citation_count,0) DESC, p.published_year DESC",
                "title": "p.title",
            }[sort]
            rows = conn.execute(
                f"""
                SELECT {_paper_columns()}, substr(COALESCE(p.abstract,''),1,320) AS abstract_short
                FROM papers p
                WHERE {where_sql}
                ORDER BY {order}
                LIMIT ? OFFSET ?
                """,
                [*params, page_size, (page - 1) * page_size],
            ).fetchall()
            authors = _paper_authors(conn, [int(row["paper_id"]) for row in rows])
            items = []
            for row in rows:
                item = _paper_summary(row)
                item["abstract_short"] = row["abstract_short"] or None
                item["authors"] = authors.get(int(row["paper_id"]), [])
                items.append(item)
            return {
                "items": items,
                "total": total,
                "page": page,
                "page_size": page_size,
                "pages": (total + page_size - 1) // page_size,
            }

    @app.get("/api/papers/{doi:path}")
    def paper(doi: str) -> dict[str, Any]:
        with connection() as conn:
            return _paper_detail(conn, doi)

    @app.get("/api/authors")
    def authors(
        q: str | None = Query(None, max_length=200),
        stage: str | None = None,
        journal: str | None = Query(None, pattern="^(AER|QJE|JPE|RES|ECMA)$"),
        year_from: int | None = Query(None, ge=START_YEAR, le=2100),
        year_to: int | None = Query(None, ge=START_YEAR, le=2100),
        sort: str = Query("papers", pattern="^(papers|name|first_year|recent)$"),
        page: int = Query(1, ge=1),
        page_size: int = Query(25, ge=1, le=100),
    ) -> dict[str, Any]:
        with connection() as conn:
            return _author_list_query(
                conn,
                q=q,
                stage=stage,
                journal=journal,
                year_from=year_from,
                year_to=year_to,
                sort=sort,
                page=page,
                page_size=page_size,
            )

    @app.get("/api/authors/{stable_id}")
    def author(stable_id: str) -> dict[str, Any]:
        with connection() as conn:
            return _author_detail(conn, stable_id)

    @app.get("/api/authors/{stable_id}/network")
    def author_network(
        stable_id: str,
        limit: int = Query(50, ge=5, le=150),
        journal: str | None = Query(None, pattern="^(AER|QJE|JPE|RES|ECMA)$"),
    ) -> dict[str, Any]:
        with connection() as conn:
            return _ego_network(conn, stable_id, limit, journal=journal)

    @app.get("/api/network")
    def network(
        year_from: int | None = Query(None, ge=START_YEAR, le=2100),
        year_to: int | None = Query(None, ge=START_YEAR, le=2100),
        journal: str | None = Query(None, pattern="^(AER|QJE|JPE|RES|ECMA)$"),
        limit: int = Query(250, ge=20, le=600),
        min_papers: int = Query(2, ge=1, le=20),
    ) -> dict[str, Any]:
        with connection() as conn:
            return _top_network(
                conn,
                year_from=year_from,
                year_to=year_to,
                journal=journal,
                limit=limit,
                min_papers=min_papers,
            )

    @app.get("/api/rankings")
    def rankings(
        limit: int = Query(10, ge=1, le=50),
    ) -> dict[str, Any]:
        with connection() as conn:
            return _rankings(conn, limit)

    @app.get("/api/network/stats")
    def network_stats(
        journal: str | None = Query(None, pattern="^(AER|QJE|JPE|RES|ECMA)$"),
    ) -> dict[str, Any]:
        with connection() as conn:
            return _network_stats(conn, journal)

    @app.get("/api/path")
    def path(
        from_id: str = Query(..., alias="from", min_length=1, max_length=80),
        to_id: str = Query(..., alias="to", min_length=1, max_length=80),
        journal: str | None = Query(None, pattern="^(AER|QJE|JPE|RES|ECMA)$"),
        max_depth: int = Query(10, ge=1, le=20),
        papers_per_step: int = Query(3, ge=1, le=10),
    ) -> dict[str, Any]:
        with connection() as conn:
            return _author_path(
                conn,
                from_id,
                to_id,
                journal=journal,
                max_depth=max_depth,
                papers_per_step=papers_per_step,
            )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(_request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.detail, "status": exc.status_code},
        )

    return app


app = create_app()

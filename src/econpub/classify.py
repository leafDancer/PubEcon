from __future__ import annotations

import json
import logging
import re
import sqlite3
from collections import defaultdict
from typing import Any

from .normalize import (
    name_match_key,
    normalize_doi,
    normalize_issue,
    normalize_name_part,
    page_range,
    page_ranges_overlap,
    title_key,
)

log = logging.getLogger(__name__)

# Exact normalised titles that are AEA administration/editorial matter, not
# research articles. title_key() lowercases, strips punctuation and collapses
# whitespace, so "Editors' Introduction" and "Editor's Introduction" map to the
# two keys below.
ADMIN_EXACT_KEYS = {
    "foreword",
    "editors introduction",
    "editor s introduction",
    "list of online reports",
    "general information on the association",
    "report of independent auditor",
    "abstracts",
}

# These titles are the "Report of the Editor: <journal>" sections, stored by
# Crossref without the prefix.
ADMIN_JOURNAL_KEYS = {
    "american economic review",
    "american economic journal applied economics",
    "american economic journal macroeconomics",
    "american economic journal microeconomics",
    "american economic journal economic policy",
    "journal of economic literature",
    "journal of economic perspectives",
}

ADMIN_CONTAINS_KEYS = (
    "john bates clark award",
    "john bates clark medalist",
)

ROMAN_PAGE_RE = re.compile(r"^[ivxlcdm]+$", re.IGNORECASE)
AUX_TYPES = {"front_matter", "association_report", "unattributed", "retraction_notice"}
TYPE_PRIORITY = {
    "article": 0,
    "erratum": 1,
    "retraction_notice": 2,
    "association_report": 3,
    "front_matter": 4,
    "unattributed": 5,
}

# Confirmed retraction pairs from the M1 audit. The first DOI is the original
# article; the second is the notice. The Crossref update-to/relation fields
# will supersede this list in P1.
RETRACTION_PAIRS = [
    ("10.1257/000282802762024656", "10.1257/aer.97.3.1032"),
    ("10.1257/aer.20210369", "10.1257/aer.113.7.2053"),
]
EXPLICIT_ERRATA = {"10.1257/aer.90.5.1535"}


def classify_papers(conn: sqlite3.Connection) -> dict[str, Any]:
    """Assign content types, identify P&P, retractions, and duplicates."""
    conn.execute(
        """
        UPDATE papers
        SET content_type='article',
            is_pp=0,
            pp_confidence=NULL,
            is_duplicate=0,
            duplicate_of_paper_id=NULL,
            retraction_status=NULL,
            retracts_paper_id=NULL,
            retracted_by_paper_id=NULL
        """
    )
    conn.execute("UPDATE papers SET content_type='issue_metadata' WHERE item_type='journal-issue'")

    # Retraction notices and retracted originals. The original keeps
    # content_type='article' but carries a status so downstream views can
    # exclude it deliberately.
    conn.execute(
        """
        UPDATE papers
        SET content_type='retraction_notice', retraction_status='notice'
        WHERE content_type='article'
          AND LOWER(COALESCE(title,'')) LIKE '%retraction%'
          AND LOWER(COALESCE(title,'')) NOT LIKE 'retracted by the authors%'
        """
    )
    conn.execute(
        """
        UPDATE papers
        SET retraction_status='retracted'
        WHERE content_type='article'
          AND LOWER(COALESCE(title,'')) LIKE 'retracted by the authors%'
        """
    )

    conn.execute(
        """
        UPDATE papers SET content_type='erratum'
        WHERE content_type='article' AND (
            LOWER(COALESCE(title,'')) LIKE '%erratum%'
            OR LOWER(COALESCE(title,'')) LIKE '%corrigendum%'
            OR LOWER(COALESCE(title,'')) LIKE '%correction to%'
        )
        """
    )
    for doi in EXPLICIT_ERRATA:
        conn.execute("UPDATE papers SET content_type='erratum' WHERE doi=?", (doi,))

    # Announcements and prize notices are editorial matter in every journal.
    conn.execute(
        """
        UPDATE papers SET content_type='front_matter'
        WHERE content_type='article' AND (
            LOWER(TRIM(COALESCE(title,''))) IN ('announcement', 'announcements')
            OR LOWER(TRIM(COALESCE(title,''))) LIKE 'announcement of the winners%'
            OR LOWER(TRIM(COALESCE(title,''))) LIKE 'announcements of the winners%'
            OR LOWER(COALESCE(title,'')) LIKE '%call for papers%'
            OR LOWER(COALESCE(title,'')) LIKE '%call for nominations%'
        )
        """
    )

    # AEA reports/minutes already identifiable by prefix. These are AER/AEA
    # section conventions, not a general journal rule.
    conn.execute(
        """
        UPDATE papers SET content_type='association_report'
        WHERE content_type='article' AND COALESCE(journal_code,'AER')='AER' AND (
            LOWER(COALESCE(title,'')) LIKE 'minutes of%'
            OR LOWER(COALESCE(title,'')) LIKE 'report of the%'
            OR LOWER(COALESCE(title,'')) LIKE 'report on the%'
            OR LOWER(COALESCE(title,'')) LIKE 'committee on the status%'
            OR LOWER(COALESCE(title,'')) LIKE '%job openings for economists%'
            OR LOWER(COALESCE(title,'')) LIKE 'information on the association%'
        )
        """
    )

    # Remaining administrative titles: Foreword, Editors' Introduction,
    # "Editor, <journal>", journal-name report sections, award notices.
    # The journal-name keys are AEA-specific, so this pass is AER-only.
    admin_rows = conn.execute(
        "SELECT paper_id, title FROM papers "
        "WHERE content_type='article' AND COALESCE(journal_code,'AER')='AER'"
    ).fetchall()
    for row in admin_rows:
        key = title_key(row["title"])
        if not key:
            continue
        if (
            key in ADMIN_EXACT_KEYS
            or key in ADMIN_JOURNAL_KEYS
            or key.startswith("editor ")
            or any(term in key for term in ADMIN_CONTAINS_KEYS)
        ):
            conn.execute(
                "UPDATE papers SET content_type='association_report' WHERE paper_id=?",
                (row["paper_id"],),
            )

    # Roman-numeral page ranges are administrative paratext in this corpus.
    roman_rows = conn.execute(
        """
        SELECT p.paper_id, p.page_first,
               EXISTS(SELECT 1 FROM authorships a WHERE a.paper_id=p.paper_id) AS has_authors
        FROM papers p
        WHERE p.content_type='article' AND p.page_first IS NOT NULL
        """
    ).fetchall()
    for row in roman_rows:
        if ROMAN_PAGE_RE.match(str(row["page_first"]).strip()):
            new_type = "association_report" if row["has_authors"] else "front_matter"
            conn.execute(
                "UPDATE papers SET content_type=? WHERE paper_id=?",
                (new_type, row["paper_id"]),
            )

    conn.execute(
        """
        UPDATE papers SET content_type='front_matter'
        WHERE content_type='article' AND (
            title IS NULL OR TRIM(title)=''
            OR LOWER(TRIM(title)) = 'front matter'
            OR LOWER(COALESCE(title,'')) LIKE 'front matter%'
            OR LOWER(COALESCE(title,'')) LIKE '%back matter%'
            OR LOWER(TRIM(COALESCE(title,''))) IN (
                'editorial board', 'editorial board.', 'subscription page',
                'table of content', 'table of contents', 'contents',
                'front cover', 'back cover', 'referee', 'referee list',
                'masthead', 'cover', 'title page', 'acknowledgements',
                'acknowledgments'
            )
            OR LOWER(COALESCE(title,'')) LIKE '%front cover%'
            OR LOWER(COALESCE(title,'')) LIKE 'contents for volume%'
            OR LOWER(COALESCE(title,'')) LIKE 'referee list%'
            OR LOWER(COALESCE(title,'')) LIKE '%acknowledg%referee%'
            OR LOWER(COALESCE(title,'')) LIKE '%gratefully acknowledges%'
        )
        """
    )
    conn.execute(
        """
        UPDATE papers SET content_type='front_matter'
        WHERE content_type='article' AND COALESCE(journal_code,'AER')='AER' AND (
            LOWER(TRIM(COALESCE(title,''))) = 'the american economic review'
            OR LOWER(COALESCE(title,'')) LIKE 'american economic association%'
            OR LOWER(COALESCE(title,'')) LIKE 'the american economic association%'
            OR LOWER(COALESCE(title,'')) LIKE '%minutes of the annual meeting%'
            OR LOWER(COALESCE(title,'')) LIKE '%report of the editor%'
            OR LOWER(COALESCE(title,'')) LIKE '%report of the secretary%'
            OR LOWER(COALESCE(title,'')) LIKE '%report of the treasurer%'
            OR LOWER(COALESCE(title,'')) LIKE '%universal academic questionnaire%'
        )
        """
    )

    conn.execute(
        """
        UPDATE papers SET content_type='unattributed'
        WHERE content_type='article'
          AND retraction_status IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM authorships a WHERE a.paper_id = papers.paper_id
          )
        """
    )

    pp_candidates = conn.execute(
        """
        SELECT published_year AS year, volume, issue, COUNT(*) AS n
        FROM papers
        WHERE content_type='article'
          AND COALESCE(journal_code,'AER')='AER'
          AND published_year BETWEEN 2000 AND 2017
          AND volume IS NOT NULL
          AND issue IS NOT NULL
        GROUP BY published_year, volume, issue
        HAVING COUNT(*) >= 50
           AND SUM(CASE WHEN published_month IN (4, 5) THEN 1 ELSE 0 END) * 1.0 / COUNT(*) >= 0.5
        ORDER BY published_year, n DESC
        """
    ).fetchall()

    chosen: dict[int, Any] = {}
    for row in pp_candidates:
        chosen.setdefault(row["year"], row)

    for year, row in chosen.items():
        conn.execute(
            """
            UPDATE papers SET is_pp=1, pp_confidence=?
            WHERE content_type='article'
              AND COALESCE(journal_code,'AER')='AER'
              AND published_year=?
              AND volume=?
              AND issue=?
            """,
            (
                f"issue_cluster: largest spring issue in {year} ({row['n']} articles)",
                year,
                row["volume"],
                row["issue"],
            ),
        )

    crossref_retractions = link_retractions_from_crossref(conn)
    _link_retractions(conn)
    duplicates = detect_duplicates(conn)
    conn.commit()

    content_types = {
        row["content_type"]: row["n"]
        for row in conn.execute("SELECT content_type, COUNT(*) AS n FROM papers GROUP BY 1")
    }
    result = {
        "content_types": content_types,
        "pp_years": sorted(chosen),
        "duplicates": duplicates,
        "crossref_retractions": crossref_retractions,
    }
    log.info(
        "Classified records: %s; P&P years: %s; duplicates: %s",
        content_types,
        sorted(chosen),
        duplicates,
    )
    return result


def link_retractions_from_crossref(conn: sqlite3.Connection) -> int:
    """Link retraction notices using Crossref's ``update-to`` field.

    The two AER retractions are also listed explicitly as a fallback, but the
    Crossref relation is the source of record and is checked first.
    """
    links = 0
    rows = conn.execute(
        "SELECT source_key, payload_json FROM source_records WHERE source='crossref'"
    ).fetchall()
    for row in rows:
        try:
            payload = json.loads(row["payload_json"])
        except (TypeError, ValueError):
            continue
        updates = payload.get("update-to") or []
        for update in updates:
            if str(update.get("type") or "").lower() != "retraction":
                continue
            notice_doi = normalize_doi(row["source_key"])
            original_doi = normalize_doi(update.get("DOI"))
            if not notice_doi or not original_doi:
                continue
            notice = conn.execute(
                "SELECT paper_id FROM papers WHERE doi=?", (notice_doi,)
            ).fetchone()
            original = conn.execute(
                "SELECT paper_id FROM papers WHERE doi=?", (original_doi,)
            ).fetchone()
            if not notice or not original:
                log.warning(
                    "Retraction link missing a record: notice=%s original=%s",
                    notice_doi,
                    original_doi,
                )
                continue
            conn.execute(
                """
                UPDATE papers
                SET content_type='retraction_notice',
                    retraction_status='notice',
                    retracts_paper_id=?
                WHERE paper_id=?
                """,
                (original["paper_id"], notice["paper_id"]),
            )
            conn.execute(
                """
                UPDATE papers
                SET content_type='article',
                    retraction_status='retracted',
                    retracted_by_paper_id=?
                WHERE paper_id=?
                """,
                (notice["paper_id"], original["paper_id"]),
            )
            links += 1
    if links:
        log.info("Linked %s retraction(s) from Crossref update-to", links)
    return links


def _link_retractions(conn: sqlite3.Connection) -> None:
    for original_doi, notice_doi in RETRACTION_PAIRS:
        original = conn.execute("SELECT paper_id FROM papers WHERE doi=?", (original_doi,)).fetchone()
        notice = conn.execute("SELECT paper_id FROM papers WHERE doi=?", (notice_doi,)).fetchone()
        if not original or not notice:
            continue
        conn.execute(
            """
            UPDATE papers
            SET content_type='article', retraction_status='retracted', retracted_by_paper_id=?
            WHERE paper_id=?
            """,
            (notice["paper_id"], original["paper_id"]),
        )
        conn.execute(
            """
            UPDATE papers
            SET content_type='retraction_notice', retraction_status='notice', retracts_paper_id=?
            WHERE paper_id=?
            """,
            (original["paper_id"], notice["paper_id"]),
        )


def _dedup_title_key(title: str | None) -> str:
    key = title_key(title)
    if key in {"editors introduction", "editor s introduction"}:
        return "editor introduction"
    return key


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _compatible(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_type = left["content_type"]
    right_type = right["content_type"]
    left_pages = page_range(left["page_first"], left["page_last"])
    right_pages = page_range(right["page_first"], right["page_last"])
    overlap = page_ranges_overlap(left_pages, right_pages)

    if left_type == "article" and right_type == "article":
        # Identical title + volume + issue + exact page range is a duplicate
        # even when one deposit has incomplete author metadata. When pages only
        # overlap, require author-set agreement to avoid merging comments or
        # replies that happen to share a page boundary.
        if left_pages is not None and right_pages is not None and left_pages == right_pages:
            return True
        return overlap and _jaccard(left["authors"], right["authors"]) >= 0.8
    if left_type == "erratum" and right_type == "erratum":
        return overlap or left_pages is None or right_pages is None
    if left_type in AUX_TYPES and right_type in AUX_TYPES:
        # Same title group + identical page range is a duplicate even when one
        # deposit has different author metadata. If the page ranges differ,
        # only merge when the author sets agree; this prevents a whole-issue
        # "Front Matter" record from swallowing the Foreword inside it.
        if left_pages is not None and right_pages is not None and left_pages == right_pages:
            return True
        if not left["authors"] and not right["authors"]:
            return True
        return _jaccard(left["authors"], right["authors"]) >= 0.5
    return False


def _canonical_sort_key(paper: dict[str, Any]) -> tuple[Any, ...]:
    return (
        TYPE_PRIORITY.get(paper["content_type"], 9),
        0
        if paper["doi"].startswith("10.1257/aer.") and not paper["doi"].endswith(";")
        else 1,
        -paper["citation_count"],
        -paper["abstract_available"],
        paper["paper_id"],
    )


def detect_duplicates(conn: sqlite3.Connection) -> int:
    """Mark duplicate deposits across all content types.

    Matching uses a punctuation-insensitive title key, normalised issue number,
    page-range overlap (roman numerals included), and author-set Jaccard
    similarity. This catches the 51 legacy/modern DOI pairs plus the 16 pairs
    the exact-key audit missed.
    """
    conn.execute("UPDATE papers SET is_duplicate=0, duplicate_of_paper_id=NULL")

    authors_by_paper: dict[int, set[str]] = defaultdict(set)
    authors_nospace_by_paper: dict[int, set[str]] = defaultdict(set)
    for row in conn.execute(
        """
        SELECT a.paper_id, a.given_name, a.family_name, a.full_name
        FROM authorships a
        JOIN papers p ON p.paper_id = a.paper_id
        WHERE p.content_type <> 'issue_metadata'
        """
    ):
        key = name_match_key(row["given_name"], row["family_name"])
        if not key:
            key = normalize_name_part(row["full_name"])
        if key:
            authors_by_paper[row["paper_id"]].add(key)
        nospace = normalize_name_part(row["full_name"]).replace(" ", "")
        if nospace:
            authors_nospace_by_paper[row["paper_id"]].add(nospace)

    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in conn.execute(
        """
        SELECT paper_id, doi, title, content_type, volume, issue,
               page_first, page_last, published_year, citation_count, abstract_available
        FROM papers
        WHERE content_type <> 'issue_metadata'
        """
    ):
        key = _dedup_title_key(row["title"])
        if not key:
            continue
        group_key = (
            key,
            row["published_year"],
            row["volume"],
            normalize_issue(row["issue"]),
        )
        groups[group_key].append(
            {
                "paper_id": row["paper_id"],
                "doi": row["doi"] or "",
                "content_type": row["content_type"],
                "page_first": row["page_first"],
                "page_last": row["page_last"],
                "citation_count": row["citation_count"] or 0,
                "abstract_available": row["abstract_available"] or 0,
                "authors": authors_by_paper.get(row["paper_id"], set()),
            }
        )

    duplicate_count = 0
    for group in groups.values():
        if len(group) < 2:
            continue
        parent = list(range(len(group)))

        def find(index: int) -> int:
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index

        def union(left: int, right: int) -> None:
            root_left = find(left)
            root_right = find(right)
            if root_left != root_right:
                parent[root_right] = root_left

        for left in range(len(group)):
            for right in range(left + 1, len(group)):
                if _compatible(group[left], group[right]):
                    union(left, right)

        components: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for index, paper in enumerate(group):
            components[find(index)].append(paper)

        for component in components.values():
            if len(component) < 2:
                continue
            ordered = sorted(component, key=_canonical_sort_key)
            canonical = ordered[0]
            for duplicate in ordered[1:]:
                conn.execute(
                    """
                    UPDATE papers
                    SET content_type='duplicate',
                        is_duplicate=1,
                        duplicate_of_paper_id=?,
                        is_pp=0,
                        pp_confidence=NULL
                    WHERE paper_id=?
                    """,
                    (canonical["paper_id"], duplicate["paper_id"]),
                )
                duplicate_count += 1

    duplicate_count += _aux_page_pass(conn, authors_nospace_by_paper)
    return duplicate_count


def _aux_page_pass(conn: sqlite3.Connection, authors_by_paper: dict[int, set[str]]) -> int:
    """Merge same-issue administrative paratext with overlapping pages.

    Some P&P front matter appears under different titles in the same issue
    ("Foreword" vs "Editor's Introduction") but occupies the same page. This
    pass catches those pairs without touching research articles.
    """
    rows = conn.execute(
        """
        SELECT paper_id, doi, title, content_type, volume, issue,
               page_first, page_last, published_year, citation_count, abstract_available
        FROM papers
        WHERE content_type IN ('front_matter', 'association_report', 'unattributed', 'retraction_notice')
          AND is_duplicate=0
        """
    ).fetchall()

    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        pages = page_range(row["page_first"], row["page_last"])
        if pages is None:
            continue
        groups[(row["published_year"], row["volume"], normalize_issue(row["issue"]))].append(
            {
                "paper_id": row["paper_id"],
                "doi": row["doi"] or "",
                "content_type": row["content_type"],
                "page_first": row["page_first"],
                "page_last": row["page_last"],
                "citation_count": row["citation_count"] or 0,
                "abstract_available": row["abstract_available"] or 0,
                "authors": authors_by_paper.get(row["paper_id"], set()),
                "pages": pages,
            }
        )

    duplicate_count = 0
    for group in groups.values():
        if len(group) < 2:
            continue
        parent = list(range(len(group)))

        def find(index: int) -> int:
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index

        def union(left: int, right: int) -> None:
            root_left = find(left)
            root_right = find(right)
            if root_left != root_right:
                parent[root_right] = root_left

        for left in range(len(group)):
            for right in range(left + 1, len(group)):
                left_paper = group[left]
                right_paper = group[right]
                if left_paper["pages"] != right_paper["pages"]:
                    continue
                if not left_paper["authors"] and not right_paper["authors"]:
                    union(left, right)
                elif _jaccard(left_paper["authors"], right_paper["authors"]) >= 0.8:
                    union(left, right)

        components: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for index, paper in enumerate(group):
            components[find(index)].append(paper)
        for component in components.values():
            if len(component) < 2:
                continue
            ordered = sorted(component, key=_canonical_sort_key)
            canonical = ordered[0]
            for duplicate in ordered[1:]:
                conn.execute(
                    """
                    UPDATE papers
                    SET content_type='duplicate',
                        is_duplicate=1,
                        duplicate_of_paper_id=?,
                        is_pp=0,
                        pp_confidence=NULL
                    WHERE paper_id=?
                    """,
                    (canonical["paper_id"], duplicate["paper_id"]),
                )
                duplicate_count += 1
    return duplicate_count

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .config import JOURNAL_NAME, REPORTS_DIR
from .db import utcnow


def _pct(numerator: int | None, denominator: int | None) -> str:
    if not denominator:
        return "n/a"
    return f"{100.0 * (numerator or 0) / denominator:.1f}%"


def _table(headers: Iterable[str], rows: Iterable[Iterable[Any]]) -> str:
    header_list = list(headers)
    lines = [
        "| " + " | ".join(header_list) + " |",
        "|" + "|".join(["---"] * len(header_list)) + "|",
    ]
    for row in rows:
        values = ["" if value is None else str(value) for value in row]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def generate_report(conn, path: Path | None = None) -> tuple[Path, Path]:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    markdown_path = path or (REPORTS_DIR / "m1_quality.md")
    metrics_path = markdown_path.with_suffix(".json")

    summary = conn.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM papers) AS records,
            (SELECT COUNT(*) FROM papers WHERE content_type='article') AS articles,
            (SELECT COUNT(*) FROM papers WHERE content_type='article' AND is_pp=1) AS pp_papers,
            (SELECT COUNT(*) FROM papers WHERE content_type='front_matter') AS front_matter,
            (SELECT COUNT(*) FROM papers WHERE content_type='issue_metadata') AS issue_metadata,
            (SELECT COUNT(*) FROM papers WHERE content_type='unattributed') AS unattributed,
            (SELECT COUNT(*) FROM papers WHERE content_type='erratum') AS errata,
            (SELECT COUNT(*) FROM papers WHERE content_type='association_report') AS association_reports,
            (SELECT COUNT(*) FROM papers WHERE content_type='retraction_notice') AS retraction_notices,
            (SELECT COUNT(*) FROM papers WHERE retraction_status='retracted') AS retracted_originals,
            (SELECT COUNT(*) FROM papers WHERE is_duplicate=1) AS duplicates,
            (SELECT COUNT(*) FROM authorships a
                JOIN papers p ON p.paper_id = a.paper_id
                WHERE p.content_type='article') AS authorships,
            (SELECT COUNT(*) FROM authors) AS authors,
            (SELECT COUNT(*) FROM authors WHERE orcid IS NOT NULL) AS authors_with_orcid,
            (SELECT COUNT(*) FROM authors WHERE resolution_method='name_key') AS authors_name_key,
            (SELECT COUNT(*) FROM authors WHERE resolution_method='name_variant') AS authors_name_variant,
            (SELECT COUNT(*) FROM authors WHERE merged_variants > 1) AS authors_merged_variants,
            (SELECT COUNT(*) FROM authors WHERE needs_review=1) AS authors_needs_review,
            (SELECT COUNT(*) FROM author_aliases) AS author_aliases,
            (SELECT COUNT(*) FROM author_merge_candidates WHERE status='pending') AS merge_candidates,
            (SELECT COUNT(*) FROM coauthorship_edges) AS coauthorship_edges,
            (SELECT COUNT(*) FROM (
                SELECT DISTINCT
                    CASE WHEN author_a_id < author_b_id THEN author_a_id ELSE author_b_id END,
                    CASE WHEN author_a_id < author_b_id THEN author_b_id ELSE author_a_id END
                FROM coauthorship_edges
            )) AS coauthorship_ties,
            (SELECT COUNT(*) FROM authorships a
                JOIN papers p ON p.paper_id = a.paper_id
                WHERE p.content_type='article'
                  AND TRIM(COALESCE(a.affiliation_raw,'')) <> '') AS with_affiliation,
            (SELECT COUNT(*) FROM authorships a
                JOIN papers p ON p.paper_id = a.paper_id
                WHERE p.content_type='article'
                  AND a.rank_category IS NOT NULL) AS with_rank,
            (SELECT COUNT(*) FROM authorships a
                JOIN papers p ON p.paper_id = a.paper_id
                WHERE p.content_type='article'
                  AND a.rank_category IS NOT NULL
                  AND a.rank_category <> 'non_academic') AS with_academic_rank,
            (SELECT COUNT(*) FROM authorships a
                JOIN papers p ON p.paper_id = a.paper_id
                WHERE p.content_type='article'
                  AND a.rank_category = 'non_academic') AS non_academic_slots,
            (SELECT COUNT(*) FROM papers
                WHERE content_type='article' AND abstract_available=1) AS with_abstract,
            (SELECT COUNT(*) FROM papers
                WHERE content_type='article' AND abstract_source='crossref') AS abstract_crossref,
            (SELECT COUNT(*) FROM papers
                WHERE content_type='article' AND abstract_source='aea') AS abstract_aea,
            (SELECT COUNT(*) FROM papers
                WHERE content_type='article' AND abstract_source='openalex') AS abstract_openalex,
            (SELECT COUNT(*) FROM papers
                WHERE content_type='article' AND abstract_available=0) AS abstract_missing,
            (SELECT COUNT(*) FROM papers
                WHERE content_type='article' AND openalex_id IS NOT NULL) AS openalex_papers,
            (SELECT COUNT(DISTINCT paper_id) FROM paper_topics WHERE scheme='jel') AS jel_papers,
            (SELECT COUNT(*) FROM paper_topics WHERE scheme='jel') AS jel_codes,
            (SELECT COUNT(DISTINCT paper_id) FROM paper_topics
                WHERE scheme='openalex_topic') AS openalex_topic_papers,
            (SELECT COUNT(*) FROM papers
                WHERE content_type='article' AND date_source='aea_article_page') AS dates_aea,
            (SELECT COUNT(*) FROM papers
                WHERE content_type='article' AND date_source='crossref_issue_metadata') AS dates_issue_metadata,
            (SELECT COUNT(*) FROM papers
                WHERE content_type='article' AND date_source='aer_issue_calendar') AS dates_calendar,
            (SELECT COUNT(*) FROM papers
                WHERE content_type='article' AND date_source='crossref') AS dates_crossref,
            (SELECT COUNT(*) FROM authors WHERE openalex_id IS NOT NULL) AS authors_with_openalex,
            (SELECT COUNT(DISTINCT author_id) FROM author_openalex_evidence
                WHERE is_consistent=0) AS author_openalex_conflicts,
            (SELECT COUNT(*) FROM institutions WHERE openalex_id IS NOT NULL) AS institutions_resolved,
            (SELECT COUNT(*) FROM authorship_institutions WHERE source='openalex') AS authorship_institution_links,
            (SELECT COUNT(*) FROM authorships a
                JOIN papers p ON p.paper_id = a.paper_id
                WHERE p.content_type='article'
                  AND a.openalex_institution_id IS NOT NULL) AS slots_with_openalex_institution,
            (SELECT COUNT(*) FROM source_records WHERE source='aea_article') AS aea_pages,
            (SELECT COUNT(*) FROM source_records WHERE source='openalex_work') AS openalex_works,
            (SELECT COUNT(*) FROM papers
                WHERE content_type='article' AND page_first IS NULL) AS missing_page_first,
            (SELECT COUNT(*) FROM papers
                WHERE content_type='article'
                  AND page_first GLOB '[0-9]*'
                  AND page_last GLOB '[0-9]*'
                  AND CAST(page_last AS INTEGER) < CAST(page_first AS INTEGER)) AS reversed_page_ranges,
            (SELECT MIN(published_year) FROM papers WHERE content_type='article') AS min_year,
            (SELECT MAX(published_year) FROM papers WHERE content_type='article') AS max_year
        """
    ).fetchone()

    content_types = conn.execute(
        """
        SELECT content_type, COUNT(*) AS n
        FROM papers
        GROUP BY 1
        ORDER BY n DESC
        """
    ).fetchall()

    item_types = conn.execute(
        """
        SELECT COALESCE(item_type, '(missing)') AS item_type, COUNT(*) AS n
        FROM papers
        GROUP BY 1
        ORDER BY n DESC
        """
    ).fetchall()

    by_year = conn.execute(
        """
        SELECT
            p.published_year AS year,
            COUNT(DISTINCT p.paper_id) AS papers,
            COUNT(a.authorship_id) AS authorships,
            SUM(CASE WHEN TRIM(COALESCE(a.affiliation_raw,'')) <> '' THEN 1 ELSE 0 END) AS with_affiliation,
            SUM(CASE WHEN a.rank_category IS NOT NULL THEN 1 ELSE 0 END) AS with_rank,
            COUNT(DISTINCT CASE WHEN p.abstract_available=1 THEN p.paper_id END) AS with_abstract,
            COUNT(DISTINCT CASE WHEN p.is_pp=1 THEN p.paper_id END) AS pp_papers
        FROM papers p
        LEFT JOIN authorships a ON a.paper_id = p.paper_id
        WHERE p.content_type='article'
        GROUP BY p.published_year
        ORDER BY p.published_year
        """
    ).fetchall()

    pp_issues = conn.execute(
        """
        SELECT published_year AS year, volume, issue, COUNT(*) AS articles,
               MIN(published_month) AS month, MAX(pp_confidence) AS confidence
        FROM papers
        WHERE content_type='article' AND is_pp=1
        GROUP BY published_year, volume, issue
        ORDER BY published_year, volume, issue
        """
    ).fetchall()

    authors_per_paper = conn.execute(
        """
        SELECT n AS authors_per_paper, COUNT(*) AS papers
        FROM (
            SELECT a.paper_id, COUNT(*) AS n
            FROM authorships a
            JOIN papers p ON p.paper_id = a.paper_id
            WHERE p.content_type='article'
            GROUP BY a.paper_id
        )
        GROUP BY n
        ORDER BY n
        """
    ).fetchall()

    rank_categories = conn.execute(
        """
        SELECT COALESCE(a.rank_category, '(no rank detected)') AS category, COUNT(*) AS n
        FROM authorships a
        JOIN papers p ON p.paper_id = a.paper_id
        WHERE p.content_type='article'
        GROUP BY 1
        ORDER BY n DESC
        """
    ).fetchall()

    institution_hints = conn.execute(
        """
        SELECT a.institution_hint, COUNT(*) AS n
        FROM authorships a
        JOIN papers p ON p.paper_id = a.paper_id
        WHERE p.content_type='article'
          AND a.institution_hint IS NOT NULL
          AND TRIM(a.institution_hint) <> ''
        GROUP BY 1
        ORDER BY n DESC
        LIMIT 25
        """
    ).fetchall()

    flags = conn.execute(
        """
        SELECT
            SUM(CASE WHEN title IS NULL OR TRIM(title)='' THEN 1 ELSE 0 END) AS missing_title,
            SUM(CASE WHEN published_year IS NULL THEN 1 ELSE 0 END) AS missing_year,
            SUM(CASE WHEN doi_synthetic=1 THEN 1 ELSE 0 END) AS synthetic_doi,
            SUM(CASE WHEN published_year > ? THEN 1 ELSE 0 END) AS future_year,
            SUM(CASE WHEN NOT EXISTS (
                SELECT 1 FROM authorships a WHERE a.paper_id = papers.paper_id
            ) THEN 1 ELSE 0 END) AS no_author
        FROM papers
        WHERE content_type='article'
        """,
        (datetime.now().year + 1,),
    ).fetchone()

    duplicate_titles = conn.execute(
        """
        SELECT title, published_year, COUNT(*) AS n
        FROM papers
        WHERE content_type='article'
          AND title IS NOT NULL
          AND TRIM(title) <> ''
        GROUP BY title, published_year
        HAVING n > 1
        ORDER BY n DESC, title
        LIMIT 15
        """
    ).fetchall()

    abstract_sources = conn.execute(
        """
        SELECT COALESCE(abstract_source, '(none)') AS source, COUNT(*) AS n
        FROM papers
        WHERE content_type='article'
        GROUP BY 1
        ORDER BY n DESC
        """
    ).fetchall()

    date_sources = conn.execute(
        """
        SELECT COALESCE(date_source, '(none)') AS source, COUNT(*) AS n
        FROM papers
        WHERE content_type='article'
        GROUP BY 1
        ORDER BY n DESC
        """
    ).fetchall()

    enrichment_by_year = conn.execute(
        """
        SELECT p.published_year AS year,
               COUNT(DISTINCT p.paper_id) AS papers,
               COUNT(DISTINCT CASE WHEN p.openalex_id IS NOT NULL THEN p.paper_id END) AS openalex_papers,
               COUNT(DISTINCT CASE WHEN p.abstract_source='aea' THEN p.paper_id END) AS aea_abstracts,
               COUNT(DISTINCT CASE WHEN p.abstract_source='openalex' THEN p.paper_id END) AS openalex_abstracts,
               COUNT(DISTINCT CASE WHEN t.scheme='jel' THEN p.paper_id END) AS jel_papers,
               COUNT(DISTINCT CASE WHEN t.scheme='openalex_topic' THEN p.paper_id END) AS openalex_topic_papers
        FROM papers p
        LEFT JOIN paper_topics t ON t.paper_id = p.paper_id
        WHERE p.content_type='article'
        GROUP BY p.published_year
        ORDER BY p.published_year
        """
    ).fetchall()

    top_jel = conn.execute(
        """
        SELECT code, COUNT(*) AS n, MIN(label) AS label
        FROM paper_topics
        WHERE scheme='jel'
        GROUP BY code
        ORDER BY n DESC, code
        LIMIT 15
        """
    ).fetchall()

    top_institutions = conn.execute(
        """
        SELECT i.display_name, i.country_code, COUNT(*) AS n
        FROM authorship_institutions ai
        JOIN institutions i ON i.institution_id = ai.institution_id
        JOIN authorships a ON a.authorship_id = ai.authorship_id
        JOIN papers p ON p.paper_id = a.paper_id
        WHERE p.content_type='article'
          AND p.is_duplicate=0
          AND ai.source='openalex'
        GROUP BY i.institution_id
        ORDER BY n DESC, i.display_name
        LIMIT 20
        """
    ).fetchall()

    top_cited = conn.execute(
        """
        SELECT title, published_year, openalex_cited_by_count, doi
        FROM papers
        WHERE content_type='article' AND openalex_cited_by_count IS NOT NULL
        ORDER BY openalex_cited_by_count DESC, title
        LIMIT 15
        """
    ).fetchall()

    author_openalex_conflicts = conn.execute(
        """
        SELECT a.canonical_name,
               COUNT(DISTINCT e.openalex_id) AS n,
               GROUP_CONCAT(DISTINCT e.openalex_id) AS openalex_ids
        FROM author_openalex_evidence e
        JOIN authors a ON a.author_id = e.author_id
        GROUP BY e.author_id
        HAVING COUNT(DISTINCT e.openalex_id) > 1
        ORDER BY n DESC, a.canonical_name
        LIMIT 20
        """
    ).fetchall()

    candidate_evidence = conn.execute(
        """
        SELECT c.candidate_id, a.canonical_name AS name_a, b.canonical_name AS name_b,
               c.reason, c.evidence
        FROM author_merge_candidates c
        JOIN authors a ON a.author_id = c.author_id_a
        JOIN authors b ON b.author_id = c.author_id_b
        ORDER BY c.candidate_id
        LIMIT 20
        """
    ).fetchall()

    articles = summary["articles"] or 0
    authorships = summary["authorships"] or 0

    lines: list[str] = []
    lines.append("# Data Quality Report — AER 2000+")
    lines.append("")
    lines.append(f"Generated: {utcnow()}")
    lines.append("")
    lines.append(
        f"Scope: **{JOURNAL_NAME}** (ISSN 0002-8282), Crossref records published from 2000 onward."
    )
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(
        _table(
            ["Metric", "Value"],
            [
                ("Bibliographic records", summary["records"]),
                ("Research articles (incl. P&P)", articles),
                ("P&P articles identified", summary["pp_papers"]),
                ("Front matter", summary["front_matter"]),
                ("Issue metadata records", summary["issue_metadata"]),
                ("Unattributed records (no author)", summary["unattributed"]),
                ("Errata/corrigenda", summary["errata"]),
                ("AEA association reports/minutes", summary["association_reports"]),
                ("Retraction notices", summary["retraction_notices"]),
                ("Retracted originals (status flag)", summary["retracted_originals"]),
                ("Duplicate records (excluded from analysis)", summary["duplicates"]),
                ("Author slots (research articles)", authorships),
                ("Canonical authors", summary["authors"]),
                ("Authors with ORCID", summary["authors_with_orcid"]),
                ("Authors resolved by exact name only", summary["authors_name_key"]),
                ("Authors resolved by name variant", summary["authors_name_variant"]),
                ("Authors with merged variants", summary["authors_merged_variants"]),
                ("Authors flagged for review", summary["authors_needs_review"]),
                ("Author aliases", summary["author_aliases"]),
                ("Pending merge candidates", summary["merge_candidates"]),
                ("Coauthor ties (unique pairs)", summary["coauthorship_ties"]),
                ("Coauthor edge records", summary["coauthorship_edges"]),
                ("Affiliation coverage (author slots)", _pct(summary["with_affiliation"], authorships)),
                ("Any rank/title mention", _pct(summary["with_rank"], authorships)),
                ("Academic byline rank coverage", _pct(summary["with_academic_rank"], authorships)),
                ("Non-academic affiliation share", _pct(summary["non_academic_slots"], authorships)),
                ("Abstract coverage (articles)", _pct(summary["with_abstract"], articles)),
                ("  — Crossref abstract", summary["abstract_crossref"]),
                ("  — AEA abstract", summary["abstract_aea"]),
                ("  — OpenAlex abstract", summary["abstract_openalex"]),
                ("  — missing abstract", summary["abstract_missing"]),
                ("OpenAlex work coverage", _pct(summary["openalex_papers"], articles)),
                ("JEL coverage (articles)", _pct(summary["jel_papers"], articles)),
                ("OpenAlex topic coverage", _pct(summary["openalex_topic_papers"], articles)),
                ("AEA article pages parsed", summary["aea_pages"]),
                ("OpenAlex works matched", summary["openalex_works"]),
                ("Authors with OpenAlex ID", summary["authors_with_openalex"]),
                ("Authors with >1 OpenAlex ID", summary["author_openalex_conflicts"]),
                ("Resolved institutions (OpenAlex)", summary["institutions_resolved"]),
                ("Authorship–institution links", summary["authorship_institution_links"]),
                ("Author slots with OpenAlex institution", _pct(summary["slots_with_openalex_institution"], authorships)),
                ("Articles missing first page", summary["missing_page_first"]),
                ("Reversed numeric page ranges", summary["reversed_page_ranges"]),
                ("Year range", f"{summary['min_year']}–{summary['max_year']}"),
            ],
        )
    )
    lines.append("")
    lines.append("## Content types")
    lines.append("")
    lines.append(
        _table(
            ["content_type", "Records"],
            [(row["content_type"], row["n"]) for row in content_types],
        )
    )
    lines.append("")
    lines.append("## Coverage by publication year")
    lines.append("")
    lines.append(
        _table(
            ["Year", "Articles", "Author slots", "Affiliation %", "Rank %", "Abstract %", "P&P articles"],
            [
                (
                    row["year"],
                    row["papers"],
                    row["authorships"],
                    _pct(row["with_affiliation"], row["authorships"]),
                    _pct(row["with_rank"], row["authorships"]),
                    _pct(row["with_abstract"], row["papers"]),
                    row["pp_papers"],
                )
                for row in by_year
            ],
        )
    )
    lines.append("")
    lines.append("## P&P issue identification")
    lines.append("")
    lines.append(
        _table(
            ["Year", "Volume", "Issue", "Articles", "Month", "Confidence"],
            [
                (
                    row["year"],
                    row["volume"],
                    row["issue"],
                    row["articles"],
                    row["month"],
                    row["confidence"],
                )
                for row in pp_issues
            ],
        )
    )
    lines.append("")
    lines.append("## Crossref item types")
    lines.append("")
    lines.append(_table(["Crossref type", "Records"], [(row["item_type"], row["n"]) for row in item_types]))
    lines.append("")
    lines.append("## Authors per paper (research articles)")
    lines.append("")
    lines.append(
        _table(
            ["Authors", "Papers"],
            [(row["authors_per_paper"], row["papers"]) for row in authors_per_paper],
        )
    )
    lines.append("")
    lines.append("## Extracted byline ranks (research articles)")
    lines.append("")
    lines.append(
        _table(
            ["Rank category", "Author slots"],
            [(row["category"], row["n"]) for row in rank_categories],
        )
    )
    lines.append("")
    lines.append("## Top raw institution hints (research articles)")
    lines.append("")
    lines.append(
        _table(
            ["Institution hint", "Author slots"],
            [(row["institution_hint"], row["n"]) for row in institution_hints],
        )
    )
    lines.append("")
    lines.append("## Quality flags (research articles)")
    lines.append("")
    lines.append(
        _table(
            ["Flag", "Count"],
            [
                ("Missing title", flags["missing_title"]),
                ("Missing publication year", flags["missing_year"]),
                ("Synthetic DOI", flags["synthetic_doi"]),
                ("Publication year beyond next calendar year", flags["future_year"]),
                ("Article with no author", flags["no_author"]),
            ],
        )
    )
    lines.append("")
    if duplicate_titles:
        lines.append("### Repeated title + year combinations (non-duplicate research articles)")
        lines.append("")
        lines.append(
            _table(
                ["Title", "Year", "Count"],
                [(row["title"], row["published_year"], row["n"]) for row in duplicate_titles],
            )
        )
        lines.append("")
    lines.append("## Enrichment coverage by publication year")
    lines.append("")
    lines.append(
        _table(
            [
                "Year",
                "Articles",
                "OpenAlex works",
                "AEA abstracts",
                "OpenAlex abstracts",
                "JEL papers",
                "OpenAlex topics",
            ],
            [
                (
                    row["year"],
                    row["papers"],
                    row["openalex_papers"],
                    row["aea_abstracts"],
                    row["openalex_abstracts"],
                    row["jel_papers"],
                    row["openalex_topic_papers"],
                )
                for row in enrichment_by_year
            ],
        )
    )
    lines.append("")
    lines.append("## Abstract provenance")
    lines.append("")
    lines.append(
        _table(
            ["Source", "Articles"],
            [(row["source"], row["n"]) for row in abstract_sources],
        )
    )
    lines.append("")
    lines.append("## Publication date provenance")
    lines.append("")
    lines.append(
        _table(
            ["date_source", "Articles"],
            [(row["source"], row["n"]) for row in date_sources],
        )
    )
    lines.append("")
    if top_jel:
        lines.append("## Most common JEL codes")
        lines.append("")
        lines.append(
            _table(
                ["JEL code", "Label (first observed)", "Articles"],
                [(row["code"], row["label"], row["n"]) for row in top_jel],
            )
        )
        lines.append("")
    if top_institutions:
        lines.append("## Top resolved institutions (OpenAlex)")
        lines.append("")
        lines.append(
            _table(
                ["Institution", "Country", "Author slots"],
                [(row["display_name"], row["country_code"], row["n"]) for row in top_institutions],
            )
        )
        lines.append("")
    if top_cited:
        lines.append("## Most-cited AER articles in the corpus (OpenAlex)")
        lines.append("")
        lines.append(
            _table(
                ["Title", "Year", "Citations", "DOI"],
                [
                    (row["title"], row["published_year"], row["openalex_cited_by_count"], row["doi"])
                    for row in top_cited
                ],
            )
        )
        lines.append("")
    if author_openalex_conflicts:
        lines.append("## Authors with conflicting OpenAlex IDs")
        lines.append("")
        lines.append(
            _table(
                ["Author", "OpenAlex IDs", "IDs"],
                [
                    (row["canonical_name"], row["n"], row["openalex_ids"])
                    for row in author_openalex_conflicts
                ],
            )
        )
        lines.append("")
    if candidate_evidence:
        lines.append("## Merge candidates and OpenAlex evidence")
        lines.append("")
        lines.append(
            _table(
                ["ID", "Author A", "Author B", "Reason", "Evidence"],
                [
                    (
                        row["candidate_id"],
                        row["name_a"],
                        row["name_b"],
                        row["reason"],
                        row["evidence"],
                    )
                    for row in candidate_evidence
                ],
            )
        )
        lines.append("")
    lines.append("## Interpretation")
    lines.append("")
    lines.append(
        "- Crossref is the M1 source of record. It covers AEA deposits from 1999 onward; "
        "the pre-1999 archive is out of scope by decision."
    )
    lines.append(
        "- `content_type` separates research articles from front matter, issue metadata, "
        "unattributed records, errata, AEA association reports/minutes, retraction notices, "
        "and duplicates. Only research articles feed the year-level and network statistics."
    )
    lines.append(
        "- Duplicates are detected with a punctuation-insensitive title key, normalised issue "
        "number, page-range overlap (roman numerals included), and author-set similarity. "
        "The canonical record keeps the modern `10.1257/aer...` DOI where possible; other "
        "rows are marked `content_type='duplicate'` with a `duplicate_of_paper_id` pointer."
    )
    lines.append(
        "- P&P articles are identified as the largest spring issue in each year through 2017. "
        "The old issue-number heuristic was wrong because the issue number moved from 2 to 3 "
        "to 5 over time."
    )
    lines.append(
        "- Affiliation strings are publish-time bylines. Coverage is high in recent years and "
        "weaker in the early 2000s; missing values are left missing rather than imputed."
    )
    lines.append(
        "- Rank extraction is a regex over the byline and is intentionally conservative. "
        f"Any rank/title mention covers {_pct(summary['with_rank'], authorships)} of slots, "
        f"but explicit academic rank covers only {_pct(summary['with_academic_rank'], authorships)}; "
        f"{_pct(summary['non_academic_slots'], authorships)} are non-academic titles. "
        "Academic byline rank cannot support career inference on its own."
    )
    lines.append(
        f"- Canonical author counts use middle-initial-, particle-, and Unicode-aware matching. "
        f"The rebuild produced {summary['authors']} canonical authors, {summary['author_aliases']} "
        f"aliases, and {summary['merge_candidates']} pending merge candidates; "
        f"{summary['authors_needs_review']} authors are flagged for review. Crossref supplies "
        "almost no ORCIDs for AER authors, so OpenAlex and CV evidence remain essential."
    )
    lines.append(
        "- OpenAlex is used only as DOI-keyed enrichment. Its `publication_date` inherits the "
        "same one-month shift as Crossref for 2002–2009, so it is stored for comparison but "
        "never used to correct issue months. AEA article pages and the AEA all-issues calendar "
        "provide the authoritative issue month."
    )
    lines.append(
        "- Citation counts are source-specific: Crossref's `is-referenced-by-count` and "
        "OpenAlex's `cited_by_count` are stored separately and not reconciled. The top-cited "
        "table reports OpenAlex's values as-is; duplicate works and citation-matching errors "
        "can inflate them."
    )
    lines.append(
        "- JEL codes come from AEA article pages. OpenAlex topics are stored separately under "
        "`scheme='openalex_topic'`; the two schemes are not treated as equivalent. JEL coverage "
        "is partial and not yet uniform by year because the AEA crawler processes in paper order "
        "and is resumable; OpenAlex topic coverage is independent and near-complete."
    )
    lines.append(
        "- Abstract provenance is explicit: Crossref, AEA, or OpenAlex. The preferred abstract "
        "is kept in `abstract`; the AEA and OpenAlex versions are retained in `abstract_aea` and "
        "`abstract_openalex` for audit."
    )
    lines.append(
        "- Institution hints are now resolved against OpenAlex institution IDs. A single "
        "authorship may carry several institutions; those links live in `authorship_institutions`. "
        "The Crossref byline string remains available in `institution_hint`."
    )
    lines.append(
        "- OpenAlex author links are attached only when a canonical author's authorships map to "
        "one OpenAlex ID (or a dominant ID covering at least 80% of them). Multiple IDs, and "
        "one ID shared by several canonical authors, are queued as review evidence rather than "
        "silently merged or split."
    )
    lines.append(
        "- Retracted originals remain `content_type='article'` with `retraction_status='retracted'` "
        "and a pointer to the notice; retraction notices are excluded from research articles. "
        "Default views should exclude retracted originals."
    )
    lines.append("")

    markdown_path.write_text("\n".join(lines), encoding="utf-8")

    metrics = {
        "generated_at": utcnow(),
        "summary": dict(summary),
        "content_types": [dict(row) for row in content_types],
        "by_year": [dict(row) for row in by_year],
        "item_types": [dict(row) for row in item_types],
        "pp_issues": [dict(row) for row in pp_issues],
        "authors_per_paper": [dict(row) for row in authors_per_paper],
        "rank_categories": [dict(row) for row in rank_categories],
        "top_institution_hints": [dict(row) for row in institution_hints],
        "flags": dict(flags),
        "duplicate_titles": [dict(row) for row in duplicate_titles],
        "abstract_sources": [dict(row) for row in abstract_sources],
        "date_sources": [dict(row) for row in date_sources],
        "enrichment_by_year": [dict(row) for row in enrichment_by_year],
        "top_jel": [dict(row) for row in top_jel],
        "top_institutions": [dict(row) for row in top_institutions],
        "top_cited": [dict(row) for row in top_cited],
        "author_openalex_conflicts": [dict(row) for row in author_openalex_conflicts],
        "candidate_evidence": [dict(row) for row in candidate_evidence],
    }
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    return markdown_path, metrics_path


def generate_m3_report(conn, path: Path | None = None) -> tuple[Path, Path]:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    markdown_path = path or (REPORTS_DIR / "m3_quality.md")
    metrics_path = markdown_path.with_suffix(".json")

    summary = conn.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM authors) AS authors,
            (SELECT COUNT(*) FROM authors WHERE stable_id IS NOT NULL) AS stable_ids,
            (SELECT COUNT(*) FROM author_identity_ledger WHERE status='active') AS ledger_active,
            (SELECT COUNT(*) FROM author_identity_ledger WHERE status='merged') AS ledger_merged,
            (SELECT COUNT(*) FROM author_identity_ledger WHERE status='inactive') AS ledger_inactive,
            (SELECT COUNT(*) FROM author_identity_events) AS identity_events,
            (SELECT COUNT(*) FROM author_separation_rules) AS separation_rules,
            (SELECT COUNT(*) FROM author_split_candidates) AS split_rows,
            (SELECT COUNT(*) FROM author_split_candidates WHERE status='applied') AS splits_applied,
            (SELECT COUNT(*) FROM author_identity_events WHERE event_type='split') AS split_events,
            (SELECT COUNT(*) FROM author_split_candidates WHERE status='rejected') AS fragments,
            (SELECT COUNT(*) FROM author_split_candidates WHERE status='proposed') AS uncertain,
            (SELECT COUNT(*) FROM author_merge_candidates WHERE status='pending') AS pending_candidates,
            (SELECT COUNT(*) FROM author_merge_candidates WHERE status='resolved_split') AS resolved_candidates,
            (SELECT COUNT(*) FROM authors WHERE needs_review=1) AS authors_needs_review,
            (SELECT COUNT(*) FROM career_assignments) AS career_assignments,
            (SELECT COUNT(*) FROM authorships a
                JOIN papers p ON p.paper_id = a.paper_id
                WHERE p.content_type='article' AND p.is_duplicate=0) AS article_slots
        """
    ).fetchone()

    identity_events = conn.execute(
        """
        SELECT event_type, COUNT(*) AS n
        FROM author_identity_events
        GROUP BY event_type
        ORDER BY n DESC, event_type
        """
    ).fetchall()

    merge_rows = conn.execute(
        """
        SELECT c.candidate_id, a.canonical_name AS name_a, b.canonical_name AS name_b,
               c.reason, c.status, c.review_notes, c.evidence
        FROM author_merge_candidates c
        JOIN authors a ON a.author_id = c.author_id_a
        JOIN authors b ON b.author_id = c.author_id_b
        ORDER BY c.candidate_id
        """
    ).fetchall()

    multi_id_rows = conn.execute(
        """
        SELECT a.canonical_name, a.stable_id, sc.openalex_id, sc.proposed_name,
               sc.paper_count, sc.first_year, sc.last_year, sc.institutions,
               sc.status, sc.evidence
        FROM author_split_candidates sc
        JOIN authors a ON a.author_id = sc.author_id
        ORDER BY a.canonical_name, sc.openalex_id
        """
    ).fetchall()

    stage_rows = conn.execute(
        """
        SELECT stage, evidence_type, confidence, COUNT(*) AS n
        FROM career_assignments
        GROUP BY 1, 2, 3
        ORDER BY n DESC, stage
        """
    ).fetchall()

    career_by_year = conn.execute(
        """
        SELECT p.published_year AS year,
               COUNT(a.authorship_id) AS slots,
               COUNT(ca.assignment_id) AS assigned
        FROM authorships a
        JOIN papers p ON p.paper_id = a.paper_id
        LEFT JOIN career_assignments ca ON ca.authorship_id = a.authorship_id
        WHERE p.content_type='article' AND p.is_duplicate=0
        GROUP BY p.published_year
        ORDER BY p.published_year
        """
    ).fetchall()

    lines: list[str] = []
    lines.append("# M3 Identity & Career Report — AER 2000+")
    lines.append("")
    lines.append(f"Generated: {utcnow()}")
    lines.append("")
    lines.append(
        f"Scope: **{JOURNAL_NAME}** (ISSN 0002-8282), 2000–present. "
        "M3 stabilises author identity, resolves the OpenAlex review queue, and "
        "adds conservative byline-only career assignments."
    )
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(
        _table(
            ["Metric", "Value"],
            [
                ("Canonical authors", summary["authors"]),
                ("Authors with stable IDs", summary["stable_ids"]),
                ("Active stable identities", summary["ledger_active"]),
                ("Merged stable identities", summary["ledger_merged"]),
                ("Inactive stable identities", summary["ledger_inactive"]),
                ("Identity events", summary["identity_events"]),
                ("Permanent separation rules", summary["separation_rules"]),
                ("Multi-ID review rows", summary["split_rows"]),
                ("Confirmed author splits", summary["split_events"]),
                ("Applied split-group rows", summary["splits_applied"]),
                ("OpenAlex fragmentation rows", summary["fragments"]),
                ("Uncertain multi-ID rows", summary["uncertain"]),
                ("Pending merge candidates", summary["pending_candidates"]),
                ("Resolved split candidates", summary["resolved_candidates"]),
                ("Authors still flagged for review", summary["authors_needs_review"]),
                ("Career assignments", summary["career_assignments"]),
                (
                    "Career coverage (article slots)",
                    _pct(summary["career_assignments"], summary["article_slots"]),
                ),
            ],
        )
    )
    lines.append("")
    lines.append("## Identity events")
    lines.append("")
    lines.append(
        _table(
            ["Event", "Count"],
            [(row["event_type"], row["n"]) for row in identity_events],
        )
    )
    lines.append("")
    lines.append("## Merge candidates")
    lines.append("")
    lines.append(
        _table(
            ["ID", "Author A", "Author B", "Status", "Review note"],
            [
                (
                    row["candidate_id"],
                    row["name_a"],
                    row["name_b"],
                    row["status"],
                    row["review_notes"] or row["reason"],
                )
                for row in merge_rows
            ],
        )
    )
    lines.append("")
    lines.append("## Multi-OpenAlex-ID review")
    lines.append("")
    lines.append(
        _table(
            [
                "Author",
                "Stable ID",
                "OpenAlex ID",
                "Proposed name",
                "Papers",
                "Years",
                "Institutions",
                "Status",
            ],
            [
                (
                    row["canonical_name"],
                    row["stable_id"],
                    row["openalex_id"],
                    row["proposed_name"],
                    row["paper_count"],
                    f"{row['first_year'] or '?'}–{row['last_year'] or '?'}",
                    row["institutions"],
                    row["status"],
                )
                for row in multi_id_rows
            ],
        )
    )
    lines.append("")
    lines.append("## Career assignments by stage and evidence")
    lines.append("")
    lines.append(
        _table(
            ["Stage", "Evidence", "Confidence", "Slots"],
            [
                (row["stage"], row["evidence_type"], row["confidence"], row["n"])
                for row in stage_rows
            ],
        )
    )
    lines.append("")
    lines.append("## Career coverage by publication year")
    lines.append("")
    lines.append(
        _table(
            ["Year", "Article slots", "Assigned", "Coverage"],
            [
                (row["year"], row["slots"], row["assigned"], _pct(row["assigned"], row["slots"]))
                for row in career_by_year
            ],
        )
    )
    lines.append("")
    lines.append("## Interpretation")
    lines.append("")
    lines.append(
        "- Stable IDs are stored in `author_identity_ledger` and survive author-table rebuilds. "
        "The ledger records created, reconciled, merged, split, and inactive events; it is not "
        "deleted when `authors` is rebuilt."
    )
    lines.append(
        "- OpenAlex-ID review is explicit: `fragment` means duplicate OpenAlex profiles for one "
        "person; `applied` means a confirmed over-merge was split; `proposed` means the evidence "
        "is insufficient and the author remains flagged."
    )
    lines.append(
        "- Confirmed splits write permanent `author_separation_rules`, so a later rebuild cannot "
        "silently re-merge the two people. The kept group retains the original stable ID; each "
        "new group receives a new stable ID."
    )
    lines.append(
        "- Career assignments here are **byline-only**. Explicit academic/non-academic ranks are "
        "high confidence; student/postdoc keywords are medium confidence. All other slots remain "
        "unknown until the CV timeline layer (M4)."
    )
    lines.append("")

    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    metrics = {
        "generated_at": utcnow(),
        "summary": dict(summary),
        "identity_events": [dict(row) for row in identity_events],
        "merge_candidates": [dict(row) for row in merge_rows],
        "multi_id_review": [dict(row) for row in multi_id_rows],
        "career_stages": [dict(row) for row in stage_rows],
        "career_by_year": [dict(row) for row in career_by_year],
    }
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    return markdown_path, metrics_path


def generate_m4_report(conn, path: Path | None = None) -> tuple[Path, Path]:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    markdown_path = path or (REPORTS_DIR / "m4_quality.md")
    metrics_path = markdown_path.with_suffix(".json")

    summary = conn.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM authors) AS authors,
            (SELECT COUNT(*) FROM authors WHERE orcid IS NOT NULL) AS authors_with_orcid,
            (SELECT COUNT(DISTINCT author_id) FROM career_events
                WHERE source_type='orcid') AS orcid_records,
            (SELECT COUNT(*) FROM career_events WHERE source_type='orcid') AS orcid_events,
            (SELECT COUNT(*) FROM career_events
                WHERE source_type='orcid' AND start_year IS NOT NULL) AS dated_orcid_events,
            (SELECT COUNT(DISTINCT author_id) FROM career_events
                WHERE source_type='orcid') AS authors_with_events,
            (SELECT COUNT(*) FROM career_assignments) AS career_assignments,
            (SELECT COUNT(*) FROM career_assignments
                WHERE evidence_type LIKE 'orcid%') AS orcid_assignments,
            (SELECT COUNT(*) FROM career_assignments
                WHERE evidence_type LIKE 'wayback%') AS wayback_assignments,
            (SELECT COUNT(*) FROM career_assignments
                WHERE evidence_type IN ('byline_rank','byline_affiliation')) AS byline_assignments,
            (SELECT COUNT(*) FROM authorships a
                JOIN papers p ON p.paper_id=a.paper_id
                WHERE p.content_type='article' AND p.is_duplicate=0) AS article_slots,
            (SELECT COUNT(*) FROM authors
                WHERE review_status='orcid_name_conflict') AS orcid_name_conflicts,
            (SELECT COUNT(*) FROM authors
                WHERE review_status='orcid_conflict') AS orcid_conflicts,
            (SELECT COUNT(*) FROM authors
                WHERE orcid IS NOT NULL
                  AND orcid_source IN ('verified_doi','verified_title',
                                       'verified_institution','field_economics')) AS orcid_accepted,
            (SELECT COUNT(*) FROM authors
                WHERE orcid_source='orcid_unverified') AS orcid_unverified,
            (SELECT COUNT(*) FROM authors
                WHERE review_status='orcid_field_mismatch') AS orcid_field_mismatches,
            (SELECT COUNT(*) FROM authors
                WHERE review_status='orcid_unverified_career_risk') AS orcid_career_risk_rejections,
            (SELECT COUNT(*) FROM author_cv_sources) AS cv_sources,
            (SELECT COUNT(*) FROM author_cv_sources WHERE status='parsed') AS cv_parsed,
            (SELECT COUNT(*) FROM career_events WHERE source_type='cv') AS cv_events,
            (SELECT COUNT(*) FROM career_assignments
                WHERE evidence_type LIKE 'cv%') AS cv_assignments,
            (SELECT COUNT(*) FROM career_assignments
                WHERE confidence IN ('high','medium')) AS high_medium_assignments,
            (SELECT COUNT(*) FROM career_assignments
                WHERE confidence='low') AS low_assignments
        """
    ).fetchone()

    event_rows = conn.execute(
        """
        SELECT event_type, source_type, confidence, COUNT(*) AS n
        FROM career_events
        GROUP BY 1, 2, 3
        ORDER BY n DESC, event_type
        """
    ).fetchall()

    assignment_rows = conn.execute(
        """
        SELECT evidence_type, stage, confidence, COUNT(*) AS n
        FROM career_assignments
        GROUP BY 1, 2, 3
        ORDER BY n DESC, stage
        """
    ).fetchall()

    career_by_year = conn.execute(
        """
        SELECT p.published_year AS year,
               COUNT(a.authorship_id) AS slots,
               SUM(CASE WHEN ca.evidence_type IN ('byline_rank','byline_affiliation')
                        THEN 1 ELSE 0 END) AS byline,
               SUM(CASE WHEN ca.evidence_type LIKE 'orcid%' THEN 1 ELSE 0 END) AS orcid,
               SUM(CASE WHEN ca.evidence_type LIKE 'wayback%' THEN 1 ELSE 0 END) AS wayback,
               COUNT(ca.assignment_id) AS assigned
        FROM authorships a
        JOIN papers p ON p.paper_id=a.paper_id
        LEFT JOIN career_assignments ca ON ca.authorship_id=a.authorship_id
        WHERE p.content_type='article' AND p.is_duplicate=0
        GROUP BY p.published_year
        ORDER BY p.published_year
        """
    ).fetchall()

    examples = conn.execute(
        """
        SELECT a.canonical_name, p.published_year, ca.stage, ca.evidence_type,
               ca.confidence, ca.notes, ca.source_url
        FROM career_assignments ca
        JOIN authors a ON a.author_id=ca.author_id
        JOIN papers p ON p.paper_id=ca.paper_id
        WHERE ca.evidence_type LIKE 'orcid%' OR ca.evidence_type LIKE 'cv%'
           OR ca.evidence_type LIKE 'wayback%'
        ORDER BY p.published_year DESC, a.canonical_name
        LIMIT 30
        """
    ).fetchall()

    identity_rows = conn.execute(
        """
        SELECT orcid_source, orcid_match_confidence, COUNT(*) AS n
        FROM authors
        WHERE orcid IS NOT NULL
        GROUP BY 1, 2
        ORDER BY n DESC, orcid_source
        """
    ).fetchall()

    review_rows = conn.execute(
        """
        SELECT review_status, COUNT(*) AS n
        FROM authors
        WHERE review_status LIKE 'orcid_%'
        GROUP BY 1
        ORDER BY n DESC
        """
    ).fetchall()

    assignment_identity_rows = conn.execute(
        """
        SELECT a.orcid_match_confidence AS identity_confidence,
               ca.confidence AS assignment_confidence,
               COUNT(*) AS n
        FROM career_assignments ca
        JOIN authors a ON a.author_id=ca.author_id
        WHERE ca.evidence_type LIKE 'orcid%'
        GROUP BY 1, 2
        ORDER BY identity_confidence, assignment_confidence
        """
    ).fetchall()

    lines: list[str] = []
    lines.append("# M4 Career Evidence Report — AER 2000+")
    lines.append("")
    lines.append(f"Generated: {utcnow()}")
    lines.append("")
    lines.append(
        f"Scope: **{JOURNAL_NAME}** (ISSN 0002-8282), 2000–present. "
        "M4 adds structured ORCID employment/education timelines and uses them "
        "to infer career stage at publication."
    )
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(
        _table(
            ["Metric", "Value"],
            [
                ("Canonical authors", summary["authors"]),
                ("Authors with ORCID", summary["authors_with_orcid"]),
                (
                    "  — accepted identity evidence",
                    summary["orcid_accepted"],
                ),
                ("  — unverified, career events withheld", summary["orcid_unverified"]),
                ("ORCID identities contributing events", summary["orcid_records"]),
                ("ORCID career events", summary["orcid_events"]),
                ("ORCID events with a start year", summary["dated_orcid_events"]),
                ("Career assignments (all sources)", summary["career_assignments"]),
                ("  — byline assignments", summary["byline_assignments"]),
                ("  — ORCID assignments", summary["orcid_assignments"]),
                ("  — Wayback assignments", summary["wayback_assignments"]),
                (
                    "Career coverage (article slots)",
                    _pct(summary["career_assignments"], summary["article_slots"]),
                ),
                ("  — high/medium confidence", summary["high_medium_assignments"]),
                ("  — low confidence", summary["low_assignments"]),
                ("ORCID name conflicts skipped", summary["orcid_name_conflicts"]),
                ("ORCID author conflicts", summary["orcid_conflicts"]),
                ("ORCID field mismatches rejected", summary["orcid_field_mismatches"]),
                (
                    "ORCID career-risk rejections",
                    summary["orcid_career_risk_rejections"],
                ),
                ("CV/homepage sources", summary["cv_sources"]),
                ("CV documents parsed", summary["cv_parsed"]),
                ("CV career events", summary["cv_events"]),
                ("CV assignments", summary["cv_assignments"]),
            ],
        )
    )
    lines.append("")
    lines.append("## ORCID identity confidence")
    lines.append("")
    lines.append(
        "Only ORCID records with direct AER evidence (a matching DOI, paper title, "
        "or institution) or a conservative economics-field signal contribute career "
        "events. Unverified records are retained as weak identity links but their "
        "employment/education events are withheld."
    )
    lines.append("")
    lines.append(
        _table(
            ["ORCID source", "Identity confidence", "Authors"],
            [
                (row["orcid_source"], row["orcid_match_confidence"], row["n"])
                for row in identity_rows
            ],
        )
    )
    lines.append("")
    if review_rows:
        lines.append(
            _table(
                ["ORCID review status", "Authors"],
                [(row["review_status"], row["n"]) for row in review_rows],
            )
        )
        lines.append("")
    if assignment_identity_rows:
        lines.append(
            _table(
                ["ORCID identity confidence", "Assignment confidence", "Assignments"],
                [
                    (row["identity_confidence"], row["assignment_confidence"], row["n"])
                    for row in assignment_identity_rows
                ],
            )
        )
        lines.append("")
    lines.append("## Career events by source and type")
    lines.append("")
    lines.append(
        _table(
            ["Event type", "Source", "Confidence", "Events"],
            [
                (row["event_type"], row["source_type"], row["confidence"], row["n"])
                for row in event_rows
            ],
        )
    )
    lines.append("")
    lines.append("## Career assignments by evidence and stage")
    lines.append("")
    lines.append(
        _table(
            ["Evidence", "Stage", "Confidence", "Slots"],
            [
                (row["evidence_type"], row["stage"], row["confidence"], row["n"])
                for row in assignment_rows
            ],
        )
    )
    lines.append("")
    lines.append("## Career coverage by publication year")
    lines.append("")
    lines.append(
        _table(
            ["Year", "Article slots", "Byline", "ORCID", "Wayback", "Assigned", "Coverage"],
            [
                (
                    row["year"],
                    row["slots"],
                    row["byline"],
                    row["orcid"] or 0,
                    row["wayback"] or 0,
                    row["assigned"],
                    _pct(row["assigned"], row["slots"]),
                )
                for row in career_by_year
            ],
        )
    )
    lines.append("")
    lines.append("## Recent ORCID-derived assignments")
    lines.append("")
    lines.append(
        _table(
            ["Author", "Year", "Stage", "Evidence", "Confidence", "Position", "Source"],
            [
                (
                    row["canonical_name"],
                    row["published_year"],
                    row["stage"],
                    row["evidence_type"],
                    row["confidence"],
                    row["notes"],
                    row["source_url"],
                )
                for row in examples
            ],
        )
    )
    lines.append("")
    lines.append("## Interpretation")
    lines.append("")
    lines.append(
        "- ORCID employment/education records are self-reported and structured. They are used "
        "only when an event's start/end interval covers the paper year; no event means no assignment."
    )
    lines.append(
        "- Explicit rank titles (Assistant/Associate/Full Professor, Lecturer, Research Fellow, "
        "Postdoc, Emeritus) are high confidence. Generic \"Professor\" titles are stored as "
        "full professor with low confidence because the title may be current rather than the "
        "rank at the paper date."
    )
    lines.append(
        "- Doctoral education intervals are used for `phd_student` at medium confidence only when "
        "the paper year falls inside the degree interval."
    )
    lines.append(
        "- Byline evidence remains paper-specific and takes precedence over ORCID for the same slot. "
        "ORCID fills slots that the byline cannot explain."
    )
    lines.append(
        "- ORCID coverage is not complete: a large share of authors have an ORCID, but many records "
        "lack dates or employment entries. CV discovery and parsing are still required for the "
        "remaining authors and for rank changes that ORCID does not record."
    )
    lines.append(
        "- ORCID identity is validated before its events are used. A matching AER DOI is the "
        "strongest signal; a matching work title or an institution overlap is also accepted. "
        "A conservative economics-field signal is accepted only at low confidence. Records with "
        "a conflicting person name, a clearly non-economics field, or a career-changing event "
        "but no positive evidence are rejected. Records with no positive evidence and no "
        "career-changing event remain as low-confidence identity links with events withheld."
    )
    lines.append(
        "- CV events come from public CVs/faculty pages discovered through ORCID researcher URLs. "
        "The parser is conservative and section-based; CV assignments are used only after byline "
        "and ORCID evidence, and raw CVs are stored only in the local ignored cache."
    )
    lines.append("")

    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    metrics = {
        "generated_at": utcnow(),
        "summary": dict(summary),
        "career_events": [dict(row) for row in event_rows],
        "career_assignments": [dict(row) for row in assignment_rows],
        "career_by_year": [dict(row) for row in career_by_year],
        "examples": [dict(row) for row in examples],
        "orcid_identity": [dict(row) for row in identity_rows],
        "orcid_review": [dict(row) for row in review_rows],
        "orcid_assignment_identity": [
            dict(row) for row in assignment_identity_rows
        ],
    }
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    return markdown_path, metrics_path

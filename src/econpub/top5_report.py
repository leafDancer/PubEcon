from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import REPORTS_DIR
from .coverage import _table

JOURNAL_ORDER = ["AER", "QJE", "JPE", "RES", "ECMA"]


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _dicts(rows) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def generate_top5_report(conn, path: Path | None = None) -> tuple[Path, Path]:
    """Report the combined top-five dataset by journal and evidence source."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    markdown_path = path or (REPORTS_DIR / "top5_quality.md")
    metrics_path = markdown_path.with_suffix(".json")

    inventory = _dicts(
        conn.execute(
            """
            SELECT COALESCE(journal_code,'AER') AS journal,
                   COUNT(*) AS records,
                   SUM(CASE WHEN content_type='article' AND is_duplicate=0 THEN 1 ELSE 0 END) AS articles,
                   SUM(CASE WHEN content_type='duplicate' THEN 1 ELSE 0 END) AS duplicates,
                   SUM(CASE WHEN content_type='erratum' THEN 1 ELSE 0 END) AS errata,
                   SUM(CASE WHEN content_type='front_matter' THEN 1 ELSE 0 END) AS front_matter,
                   SUM(CASE WHEN content_type='association_report' THEN 1 ELSE 0 END) AS association_reports,
                   SUM(CASE WHEN content_type='supplement' THEN 1 ELSE 0 END) AS supplements,
                   SUM(CASE WHEN content_type='book_review' THEN 1 ELSE 0 END) AS book_reviews,
                   SUM(CASE WHEN content_type='unattributed' THEN 1 ELSE 0 END) AS unattributed,
                   SUM(CASE WHEN content_type='article' AND is_duplicate=0
                            AND abstract IS NOT NULL AND abstract<>'' THEN 1 ELSE 0 END) AS abstracts
            FROM papers
            GROUP BY COALESCE(journal_code,'AER')
            """
        )
    )
    by_journal = {row["journal"]: row for row in inventory}

    career = _dicts(
        conn.execute(
            """
            SELECT p.journal_code AS journal,
                   COUNT(*) AS slots,
                   SUM(CASE WHEN ca.authorship_id IS NOT NULL THEN 1 ELSE 0 END) AS assigned,
                   SUM(CASE WHEN ca.confidence IN ('high','medium') THEN 1 ELSE 0 END) AS high_medium
            FROM authorships s
            JOIN papers p ON p.paper_id=s.paper_id
            LEFT JOIN career_assignments ca ON ca.authorship_id=s.authorship_id
            WHERE p.content_type='article' AND p.is_duplicate=0
            GROUP BY p.journal_code
            """
        )
    )
    career_by_journal = {row["journal"]: row for row in career}

    evidence = _dicts(
        conn.execute(
            """
            SELECT evidence_type, confidence, COUNT(*) AS n
            FROM career_assignments
            GROUP BY evidence_type, confidence
            ORDER BY n DESC
            """
        )
    )
    orcid_tiers = _dicts(
        conn.execute(
            """
            SELECT orcid_source, COUNT(*) AS n
            FROM authors WHERE orcid IS NOT NULL
            GROUP BY orcid_source ORDER BY n DESC
            """
        )
    )
    reach = _dicts(
        conn.execute(
            """
            SELECT journal_count, COUNT(*) AS authors
            FROM (
                SELECT a.author_id, COUNT(DISTINCT p.journal_code) AS journal_count
                FROM authors a
                JOIN authorships s ON s.author_id=a.author_id
                JOIN papers p ON p.paper_id=s.paper_id
                    AND p.content_type='article' AND p.is_duplicate=0
                GROUP BY a.author_id
            )
            GROUP BY journal_count ORDER BY journal_count
            """
        )
    )
    top_cross = _dicts(
        conn.execute(
            """
            SELECT a.canonical_name AS name,
                   COUNT(DISTINCT p.journal_code) AS journals,
                   COUNT(DISTINCT p.paper_id) AS papers
            FROM authors a
            JOIN authorships s ON s.author_id=a.author_id
            JOIN papers p ON p.paper_id=s.paper_id
                AND p.content_type='article' AND p.is_duplicate=0
            GROUP BY a.author_id
            ORDER BY journals DESC, papers DESC, a.canonical_name
            LIMIT 12
            """
        )
    )
    merge_status = _dicts(
        conn.execute(
            "SELECT status, COUNT(*) AS n FROM author_merge_candidates GROUP BY status"
        )
    )
    review_status = _dicts(
        conn.execute(
            """
            SELECT COALESCE(review_status,'unspecified') AS status, COUNT(*) AS n
            FROM authors WHERE needs_review=1
            GROUP BY 1 ORDER BY n DESC
            """
        )
    )
    unattributed_samples = _dicts(
        conn.execute(
            """
            SELECT COALESCE(journal_code,'AER') AS journal, title, published_year
            FROM papers
            WHERE content_type='unattributed'
            ORDER BY journal, published_year
            """
        )
    )
    cv = conn.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM author_cv_sources) AS sources,
            (SELECT COUNT(*) FROM author_cv_sources WHERE status='candidate') AS candidates,
            (SELECT COUNT(*) FROM author_cv_sources WHERE status='parsed') AS parsed,
            (SELECT COUNT(*) FROM author_cv_sources WHERE status='failed') AS failed,
            (SELECT COUNT(*) FROM career_events WHERE source_type='cv') AS events,
            (SELECT COUNT(*) FROM career_assignments WHERE evidence_type LIKE 'cv%') AS assignments,
            (SELECT COUNT(DISTINCT author_id) FROM career_events WHERE source_type='cv') AS authors
        """
    ).fetchone()
    totals = conn.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM papers) AS records,
            (SELECT COUNT(*) FROM papers WHERE content_type='article' AND is_duplicate=0) AS articles,
            (SELECT COUNT(*) FROM authorships s JOIN papers p ON p.paper_id=s.paper_id
                WHERE p.content_type='article' AND p.is_duplicate=0) AS slots,
            (SELECT COUNT(*) FROM authors) AS authors,
            (SELECT COUNT(*) FROM coauthorship_edges) AS edges,
            (SELECT COUNT(*) FROM career_assignments) AS assignments,
            (SELECT COUNT(*) FROM authors WHERE needs_review=1) AS needs_review,
            (SELECT COUNT(*) FROM author_separation_rules) AS separation_rules
        """
    ).fetchone()

    metrics = {
        "generated_at": _utcnow(),
        "totals": dict(totals),
        "inventory": inventory,
        "career_by_journal": career,
        "career_evidence": evidence,
        "cv": dict(cv),
        "orcid_tiers": orcid_tiers,
        "journal_reach": reach,
        "top_cross_journal_authors": top_cross,
        "merge_status": merge_status,
        "review_status": review_status,
        "unattributed": unattributed_samples,
    }
    metrics_path.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    lines: list[str] = []
    lines.append("# Top-five dataset report")
    lines.append("")
    lines.append(f"Generated {metrics['generated_at']}.")
    lines.append("")
    lines.append(
        "Scope: *American Economic Review*, *Quarterly Journal of Economics*, "
        "*Journal of Political Economy*, *Review of Economic Studies*, and "
        "*Econometrica*, 2000–present. AER includes Papers & Proceedings through "
        "2017. Counts are research articles unless stated otherwise."
    )
    lines.append("")
    lines.append("## At a glance")
    lines.append("")
    lines.append(
        _table(
            ["Metric", "Value"],
            [
                ("Crossref records", totals["records"]),
                ("Research articles", totals["articles"]),
                ("Author slots", totals["slots"]),
                ("Canonical authors", totals["authors"]),
                ("Coauthorship edges", totals["edges"]),
                ("Career assignments", totals["assignments"]),
                ("Authors flagged for review", totals["needs_review"]),
                ("Separation rules", totals["separation_rules"]),
            ],
        )
    )
    lines.append("")
    lines.append("## Inventory by journal")
    lines.append("")
    lines.append(
        _table(
            [
                "Journal",
                "Records",
                "Articles",
                "Duplicates",
                "Errata",
                "Front matter",
                "Society reports",
                "Supplements",
                "Book reviews",
                "Unattributed",
                "Abstracts",
            ],
            [
                (
                    row["journal"],
                    row["records"],
                    row["articles"],
                    row["duplicates"],
                    row["errata"],
                    row["front_matter"],
                    row["association_reports"],
                    row["supplements"],
                    row["book_reviews"],
                    row["unattributed"],
                    row["abstracts"],
                )
                for row in sorted(
                    inventory,
                    key=lambda item: (
                        JOURNAL_ORDER.index(item["journal"])
                        if item["journal"] in JOURNAL_ORDER
                        else 99
                    ),
                )
            ],
        )
    )
    lines.append("")
    lines.append("## Career coverage by journal")
    lines.append("")
    career_rows = []
    for journal in JOURNAL_ORDER:
        row = career_by_journal.get(journal)
        if not row:
            continue
        coverage = 100.0 * row["assigned"] / row["slots"] if row["slots"] else 0.0
        career_rows.append(
            (
                journal,
                row["slots"],
                row["assigned"],
                f"{coverage:.1f}%",
                row["high_medium"],
            )
        )
    lines.append(
        _table(
            ["Journal", "Slots", "Assigned", "Coverage", "High/medium"],
            career_rows,
        )
    )
    lines.append("")
    lines.append(
        "Career evidence is ORCID and CV only for the new journals. AER also has "
        "byline rank evidence. Unknown slots are not imputed."
    )
    lines.append("")
    lines.append("## CV coverage")
    lines.append("")
    lines.append(
        _table(
            ["Metric", "Value"],
            [
                ("CV/homepage sources", cv["sources"]),
                ("  — candidates not yet processed", cv["candidates"]),
                ("  — parsed documents", cv["parsed"]),
                ("  — failed", cv["failed"]),
                ("Authors with CV events", cv["authors"]),
                ("CV career events", cv["events"]),
                ("CV career assignments", cv["assignments"]),
            ],
        )
    )
    lines.append("")
    lines.append(
        "The CV crawl is resumable. A non-zero candidate count is a visible queue, "
        "not a claim that no CV exists."
    )
    lines.append("")
    lines.append("## Career evidence")
    lines.append("")
    lines.append(
        _table(
            ["Evidence", "Confidence", "Assignments"],
            [(row["evidence_type"], row["confidence"], row["n"]) for row in evidence],
        )
    )
    lines.append("")
    lines.append("## Cross-journal reach")
    lines.append("")
    lines.append(
        _table(
            ["Journals per author", "Authors"],
            [(row["journal_count"], row["authors"]) for row in reach],
        )
    )
    lines.append("")
    lines.append(
        _table(
            ["Author", "Journals", "Papers"],
            [(row["name"], row["journals"], row["papers"]) for row in top_cross],
        )
    )
    lines.append("")
    lines.append("## Identity")
    lines.append("")
    lines.append(
        _table(
            ["ORCID tier", "Authors"],
            [(row["orcid_source"], row["n"]) for row in orcid_tiers],
        )
    )
    lines.append("")
    if merge_status:
        lines.append(
            _table(
                ["Merge candidate status", "Pairs"],
                [(row["status"], row["n"]) for row in merge_status],
            )
        )
        lines.append("")
    if review_status:
        lines.append(
            _table(
                ["Review status", "Authors"],
                [(row["status"], row["n"]) for row in review_status],
            )
        )
        lines.append("")
    lines.append("## Missingness")
    lines.append("")
    unattributed_by_journal: dict[str, list[dict[str, Any]]] = {}
    for row in unattributed_samples:
        unattributed_by_journal.setdefault(row["journal"], []).append(row)
    for journal in JOURNAL_ORDER:
        rows = unattributed_by_journal.get(journal, [])
        if not rows:
            continue
        lines.append(
            f"- **{journal}:** {len(rows)} unattributed records. Examples: "
            + "; ".join(
                f"“{(row['title'] or 'untitled')[:90]}” ({row['published_year']})"
                for row in rows[:3]
            )
            + "."
        )
    lines.append("")
    missing_abstracts = [
        (
            row["journal"],
            row["articles"] - row["abstracts"],
            f"{100.0 * row['abstracts'] / row['articles']:.1f}%"
            if row["articles"]
            else "0%",
        )
        for row in inventory
        if row["articles"]
    ]
    lines.append(
        _table(
            ["Journal", "Articles without abstract", "Abstract coverage"],
            missing_abstracts,
        )
    )
    lines.append("")
    lines.append("## Interpretation")
    lines.append("")
    lines.append(
        "- Crossref is the primary record. OpenAlex supplies DOI-keyed enrichment "
        "and may supply a missing byline; those rows are marked "
        "`openalex_backfill` and never replace a Crossref author."
    )
    lines.append(
        "- Journal is a first-class dimension. Duplicate detection is scoped by "
        "journal, so identical titles in different journals are not merged."
    )
    lines.append(
        "- AER P&P records are included through 2017. The P&P flag is not applied "
        "to other journals."
    )
    lines.append(
        "- ORCID events are used only after identity validation against the "
        "author's papers. Unverified links keep their identity record but their "
        "events are withheld."
    )
    lines.append(
        "- Missing data stays missing. No stage is inferred from age, seniority, "
        "or a current title when the dated evidence does not cover the paper."
    )
    lines.append("")

    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    return markdown_path, metrics_path

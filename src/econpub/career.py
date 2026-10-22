from __future__ import annotations

import logging
import re
import sqlite3
from collections import Counter
from typing import Any

from . import db

log = logging.getLogger(__name__)

STAGE_MAP = {
    "assistant_professor": "assistant_professor",
    "associate_professor": "associate_professor",
    "full_professor": "full_professor",
    "lecturer_other_academic": "lecturer_other_academic",
    "other_academic": "lecturer_other_academic",
    "research_fellow": "research_fellow",
    "emeritus": "emeritus",
    "phd_student": "phd_student",
    "non_academic": "non_academic",
}

STUDENT_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"\bph\.?\s*d\.?\s+(student|candidate)\b", re.IGNORECASE), "phd_student", "PhD student"),
    (re.compile(r"\bdoctoral\s+(student|candidate)\b", re.IGNORECASE), "phd_student", "doctoral student"),
    (
        re.compile(
            r"\bgraduate\s+student\b(?!\s+(?:mailbox|mailboxes|office|mailing))",
            re.IGNORECASE,
        ),
        "phd_student",
        "graduate student",
    ),
    (re.compile(r"\bmaster'?s?\s+(student|candidate)\b", re.IGNORECASE), "masters_student", "master's student"),
    (re.compile(r"\bundergraduate\b", re.IGNORECASE), "undergraduate", "undergraduate"),
    (re.compile(r"\bpost-?doc(toral)?\b", re.IGNORECASE), "postdoc", "postdoc"),
]


def infer_byline_career(conn: sqlite3.Connection) -> dict[str, Any]:
    """Build career assignments from publish-time byline evidence only.

    This is deliberately conservative. A row is written only when the byline
    states a rank or a student/postdoc status. Everything else stays missing
    until the CV timeline layer (M4).
    """
    conn.execute(
        "DELETE FROM career_assignments WHERE evidence_type IN ('byline_rank','byline_affiliation')"
    )
    rows = conn.execute(
        """
        SELECT a.authorship_id, a.author_id, a.paper_id, a.rank_category, a.rank_raw,
               a.affiliation_raw, p.doi, p.published_year
        FROM authorships a
        JOIN papers p ON p.paper_id = a.paper_id
        WHERE p.content_type='article' AND p.is_duplicate=0 AND a.author_id IS NOT NULL
        """
    ).fetchall()
    now = db.utcnow()
    stage_counts: Counter[str] = Counter()
    evidence_counts: Counter[str] = Counter()
    assigned = 0
    for row in rows:
        stage = STAGE_MAP.get((row["rank_category"] or "").strip())
        evidence_type = "byline_rank"
        confidence = "high"
        notes = row["rank_raw"] or row["rank_category"]
        if stage is None:
            affiliation = row["affiliation_raw"] or ""
            for pattern, candidate_stage, label in STUDENT_PATTERNS:
                if pattern.search(affiliation):
                    stage = candidate_stage
                    evidence_type = "byline_affiliation"
                    confidence = "medium"
                    notes = f"{label}: {affiliation}"
                    break
        if stage is None:
            continue
        source_url = f"https://doi.org/{row['doi']}" if row["doi"] else None
        conn.execute(
            """
            INSERT INTO career_assignments
                (authorship_id, author_id, paper_id, stage, evidence_type, confidence,
                 source_url, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["authorship_id"],
                row["author_id"],
                row["paper_id"],
                stage,
                evidence_type,
                confidence,
                source_url,
                notes,
                now,
            ),
        )
        assigned += 1
        stage_counts[stage] += 1
        evidence_counts[evidence_type] += 1
    conn.commit()
    stats = {
        "assigned": assigned,
        "by_stage": dict(stage_counts),
        "by_evidence": dict(evidence_counts),
        "unknown_slots": len(rows) - assigned,
    }
    log.info("Byline career assignments: %s", stats)
    return stats

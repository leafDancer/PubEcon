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

ROLE_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"\bemerit(?:us|a)\b", re.IGNORECASE), "emeritus", "high"),
    (
        re.compile(
            r"\bph\.?\s*d\.?\s+(?:student|candidate)\b|\bdoctoral\s+(?:student|candidate)\b|"
            r"\bgraduate\s+student\b",
            re.IGNORECASE,
        ),
        "phd_student",
        "high",
    ),
    (re.compile(r"\bpost-?doc(?:toral)?\b", re.IGNORECASE), "postdoc", "high"),
    (re.compile(r"\b(?:assistant|asst\.?)\s+(?:professor|prof\.?)\b", re.IGNORECASE), "assistant_professor", "high"),
    (re.compile(r"\b(?:associate|assoc\.?)\s+(?:professor|prof\.?)\b", re.IGNORECASE), "associate_professor", "high"),
    (re.compile(r"\bfull\s+professor\b", re.IGNORECASE), "full_professor", "high"),
    (re.compile(r"\bchair\s+professor\b", re.IGNORECASE), "full_professor", "high"),
    (re.compile(r"\b(?:senior\s+)?lecturer\b|\breader\b|\binstructor\b", re.IGNORECASE), "lecturer_other_academic", "high"),
    (re.compile(r"\bresearch\s+(?:fellow|scientist)\b", re.IGNORECASE), "research_fellow", "high"),
    (re.compile(r"\bprofessor\b", re.IGNORECASE), "full_professor", "low"),
    (
        re.compile(
            r"\b(?:economist|research economist|analyst|consultant|director|manager|"
            r"advisor|adviser|central bank|federal reserve|world bank|imf|treasury|"
            r"ministry|government)\b",
            re.IGNORECASE,
        ),
        "non_academic",
        "medium",
    ),
]

STAGE_PRIORITY = {
    "full_professor": 0,
    "associate_professor": 1,
    "assistant_professor": 2,
    "lecturer_other_academic": 3,
    "research_fellow": 4,
    "postdoc": 5,
    "emeritus": 6,
    "non_academic": 7,
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


def classify_role(title: str | None) -> tuple[str | None, str]:
    text = (title or "").strip()
    if not text:
        return None, "low"
    for pattern, stage, confidence in ROLE_PATTERNS:
        if pattern.search(text):
            return stage, confidence
    return None, "low"


def _event_covers(event: sqlite3.Row, year: int) -> bool:
    start = event["start_year"]
    end = event["end_year"]
    if start is None:
        return False
    if year < int(start):
        return False
    if end is None:
        return True
    return year <= int(end)


def _is_doctoral(title: str | None) -> bool:
    return bool(
        re.search(r"\bph\.?\s*d\.?\b|\bdoctor(?:ate|al)?\b", title or "", re.IGNORECASE)
    )


def _assign_structured_careers(
    conn: sqlite3.Connection,
    *,
    source_type: str,
    employment_evidence: str,
    education_evidence: str,
    skip_types: tuple[str, ...],
    replace_types: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Assign career stages from structured career events.

    Higher-priority evidence (byline, or ORCID before CV) is never overwritten.
    A stage is assigned only when an event's start/end interval covers the
    paper year.
    """
    conn.execute(
        "DELETE FROM career_assignments WHERE evidence_type IN (?, ?)",
        (employment_evidence, education_evidence),
    )
    skip_placeholders = ",".join("?" for _ in skip_types)
    rows = conn.execute(
        f"""
        SELECT s.authorship_id, s.author_id, s.paper_id, p.published_year, p.doi
        FROM authorships s
        JOIN papers p ON p.paper_id = s.paper_id
        WHERE p.content_type='article' AND p.is_duplicate=0
          AND s.author_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM career_assignments ca
              WHERE ca.authorship_id = s.authorship_id
                AND ca.evidence_type IN ({skip_placeholders})
          )
        """,
        skip_types,
    ).fetchall()
    now = db.utcnow()
    stage_counts: Counter[str] = Counter()
    evidence_counts: Counter[str] = Counter()
    confidence_counts: Counter[str] = Counter()
    assigned = 0
    for row in rows:
        year = row["published_year"]
        if year is None:
            continue
        events = conn.execute(
            """
            SELECT event_id, event_type, title, institution, start_year, end_year,
                   is_current, confidence, source_url, source_snippet
            FROM career_events
            WHERE author_id=? AND source_type=?
            """,
            (row["author_id"], source_type),
        ).fetchall()
        employment = []
        for event in events:
            if event["event_type"] != "employment" or not _event_covers(event, int(year)):
                continue
            stage, role_confidence = classify_role(event["title"])
            if stage is None:
                continue
            employment.append((event, stage, role_confidence))
        chosen = None
        if employment:
            # A concurrent research fellowship should not outrank a professorship.
            # Prefer the more senior academic rank; an explicit emeritus event
            # wins over an older, open-ended professorship.
            emeritus = [item for item in employment if item[1] == "emeritus"]
            if emeritus:
                chosen = max(emeritus, key=lambda item: item[0]["start_year"] or 0)
            else:
                specificity = {"high": 3, "medium": 2, "low": 2}
                employment.sort(
                    key=lambda item: (
                        -specificity.get(item[2], 1),
                        -(item[0]["start_year"] or 0),
                        STAGE_PRIORITY.get(item[1], 99),
                    )
                )
                chosen = employment[0]
            evidence_type = employment_evidence
        else:
            education = [
                event
                for event in events
                if event["event_type"] == "education"
                and event["end_year"] is not None
                and _event_covers(event, int(year))
                and _is_doctoral(event["title"])
            ]
            if not education:
                continue
            event = sorted(
                education, key=lambda value: -(value["start_year"] or 0)
            )[0]
            chosen = (event, "phd_student", "medium")
            evidence_type = education_evidence
        event, stage, role_confidence = chosen
        if event["confidence"] == "high" and role_confidence == "high":
            confidence = "high"
        elif event["confidence"] in {"high", "medium"} and role_confidence in {"high", "medium"}:
            confidence = "medium"
        else:
            confidence = "low"
        if replace_types:
            replace_placeholders = ",".join("?" for _ in replace_types)
            conn.execute(
                f"""
                DELETE FROM career_assignments
                WHERE authorship_id=? AND evidence_type IN ({replace_placeholders})
                """,
                (row["authorship_id"], *replace_types),
            )
        conn.execute(
            """
            INSERT INTO career_assignments
                (authorship_id, author_id, paper_id, stage, evidence_type, confidence,
                 source_url, notes, career_event_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["authorship_id"],
                row["author_id"],
                row["paper_id"],
                stage,
                evidence_type,
                confidence,
                event["source_url"],
                (
                    f"{event['title']}; {event['institution']}"
                    + (
                        " (generic professor title; rank uncertain)"
                        if role_confidence == "low"
                        else ""
                    )
                ),
                event["event_id"],
                now,
            ),
        )
        assigned += 1
        stage_counts[stage] += 1
        evidence_counts[evidence_type] += 1
        confidence_counts[confidence] += 1
    conn.commit()
    stats = {
        "source": source_type,
        "eligible_slots": len(rows),
        "assigned": assigned,
        "by_stage": dict(stage_counts),
        "by_evidence": dict(evidence_counts),
        "by_confidence": dict(confidence_counts),
    }
    log.info("%s career assignments: %s", source_type, stats)
    return stats


def assign_orcid_careers(conn: sqlite3.Connection) -> dict[str, Any]:
    return _assign_structured_careers(
        conn,
        source_type="orcid",
        employment_evidence="orcid_employment",
        education_evidence="orcid_education",
        skip_types=("byline_rank", "byline_affiliation"),
        replace_types=("cv_employment", "cv_education"),
    )


def assign_wayback_careers(conn: sqlite3.Connection) -> dict[str, Any]:
    """Assign stages from point-in-time faculty/homepage snapshots.

    Wayback evidence is contemporaneous with the paper year but noisier than
    an explicit byline or a validated ORCID interval, so it sits between ORCID
    and CV evidence and caps out at medium confidence.
    """
    return _assign_structured_careers(
        conn,
        source_type="wayback",
        employment_evidence="wayback_employment",
        education_evidence="wayback_education",
        skip_types=(
            "byline_rank",
            "byline_affiliation",
            "orcid_employment",
            "orcid_education",
        ),
        replace_types=("cv_employment", "cv_education"),
    )


def assign_cv_careers(conn: sqlite3.Connection) -> dict[str, Any]:
    return _assign_structured_careers(
        conn,
        source_type="cv",
        employment_evidence="cv_employment",
        education_evidence="cv_education",
        skip_types=(
            "byline_rank",
            "byline_affiliation",
            "orcid_employment",
            "orcid_education",
            "wayback_employment",
            "wayback_education",
        ),
    )


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
        # Byline evidence is paper-specific and outranks any prior ORCID/CV
        # assignment for the same slot.
        conn.execute(
            "DELETE FROM career_assignments WHERE authorship_id=?",
            (row["authorship_id"],),
        )
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

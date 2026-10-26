from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from .normalize import clean_text

# CVs sometimes place personal details on the same line as an education or
# employment entry. The public record only keeps structured degree/employment
# facts, so cut the line at the first personal-information marker.
_PII_MARKER = re.compile(
    r"(?:personal\s*information|date\s*of\s*birth|\bbirth\s*date\b|\bborn\b|"
    r"\bnationality\b|\bcitizenship\b|\baddress\b|\bphone\b|"
    r"\btelephone\b|\be-?mail\b)\s*[:\-]?",
    re.IGNORECASE,
)
_EMAIL = re.compile(r"[\w.+-]+@[^\s,;()]+\.[^\s,;()]+", re.UNICODE)


def strip_personal_info(value: Any, *, cut_personal_markers: bool = True) -> str | None:
    """Remove personal details that must never enter the public record.

    Affiliation strings are institutional addresses, so callers can keep their
    address text while still removing embedded email addresses.
    """
    text = clean_text(value)
    if not text:
        return None
    if cut_personal_markers:
        marker = _PII_MARKER.search(text)
        if marker:
            text = text[: marker.start()]
    text = _EMAIL.sub(" ", text)
    cleaned = clean_text(text).strip(" ,;:-")
    return cleaned or None


def structured_snippet(
    event_type: str,
    title: str | None,
    institution: str | None,
    start_year: int | None,
    end_year: int | None,
    is_current: bool | int | None,
) -> str:
    """The only snippet we keep for CV events: normalized structured facts."""
    if event_type == "education":
        payload = {
            "degree": strip_personal_info(title),
            "institution": strip_personal_info(institution),
            "start": start_year,
            "end": end_year,
        }
    else:
        payload = {
            "role": strip_personal_info(title),
            "institution": strip_personal_info(institution),
            "start": start_year,
            "end": end_year,
            "current": bool(is_current),
        }
    return json.dumps(payload, ensure_ascii=False)


def sanitize_affiliations(conn: sqlite3.Connection) -> dict[str, int]:
    """Remove emails and other personal details from affiliation strings."""
    fields = [
        ("authorships", ("authorship_id",), "affiliation_raw"),
        ("authorships", ("authorship_id",), "institution_hint"),
        ("authorships", ("authorship_id",), "openalex_institution_name"),
        ("authorships", ("authorship_id",), "openalex_raw_affiliation"),
        ("authorship_institutions", ("authorship_id", "institution_id", "source"), "raw_name"),
        ("institutions", ("institution_id",), "display_name"),
    ]
    changed = 0
    scanned = 0
    for table, keys, column in fields:
        key_sql = ", ".join(f'"{key}"' for key in keys)
        where_sql = " AND ".join(f'"{key}"=?' for key in keys)
        rows = conn.execute(f'SELECT {key_sql}, "{column}" FROM "{table}"').fetchall()
        for row in rows:
            scanned += 1
            cleaned = strip_personal_info(row[column], cut_personal_markers=False)
            if cleaned != row[column]:
                conn.execute(
                    f'UPDATE "{table}" SET "{column}"=? WHERE {where_sql}',
                    (cleaned, *[row[key] for key in keys]),
                )
                changed += 1
    conn.commit()
    return {"fields_scanned": scanned, "changed": changed}


def sanitize_career_events(conn: sqlite3.Connection) -> dict[str, int]:
    """Scrub existing career events and replace raw CV snippets with facts.

    This is idempotent and safe to run on both databases. It is the repair path
    for databases built before the CV parser stopped retaining raw CV lines.
    """
    rows = conn.execute(
        """
        SELECT event_id, event_type, title, institution, start_year, end_year,
               is_current, source_type, source_snippet
        FROM career_events
        """
    ).fetchall()
    changed = 0
    for row in rows:
        title = strip_personal_info(row["title"])
        institution = strip_personal_info(row["institution"])
        snippet = row["source_snippet"]
        if row["source_type"] == "cv":
            snippet = structured_snippet(
                row["event_type"],
                title,
                institution,
                row["start_year"],
                row["end_year"],
                row["is_current"],
            )
        if (
            title != row["title"]
            or institution != row["institution"]
            or snippet != row["source_snippet"]
        ):
            conn.execute(
                """
                UPDATE career_events
                SET title=?, institution=?, source_snippet=?
                WHERE event_id=?
                """,
                (title, institution, snippet, row["event_id"]),
            )
            changed += 1
    conn.commit()
    return {"scanned": len(rows), "changed": changed}

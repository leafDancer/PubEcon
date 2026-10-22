from __future__ import annotations

import logging
import re
import sqlite3
from collections import defaultdict
from typing import Any, Iterable

from . import db
from .normalize import name_key, name_match_key, normalize_name_part, normalize_orcid

log = logging.getLogger(__name__)

STABLE_PREFIX = "aer-a-"
STABLE_WIDTH = 6
_INSTITUTION_STOPWORDS = {
    "university",
    "univ",
    "college",
    "school",
    "institute",
    "department",
    "dept",
    "economics",
    "economic",
    "the",
    "of",
    "and",
    "for",
    "at",
    "in",
    "center",
    "centre",
    "research",
    "national",
    "bureau",
    "federal",
    "reserve",
    "bank",
    "board",
    "professor",
    "assistant",
    "associate",
    "senior",
}


def _next_number(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT MAX(CAST(SUBSTR(stable_id, ?) AS INTEGER)) FROM author_identity_ledger",
        (len(STABLE_PREFIX) + 1,),
    ).fetchone()
    return int(row[0] or 0) + 1


def _new_stable_ids(conn: sqlite3.Connection, count: int) -> list[str]:
    start = _next_number(conn)
    return [f"{STABLE_PREFIX}{start + offset:0{STABLE_WIDTH}d}" for offset in range(count)]


def _year_overlap(left_first, left_last, right_first, right_last) -> bool:
    if left_first is None or left_last is None or right_first is None or right_last is None:
        return False
    return not (left_last < right_first or right_last < left_first)


def _institution_tokens(text: str | None) -> set[str]:
    if not text:
        return set()
    tokens = set(normalize_name_part(text).split())
    return {token for token in tokens if len(token) >= 2 and token not in _INSTITUTION_STOPWORDS}


def _author_profile(conn: sqlite3.Connection, author_id: int) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT a.author_id, a.stable_id, a.canonical_name, a.given_name, a.family_name,
               a.orcid, a.openalex_id, a.name_key, a.match_key
        FROM authors a WHERE a.author_id=?
        """,
        (author_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"unknown author_id {author_id}")
    aggregate = conn.execute(
        """
        SELECT MIN(p.published_year) AS first_year,
               MAX(p.published_year) AS last_year,
               GROUP_CONCAT(DISTINCT a.openalex_author_id) AS openalex_ids,
               GROUP_CONCAT(DISTINCT a.institution_hint) AS crossref_institutions,
               GROUP_CONCAT(DISTINCT a.openalex_institution_name) AS openalex_institutions
        FROM authorships a
        JOIN papers p ON p.paper_id = a.paper_id
        WHERE a.author_id=?
        """,
        (author_id,),
    ).fetchone()
    institutions = ", ".join(
        value
        for value in (
            aggregate["crossref_institutions"],
            aggregate["openalex_institutions"],
        )
        if value
    )
    return {
        "author_id": int(row["author_id"]),
        "stable_id": row["stable_id"],
        "canonical_name": row["canonical_name"],
        "given_name": row["given_name"],
        "family_name": row["family_name"],
        "orcid": normalize_orcid(row["orcid"]),
        "openalex_id": row["openalex_id"],
        "openalex_ids": {
            value for value in str(aggregate["openalex_ids"] or "").split(",") if value
        },
        "name_key": row["name_key"],
        "match_key": row["match_key"],
        "first_year": aggregate["first_year"],
        "last_year": aggregate["last_year"],
        "institutions": institutions,
        "institution_tokens": _institution_tokens(institutions),
        "normalized_name": normalize_name_part(row["canonical_name"]),
    }


def _ledger_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in conn.execute(
            """
            SELECT stable_id, orcid, openalex_id, canonical_name, given_name, family_name,
                   name_key, match_key, first_year, last_year, institutions,
                   current_author_id, status
            FROM author_identity_ledger
            ORDER BY stable_id
            """
        ).fetchall()
    ]


def ensure_identity_ledger(conn: sqlite3.Connection) -> int:
    """Initialise stable IDs for the current author table if needed.

    Idempotent. It assigns a stable ID to every author that lacks one and
    writes the corresponding ledger row. Existing stable IDs are preserved.
    """
    ledger_count = conn.execute("SELECT COUNT(*) FROM author_identity_ledger").fetchone()[0]
    if ledger_count:
        return 0
    authors = conn.execute(
        "SELECT author_id FROM authors WHERE stable_id IS NULL ORDER BY author_id"
    ).fetchall()
    if not authors:
        return 0
    stable_ids = _new_stable_ids(conn, len(authors))
    now = db.utcnow()
    for row, stable_id in zip(authors, stable_ids):
        profile = _author_profile(conn, int(row["author_id"]))
        conn.execute(
            "UPDATE authors SET stable_id=?, updated_at=? WHERE author_id=?",
            (stable_id, now, profile["author_id"]),
        )
        conn.execute(
            """
            INSERT INTO author_identity_ledger
                (stable_id, orcid, openalex_id, canonical_name, given_name, family_name,
                 name_key, match_key, first_year, last_year, institutions,
                 current_author_id, status, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
            """,
            (
                stable_id,
                profile["orcid"] or None,
                profile["openalex_id"],
                profile["canonical_name"],
                profile["given_name"],
                profile["family_name"],
                profile["name_key"],
                profile["match_key"],
                profile["first_year"],
                profile["last_year"],
                profile["institutions"] or None,
                profile["author_id"],
                now,
            ),
        )
        _record_event(conn, stable_id, "created", profile["author_id"], None, "initial assignment")
    conn.commit()
    log.info("Assigned %s initial stable author IDs", len(authors))
    return len(authors)


def _record_event(
    conn: sqlite3.Connection,
    stable_id: str,
    event_type: str,
    author_id: int | None,
    related_stable_id: str | None,
    reason: str,
) -> None:
    conn.execute(
        """
        INSERT INTO author_identity_events
            (stable_id, event_type, related_stable_id, author_id, reason, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (stable_id, event_type, related_stable_id, author_id, reason, db.utcnow()),
    )


def _update_ledger(
    conn: sqlite3.Connection,
    stable_id: str,
    profile: dict[str, Any],
    *,
    status: str = "active",
) -> None:
    conn.execute(
        """
        UPDATE author_identity_ledger
        SET orcid=?, openalex_id=?, canonical_name=?, given_name=?, family_name=?,
            name_key=?, match_key=?, first_year=?, last_year=?, institutions=?,
            current_author_id=?, status=?, updated_at=?
        WHERE stable_id=?
        """,
        (
            profile["orcid"] or None,
            profile["openalex_id"],
            profile["canonical_name"],
            profile["given_name"],
            profile["family_name"],
            profile["name_key"],
            profile["match_key"],
            profile["first_year"],
            profile["last_year"],
            profile["institutions"] or None,
            profile["author_id"] if status == "active" else None,
            status,
            db.utcnow(),
            stable_id,
        ),
    )


def _prefer(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda row: (
            0 if row.get("status") == "active" else 1,
            row["first_year"] if row["first_year"] is not None else 9999,
            -len(row["canonical_name"] or ""),
            row["stable_id"],
        ),
    )[0]


def _match_ledger(
    profile: dict[str, Any],
    ledger: list[dict[str, Any]],
    used: set[str],
) -> tuple[dict[str, Any] | None, str]:
    available = [row for row in ledger if row["stable_id"] not in used]
    if profile["orcid"]:
        matches = [row for row in available if normalize_orcid(row["orcid"]) == profile["orcid"]]
        if matches:
            return _prefer(matches), "orcid"
    if profile["openalex_ids"]:
        matches = [
            row
            for row in available
            if row["openalex_id"] and row["openalex_id"] in profile["openalex_ids"]
        ]
        if matches:
            return _prefer(matches), "openalex"
    exact = [
        row
        for row in available
        if normalize_name_part(row["canonical_name"]) == profile["normalized_name"]
        and _year_overlap(
            row["first_year"], row["last_year"], profile["first_year"], profile["last_year"]
        )
    ]
    if exact:
        return _prefer(exact), "name_year"
    by_name = [
        row
        for row in available
        if row["match_key"]
        and row["match_key"] == profile["match_key"]
        and _year_overlap(
            row["first_year"], row["last_year"], profile["first_year"], profile["last_year"]
        )
    ]
    if by_name:
        if profile["institution_tokens"]:
            with_inst = [
                row
                for row in by_name
                if _institution_tokens(row["institutions"]) & profile["institution_tokens"]
            ]
            if with_inst:
                return _prefer(with_inst), "institution_year"
        return _prefer(by_name), "match_key_year"
    return None, "new"


def assign_stable_ids(conn: sqlite3.Connection) -> dict[str, int]:
    """Reconcile the rebuilt author table with the stable-identity ledger.

    Matching precedence is ORCID, OpenAlex ID, exact name plus year overlap,
    match key plus year overlap, and finally institution overlap. Ledger rows
    that no longer have a current author are marked merged or inactive rather
    than deleted.
    """
    ensure_identity_ledger(conn)
    author_rows = conn.execute(
        "SELECT author_id FROM authors WHERE stable_id IS NULL ORDER BY author_id"
    ).fetchall()
    if not author_rows:
        # Refresh ledger profiles for existing IDs.
        for row in conn.execute("SELECT author_id, stable_id FROM authors"):
            if row["stable_id"]:
                _update_ledger(conn, row["stable_id"], _author_profile(conn, int(row["author_id"])))
        conn.commit()
        return {"assigned": 0, "merged": 0, "inactive": 0}

    ledger = _ledger_rows(conn)
    used: set[str] = set()
    assigned = 0
    merged = 0
    inactive = 0
    matches: dict[int, tuple[str, str]] = {}
    for row in author_rows:
        profile = _author_profile(conn, int(row["author_id"]))
        match, method = _match_ledger(profile, ledger, used)
        if match is None:
            stable_id = _new_stable_ids(conn, 1)[0]
            conn.execute(
                """
                INSERT INTO author_identity_ledger
                    (stable_id, orcid, openalex_id, canonical_name, given_name, family_name,
                     name_key, match_key, first_year, last_year, institutions,
                     current_author_id, status, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
                """,
                (
                    stable_id,
                    profile["orcid"] or None,
                    profile["openalex_id"],
                    profile["canonical_name"],
                    profile["given_name"],
                    profile["family_name"],
                    profile["name_key"],
                    profile["match_key"],
                    profile["first_year"],
                    profile["last_year"],
                    profile["institutions"] or None,
                    profile["author_id"],
                    db.utcnow(),
                ),
            )
            conn.execute(
                "UPDATE authors SET stable_id=?, updated_at=? WHERE author_id=?",
                (stable_id, db.utcnow(), profile["author_id"]),
            )
            _record_event(
                conn, stable_id, "created", profile["author_id"], None, "new identity after rebuild"
            )
            assigned += 1
        else:
            stable_id = match["stable_id"]
            conn.execute(
                "UPDATE authors SET stable_id=?, updated_at=? WHERE author_id=?",
                (stable_id, db.utcnow(), profile["author_id"]),
            )
            _update_ledger(conn, stable_id, profile)
            _record_event(
                conn,
                stable_id,
                "reconciled",
                profile["author_id"],
                None,
                f"matched by {method}",
            )
        used.add(stable_id)
        matches[profile["author_id"]] = (stable_id, method)

    # Ledger rows with no current author: find a plausible successor by match
    # key and mark the old identity as merged into it.
    by_match_key: dict[str, list[int]] = defaultdict(list)
    for author_id, (stable_id, _) in matches.items():
        profile = _author_profile(conn, author_id)
        by_match_key[profile["match_key"]].append(author_id)
    for row in ledger:
        if row["stable_id"] in used:
            continue
        successors = by_match_key.get(row["match_key"] or "", [])
        if len(successors) == 1:
            target_author = successors[0]
            target_stable = matches[target_author][0]
            conn.execute(
                """
                UPDATE author_identity_ledger
                SET status='merged', current_author_id=?, updated_at=?
                WHERE stable_id=?
                """,
                (target_author, db.utcnow(), row["stable_id"]),
            )
            _record_event(
                conn,
                row["stable_id"],
                "merged",
                target_author,
                target_stable,
                "name-key successor after rebuild",
            )
            merged += 1
        else:
            conn.execute(
                """
                UPDATE author_identity_ledger
                SET status='inactive', current_author_id=NULL, updated_at=?
                WHERE stable_id=?
                """,
                (db.utcnow(), row["stable_id"]),
            )
            _record_event(
                conn, row["stable_id"], "inactive", None, None, "no successor after rebuild"
            )
            inactive += 1
    conn.commit()
    stats = {"assigned": assigned, "merged": merged, "inactive": inactive}
    log.info("Stable author IDs: %s", stats)
    return stats


def stable_id_for_author(conn: sqlite3.Connection, author_id: int) -> str | None:
    row = conn.execute("SELECT stable_id FROM authors WHERE author_id=?", (author_id,)).fetchone()
    return row["stable_id"] if row else None


def create_stable_identity(
    conn: sqlite3.Connection,
    *,
    canonical_name: str,
    given_name: str | None,
    family_name: str | None,
    orcid: str | None,
    openalex_id: str | None,
    first_year: int | None,
    last_year: int | None,
    institutions: str | None,
    author_id: int | None,
    event_reason: str,
) -> str:
    """Create a new stable identity (used when splitting an author)."""
    stable_id = _new_stable_ids(conn, 1)[0]
    now = db.utcnow()
    conn.execute(
        """
        INSERT INTO author_identity_ledger
            (stable_id, orcid, openalex_id, canonical_name, given_name, family_name,
             name_key, match_key, first_year, last_year, institutions,
             current_author_id, status, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
        """,
        (
            stable_id,
            normalize_orcid(orcid) or None,
            openalex_id,
            canonical_name,
            given_name,
            family_name,
            name_key(given_name, family_name),
            name_match_key(given_name, family_name),
            first_year,
            last_year,
            institutions,
            author_id,
            now,
        ),
    )
    _record_event(conn, stable_id, "created", author_id, None, event_reason)
    return stable_id


def mark_split(
    conn: sqlite3.Connection,
    *,
    original_stable_id: str,
    new_stable_id: str,
    original_author_id: int,
    new_author_id: int,
    reason: str,
) -> None:
    _record_event(
        conn,
        original_stable_id,
        "split",
        original_author_id,
        new_stable_id,
        reason,
    )
    conn.execute(
        "UPDATE author_identity_ledger SET updated_at=? WHERE stable_id IN (?, ?)",
        (db.utcnow(), original_stable_id, new_stable_id),
    )

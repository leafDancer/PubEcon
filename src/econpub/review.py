from __future__ import annotations

import json
import logging
import sqlite3
from collections import defaultdict
from typing import Any, Iterable

from . import db
from .authors import _rebuild_coauthorship
from .identity import create_stable_identity, mark_split, stable_id_for_author
from .normalize import clean_text, name_key, name_match_key, normalize_name_part

log = logging.getLogger(__name__)

# Manual review of authors that currently map to more than one OpenAlex ID.
# The review is deliberately explicit and auditable: `fragment` means the
# OpenAlex profiles are duplicate records for one person; `split` means the
# canonical author is an over-merge; `uncertain` means the evidence is not
# strong enough to split and the author stays flagged.
MULTI_ID_REVIEWS: dict[str, dict[str, str]] = {
    "John Morgan": {
        "decision": "split",
        "keep_openalex_id": "A5113551723",
        "reason": (
            "John W. Morgan (Princeton, 2001) and John M. Morgan (UC Berkeley, 2008-09) "
            "have conflicting middle initials, different institutions, and non-overlapping "
            "papers."
        ),
    },
    "Benjamin R Page": {
        "decision": "split",
        "keep_openalex_id": "A5002652442",
        "reason": (
            "Benjamin I. Page (2000) and Benjamin R Page (2005) have conflicting middle "
            "initials; the OpenAlex profiles are distinct."
        ),
    },
    "Daniel M. Sullivan": {
        "decision": "split",
        "keep_openalex_id": "A5021617351",
        "reason": (
            "Daniel G. Sullivan (Federal Reserve Bank of Chicago, 2009) and Daniel M. "
            "Sullivan (JPMorgan Chase Institute, 2024) have conflicting middle initials, "
            "institutions, and periods."
        ),
    },
    "David S Johnson": {
        "decision": "uncertain",
        "reason": (
            "Census Bureau (2006-2013) and University of Michigan (2026); a move is "
            "plausible but the records lack middle initials or an independent identifier."
        ),
    },
    "Jean Lee": {
        "decision": "uncertain",
        "reason": (
            "World Bank (2013) and NYU (2014) are compatible with a move, but the records "
            "lack a distinguishing middle name or identifier."
        ),
    },
    "Jose Maria Fernandez": {
        "decision": "uncertain",
        "reason": (
            "MIT financial engineering (2013) and University of Louisville (2017) differ "
            "in field and institution; no independent identifier."
        ),
    },
    "Daniel Chen": {
        "decision": "uncertain",
        "reason": (
            "Stanford GSB (2021) and Princeton Economics (2026) are compatible with a move, "
            "but the name is common and the records lack a distinguishing initial."
        ),
    },
    "André Meier": {
        "decision": "uncertain",
        "reason": (
            "IMF (2010) and Tudor Capital (2026) are compatible with a career move, but no "
            "independent identifier confirms it."
        ),
    },
}

FRAGMENT_REASON = (
    "Same canonical name and non-conflicting institution/year evidence; treated as "
    "OpenAlex profile duplication rather than distinct people."
)


def _get_author(conn: sqlite3.Connection, author_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM authors WHERE author_id=?", (author_id,)).fetchone()
    if row is None:
        raise KeyError(f"unknown author_id {author_id}")
    return row


def _author_groups(conn: sqlite3.Connection, author_id: int) -> list[dict[str, Any]]:
    groups = []
    rows = conn.execute(
        """
        SELECT openalex_author_id AS openalex_id,
               COUNT(*) AS paper_count,
               MIN(p.published_year) AS first_year,
               MAX(p.published_year) AS last_year
        FROM authorships a
        JOIN papers p ON p.paper_id = a.paper_id
        WHERE a.author_id=? AND a.openalex_author_id IS NOT NULL
        GROUP BY a.openalex_author_id
        ORDER BY paper_count DESC, first_year
        """,
        (author_id,),
    ).fetchall()
    for row in rows:
        names = [
            clean_text(item["openalex_author_name"])
            for item in conn.execute(
                """
                SELECT DISTINCT openalex_author_name FROM authorships
                WHERE author_id=? AND openalex_author_id=?
                  AND openalex_author_name IS NOT NULL
                """,
                (author_id, row["openalex_id"]),
            )
        ]
        institutions = [
            clean_text(item["openalex_institution_name"])
            for item in conn.execute(
                """
                SELECT DISTINCT openalex_institution_name FROM authorships
                WHERE author_id=? AND openalex_author_id=?
                  AND openalex_institution_name IS NOT NULL
                """,
                (author_id, row["openalex_id"]),
            )
        ]
        authorship_ids = [
            int(item["authorship_id"])
            for item in conn.execute(
                """
                SELECT authorship_id FROM authorships
                WHERE author_id=? AND openalex_author_id=?
                """,
                (author_id, row["openalex_id"]),
            )
        ]
        groups.append(
            {
                "openalex_id": row["openalex_id"],
                "paper_count": int(row["paper_count"]),
                "first_year": row["first_year"],
                "last_year": row["last_year"],
                "names": [name for name in names if name],
                "institutions": [item for item in institutions if item],
                "authorship_ids": authorship_ids,
            }
        )
    return groups


def _best_name(
    group: dict[str, Any], fallback: str, *, include_fallback: bool = False
) -> str:
    names = list(group["names"])
    if include_fallback and fallback:
        names.append(fallback)
    if not names:
        names = [fallback]
    return max(names, key=lambda value: (len(value), value))


def _split_name(full_name: str, fallback_family: str) -> tuple[str, str]:
    full_name = clean_text(full_name)
    fallback_family = clean_text(fallback_family)
    if fallback_family and full_name.lower().endswith(fallback_family.lower()):
        given = full_name[: -len(fallback_family)].strip(" ,")
        return given, fallback_family
    tokens = full_name.split()
    if len(tokens) >= 2:
        return " ".join(tokens[:-1]), tokens[-1]
    return "", full_name


def _rebuild_aliases(conn: sqlite3.Connection, author_ids: Iterable[int]) -> None:
    author_ids = list(author_ids)
    if not author_ids:
        return
    placeholders = ",".join("?" for _ in author_ids)
    conn.execute(f"DELETE FROM author_aliases WHERE author_id IN ({placeholders})", author_ids)
    now = db.utcnow()
    for author_id in author_ids:
        rows = conn.execute(
            """
            SELECT a.given_name, a.family_name, a.full_name, a.orcid, a.suffix, a.match_key,
                   p.published_year, p.paper_id
            FROM authorships a
            JOIN papers p ON p.paper_id = a.paper_id
            WHERE a.author_id=?
            """,
            (author_id,),
        ).fetchall()
        grouped: dict[tuple[Any, ...], list[sqlite3.Row]] = defaultdict(list)
        for row in rows:
            grouped[
                (
                    row["given_name"],
                    row["family_name"],
                    row["full_name"],
                    row["orcid"],
                    row["suffix"],
                    row["match_key"],
                )
            ].append(row)
        for key, values in grouped.items():
            years = [value["published_year"] for value in values if value["published_year"]]
            conn.execute(
                """
                INSERT INTO author_aliases
                    (author_id, given_name, family_name, full_name, orcid, suffix,
                     name_key, match_key, first_year, last_year, paper_count, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    author_id,
                    key[0],
                    key[1],
                    key[2],
                    key[3],
                    key[4],
                    name_key(key[0], key[1]),
                    key[5],
                    min(years) if years else None,
                    max(years) if years else None,
                    len({value["paper_id"] for value in values}),
                    now,
                ),
            )


def _insert_separation_rule(
    conn: sqlite3.Connection,
    *,
    left_openalex_id: str | None,
    right_openalex_id: str | None,
    left_authorship_id: int | None,
    right_authorship_id: int | None,
    reason: str,
) -> None:
    existing = conn.execute(
        """
        SELECT 1 FROM author_separation_rules
        WHERE COALESCE(left_openalex_id,'')=COALESCE(?,'')
          AND COALESCE(right_openalex_id,'')=COALESCE(?,'')
          AND COALESCE(left_authorship_id,0)=COALESCE(?,0)
          AND COALESCE(right_authorship_id,0)=COALESCE(?,0)
        """,
        (left_openalex_id, right_openalex_id, left_authorship_id, right_authorship_id),
    ).fetchone()
    if existing:
        return
    conn.execute(
        """
        INSERT INTO author_separation_rules
            (left_openalex_id, right_openalex_id, left_authorship_id, right_authorship_id,
             reason, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            left_openalex_id,
            right_openalex_id,
            left_authorship_id,
            right_authorship_id,
            reason,
            db.utcnow(),
        ),
    )


def _refresh_author_openalex_fields(conn: sqlite3.Connection, author_ids: Iterable[int]) -> None:
    for author_id in author_ids:
        rows = conn.execute(
            """
            SELECT a.openalex_author_id, COUNT(*) AS n,
                   MIN(p.published_year) AS first_year,
                   MAX(p.published_year) AS last_year
            FROM authorships a JOIN papers p ON p.paper_id=a.paper_id
            WHERE a.author_id=? AND a.openalex_author_id IS NOT NULL
            GROUP BY a.openalex_author_id
            ORDER BY n DESC, last_year DESC
            """,
            (author_id,),
        ).fetchall()
        if not rows:
            continue
        primary = rows[0]
        cited = conn.execute(
            """
            SELECT COALESCE(SUM(p.openalex_cited_by_count),0)
            FROM authorships a JOIN papers p ON p.paper_id=a.paper_id
            WHERE a.author_id=? AND a.openalex_author_id=?
            """,
            (author_id, primary["openalex_author_id"]),
        ).fetchone()[0]
        last_institution = conn.execute(
            """
            SELECT a.openalex_institution_id, a.openalex_institution_name
            FROM authorships a JOIN papers p ON p.paper_id=a.paper_id
            WHERE a.author_id=? AND a.openalex_author_id=?
              AND a.openalex_institution_id IS NOT NULL
            ORDER BY p.published_year DESC
            LIMIT 1
            """,
            (author_id, primary["openalex_author_id"]),
        ).fetchone()
        conn.execute(
            """
            UPDATE authors
            SET openalex_id=?, openalex_match_confidence=?,
                openalex_works_count=?, openalex_cited_by_count=?,
                openalex_last_institution_id=?, openalex_last_institution_name=?
            WHERE author_id=?
            """,
            (
                primary["openalex_author_id"],
                "high" if len(rows) == 1 else "low",
                sum(int(row["n"]) for row in rows),
                cited,
                last_institution["openalex_institution_id"] if last_institution else None,
                last_institution["openalex_institution_name"] if last_institution else None,
                author_id,
            ),
        )


def split_author_by_openalex(
    conn: sqlite3.Connection,
    author_id: int,
    groups: list[dict[str, Any]],
    *,
    keep_openalex_id: str | None,
    reason: str,
) -> dict[str, Any]:
    """Split one canonical author into its OpenAlex-ID groups.

    The kept group retains the original author row and stable ID. Every other
    group becomes a new author with a new stable ID. Authorships without an
    OpenAlex ID stay with the kept group.
    """
    if len(groups) < 2:
        raise ValueError("a split needs at least two OpenAlex groups")
    original = _get_author(conn, author_id)
    keep_group = None
    if keep_openalex_id:
        keep_group = next(
            (group for group in groups if group["openalex_id"] == keep_openalex_id), None
        )
    if keep_group is None:
        keep_group = sorted(
            groups,
            key=lambda group: (
                -group["paper_count"],
                group["first_year"] if group["first_year"] is not None else 9999,
                -len(_best_name(group, original["canonical_name"])),
            ),
        )[0]
    # Authorships with no OpenAlex ID stay with the kept author. Include them
    # in the keep group's authorship list so separation rules cover the full
    # cross-group boundary, not just the linked authorships.
    keep_group = dict(keep_group)
    unlinked_ids = [
        int(row["authorship_id"])
        for row in conn.execute(
            """
            SELECT authorship_id FROM authorships
            WHERE author_id=? AND openalex_author_id IS NULL
            """,
            (author_id,),
        )
    ]
    keep_group["authorship_ids"] = list(keep_group["authorship_ids"]) + unlinked_ids
    now = db.utcnow()

    kept_name = _best_name(
        keep_group, original["canonical_name"], include_fallback=True
    )
    kept_given, kept_family = _split_name(kept_name, original["family_name"] or "")
    conn.execute(
        """
        UPDATE authors
        SET canonical_name=?, given_name=?, family_name=?, name_key=?, match_key=?,
            openalex_id=?, openalex_match_confidence='high',
            resolution_method='openalex_split', resolution_confidence='high',
            needs_review=0, review_status='split_applied', updated_at=?
        WHERE author_id=?
        """,
        (
            kept_name,
            kept_given or None,
            kept_family or None,
            name_key(kept_given, kept_family),
            name_match_key(kept_given, kept_family),
            keep_group["openalex_id"],
            now,
            author_id,
        ),
    )
    if original["stable_id"]:
        conn.execute(
            """
            UPDATE author_identity_ledger
            SET canonical_name=?, given_name=?, family_name=?, name_key=?, match_key=?,
                openalex_id=?, current_author_id=?, status='active', updated_at=?
            WHERE stable_id=?
            """,
            (
                kept_name,
                kept_given or None,
                kept_family or None,
                name_key(kept_given, kept_family),
                name_match_key(kept_given, kept_family),
                keep_group["openalex_id"],
                author_id,
                now,
                original["stable_id"],
            ),
        )

    new_authors: list[dict[str, Any]] = []
    for group in groups:
        if group["openalex_id"] == keep_group["openalex_id"]:
            continue
        group_name = _best_name(group, original["canonical_name"])
        given, family = _split_name(group_name, original["family_name"] or "")
        cursor = conn.execute(
            """
            INSERT INTO authors
                (stable_id, canonical_name, given_name, family_name, orcid, openalex_id,
                 openalex_match_confidence, name_key, match_key, suffix, merged_variants,
                 resolution_method, resolution_confidence, needs_review, review_status,
                 created_at, updated_at)
            VALUES (NULL, ?, ?, ?, NULL, ?, 'high', ?, ?, ?, 1,
                    'openalex_split', 'high', 0, 'split_applied', ?, ?)
            """,
            (
                group_name,
                given or None,
                family or None,
                group["openalex_id"],
                name_key(given, family),
                name_match_key(given, family),
                original["suffix"],
                now,
                now,
            ),
        )
        new_author_id = int(cursor.lastrowid)
        stable_id = create_stable_identity(
            conn,
            canonical_name=group_name,
            given_name=given or None,
            family_name=family or None,
            orcid=None,
            openalex_id=group["openalex_id"],
            first_year=group["first_year"],
            last_year=group["last_year"],
            institutions="; ".join(group["institutions"]) or None,
            author_id=new_author_id,
            event_reason=reason,
        )
        conn.execute(
            "UPDATE authors SET stable_id=? WHERE author_id=?", (stable_id, new_author_id)
        )
        placeholders = ",".join("?" for _ in group["authorship_ids"])
        conn.execute(
            f"UPDATE authorships SET author_id=? WHERE authorship_id IN ({placeholders})",
            (new_author_id, *group["authorship_ids"]),
        )
        conn.execute(
            """
            UPDATE career_assignments SET author_id=?
            WHERE authorship_id IN (SELECT authorship_id FROM authorships WHERE author_id=?)
            """,
            (new_author_id, new_author_id),
        )
        conn.execute(
            """
            UPDATE author_openalex_evidence SET author_id=?
            WHERE author_id=? AND openalex_id=?
            """,
            (new_author_id, author_id, group["openalex_id"]),
        )
        conn.execute(
            """
            INSERT INTO author_split_candidates
                (author_id, openalex_id, proposed_name, paper_count, first_year, last_year,
                 institutions, evidence, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'applied', ?)
            ON CONFLICT(author_id, openalex_id) DO UPDATE SET
                proposed_name=excluded.proposed_name,
                paper_count=excluded.paper_count,
                first_year=excluded.first_year,
                last_year=excluded.last_year,
                institutions=excluded.institutions,
                evidence=excluded.evidence,
                status='applied'
            """,
            (
                new_author_id,
                group["openalex_id"],
                group_name,
                group["paper_count"],
                group["first_year"],
                group["last_year"],
                "; ".join(group["institutions"]) or None,
                json.dumps({"reason": reason, "kept": False}, ensure_ascii=False),
                now,
            ),
        )
        new_authors.append({"author_id": new_author_id, "openalex_id": group["openalex_id"]})
        mark_split(
            conn,
            original_stable_id=original["stable_id"],
            new_stable_id=stable_id,
            original_author_id=author_id,
            new_author_id=new_author_id,
            reason=reason,
        )

    # Mark the kept group's review row and record separation rules for every
    # cross-group pair of authorships and for the two OpenAlex IDs.
    conn.execute(
        """
        INSERT INTO author_split_candidates
            (author_id, openalex_id, proposed_name, paper_count, first_year, last_year,
             institutions, evidence, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'applied', ?)
        ON CONFLICT(author_id, openalex_id) DO UPDATE SET
            proposed_name=excluded.proposed_name,
            paper_count=excluded.paper_count,
            first_year=excluded.first_year,
            last_year=excluded.last_year,
            institutions=excluded.institutions,
            evidence=excluded.evidence,
            status='applied'
        """,
        (
            author_id,
            keep_group["openalex_id"],
            kept_name,
            keep_group["paper_count"],
            keep_group["first_year"],
            keep_group["last_year"],
            "; ".join(keep_group["institutions"]) or None,
            json.dumps({"reason": reason, "kept": True}, ensure_ascii=False),
            now,
        ),
    )
    groups_for_rules = [keep_group] + [
        group for group in groups if group["openalex_id"] != keep_group["openalex_id"]
    ]
    for left in groups_for_rules:
        for right in groups_for_rules:
            if left["openalex_id"] >= right["openalex_id"]:
                continue
            _insert_separation_rule(
                conn,
                left_openalex_id=left["openalex_id"],
                right_openalex_id=right["openalex_id"],
                left_authorship_id=None,
                right_authorship_id=None,
                reason=reason,
            )
            for left_authorship in left["authorship_ids"]:
                for right_authorship in right["authorship_ids"]:
                    _insert_separation_rule(
                        conn,
                        left_openalex_id=left["openalex_id"],
                        right_openalex_id=right["openalex_id"],
                        left_authorship_id=left_authorship,
                        right_authorship_id=right_authorship,
                        reason=reason,
                    )

    affected = [author_id] + [item["author_id"] for item in new_authors]
    _rebuild_aliases(conn, affected)
    _refresh_author_openalex_fields(conn, affected)
    conn.commit()
    return {
        "author_id": author_id,
        "kept_openalex_id": keep_group["openalex_id"],
        "new_authors": new_authors,
        "affected_author_ids": affected,
    }


def resolve_merge_candidates(conn: sqlite3.Connection) -> dict[str, int]:
    """Resolve the seven name-based candidates using documented evidence."""
    rows = conn.execute(
        """
        SELECT c.candidate_id, c.author_id_a, c.author_id_b, c.evidence,
               a.canonical_name AS name_a, b.canonical_name AS name_b
        FROM author_merge_candidates c
        JOIN authors a ON a.author_id=c.author_id_a
        JOIN authors b ON b.author_id=c.author_id_b
        WHERE c.status='pending'
        """
    ).fetchall()
    resolved = 0
    for row in rows:
        try:
            evidence = json.loads(row["evidence"] or "{}")
        except (TypeError, ValueError):
            evidence = {}
        if evidence.get("verdict") == "same":
            # Shared-OpenAlex-ID pairs are handled by
            # merge_openalex_supported_authors, not marked as splits.
            continue
        if row["name_a"] == "Robert J. Gordon" or row["name_b"] == "Robert J. Gordon":
            note = (
                "Robert J. Gordon (Northwestern) and Robert N. Gordon (NYU Stern / "
                "Twenty-First Securities) have conflicting middle initials and institutions."
            )
        elif evidence.get("verdict") == "different":
            note = (
                "OpenAlex author IDs differ: "
                f"{evidence.get('left_openalex_id')} vs {evidence.get('right_openalex_id')}."
            )
        else:
            note = "Institution, middle-initial, and publication-period evidence support a split."
        conn.execute(
            """
            UPDATE author_merge_candidates
            SET status='resolved_split', reviewed_at=?, review_notes=?
            WHERE candidate_id=?
            """,
            (db.utcnow(), note, row["candidate_id"]),
        )
        for author_id in (row["author_id_a"], row["author_id_b"]):
            conn.execute(
                """
                UPDATE authors
                SET needs_review=0, review_status='namesake_resolved', updated_at=?
                WHERE author_id=?
                """,
                (db.utcnow(), author_id),
            )
        resolved += 1
    conn.commit()
    stats = {"pending_seen": len(rows), "resolved_split": resolved}
    log.info("Merge candidates: %s", stats)
    return stats


def resolve_multi_id_authors(conn: sqlite3.Connection) -> dict[str, int]:
    """Classify and, where confirmed, split multi-OpenAlex-ID authors."""
    authors = conn.execute(
        """
        SELECT author_id, canonical_name FROM authors
        WHERE author_id IN (
            SELECT author_id FROM author_openalex_evidence
            GROUP BY author_id HAVING COUNT(DISTINCT openalex_id) > 1
        )
        ORDER BY canonical_name
        """
    ).fetchall()
    stats = {
        "multi_id_authors": len(authors),
        "split_authors": 0,
        "fragmentation_authors": 0,
        "uncertain_authors": 0,
        "new_authors": 0,
    }
    split_author_ids: list[int] = []
    for author in authors:
        author_id = int(author["author_id"])
        groups = _author_groups(conn, author_id)
        if len(groups) < 2:
            continue
        review = MULTI_ID_REVIEWS.get(author["canonical_name"])
        if review is None:
            decision = "fragment"
            reason = FRAGMENT_REASON
            keep_openalex_id = None
        else:
            decision = review["decision"]
            reason = review["reason"]
            keep_openalex_id = review.get("keep_openalex_id")
        if decision == "split":
            result = split_author_by_openalex(
                conn,
                author_id,
                groups,
                keep_openalex_id=keep_openalex_id,
                reason=reason,
            )
            stats["split_authors"] += 1
            stats["new_authors"] += len(result["new_authors"])
            split_author_ids.extend(result["affected_author_ids"])
            continue
        status = "rejected" if decision == "fragment" else "proposed"
        for group in groups:
            conn.execute(
                """
                INSERT INTO author_split_candidates
                    (author_id, openalex_id, proposed_name, paper_count, first_year,
                     last_year, institutions, evidence, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(author_id, openalex_id) DO UPDATE SET
                    proposed_name=excluded.proposed_name,
                    paper_count=excluded.paper_count,
                    first_year=excluded.first_year,
                    last_year=excluded.last_year,
                    institutions=excluded.institutions,
                    evidence=excluded.evidence,
                    status=excluded.status
                """,
                (
                    author_id,
                    group["openalex_id"],
                    _best_name(group, author["canonical_name"]),
                    group["paper_count"],
                    group["first_year"],
                    group["last_year"],
                    "; ".join(group["institutions"]) or None,
                    json.dumps(
                        {"decision": decision, "reason": reason}, ensure_ascii=False
                    ),
                    status,
                    db.utcnow(),
                ),
            )
        if decision == "fragment":
            stats["fragmentation_authors"] += 1
            conn.execute(
                """
                UPDATE authors
                SET needs_review=0, review_status='openalex_fragmentation', updated_at=?
                WHERE author_id=?
                """,
                (db.utcnow(), author_id),
            )
        else:
            stats["uncertain_authors"] += 1
            conn.execute(
                """
                UPDATE authors
                SET needs_review=1, review_status='manual_review', updated_at=?
                WHERE author_id=?
                """,
                (db.utcnow(), author_id),
            )
    if split_author_ids:
        _rebuild_coauthorship(conn)
    conn.commit()
    log.info("Multi-ID author review: %s", stats)
    return stats

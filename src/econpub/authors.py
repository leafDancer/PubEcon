from __future__ import annotations

import logging
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

from .identity import assign_stable_ids, ensure_identity_ledger
from .normalize import (
    clean_text,
    family_root,
    given_root,
    middle_initials,
    name_key,
    name_match_key,
    normalize_name_part,
    normalize_orcid,
)

log = logging.getLogger(__name__)

# Confirmed distinct namesakes from the M1 audit. These pairs are never
# auto-merged; they stay separate and are written to the review queue.
KNOWN_NAMESAKE_PAIRS = {
    frozenset({"robert l clark", "robert clark"}),
    frozenset({"margaret m mcconnell", "margaret mcconnell"}),
    frozenset({"jing cynthia wu", "jing wu"}),
    frozenset({"robert j gordon", "robert gordon"}),
    frozenset({"michael walker", "michael s walker"}),
}

INSTITUTION_STOPWORDS = {
    "university",
    "univ",
    "college",
    "school",
    "institute",
    "institution",
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
    "program",
    "programme",
    "faculty",
    "division",
    "graduate",
    "business",
    "management",
    "public",
    "policy",
    "studies",
    "science",
    "sciences",
    "national",
    "american",
    "federal",
    "reserve",
    "bank",
    "board",
    "bureau",
    "office",
    "street",
    "avenue",
    "road",
    "room",
    "hall",
    "building",
    "box",
    "professor",
    "assistant",
    "associate",
    "senior",
    "lecturer",
    "reader",
    "instructor",
    "student",
    "phd",
    "postdoc",
    "fellow",
}

INSTITUTION_ALIASES = {
    "mit": {"massachusetts", "technology"},
    "ucla": {"california", "los", "angeles"},
    "ucb": {"california", "berkeley"},
    "nyu": {"new", "york"},
    "lse": {"london", "economics"},
    "lmu": {"ludwig", "maximilians", "munchen"},
    "sdu": {"southern", "denmark"},
    "kth": {"royal", "technology"},
    "caltech": {"california", "technology"},
    "cmu": {"carnegie", "mellon"},
    "usc": {"southern", "california"},
    "ucsd": {"california", "san", "diego"},
    "upenn": {"pennsylvania"},
    "ucl": {"college", "london"},
    "epfl": {"lausanne"},
}


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _institution_tokens(hint: str | None, raw: str | None) -> set[str]:
    text = clean_text(hint) or clean_text(raw)
    if not text:
        return set()
    tokens = set(normalize_name_part(text).split())
    expanded: set[str] = set()
    for token in tokens:
        expanded.update(INSTITUTION_ALIASES.get(token, {token}))
    meaningful = {token for token in expanded if token not in INSTITUTION_STOPWORDS and len(token) >= 2}
    return meaningful or expanded


def _profile(row: sqlite3.Row) -> dict[str, Any]:
    given = clean_text(row["given_name"])
    family = clean_text(row["family_name"])
    full = clean_text(row["full_name"]) or f"{given} {family}".strip()
    match_key = name_match_key(given, family)
    return {
        "authorship_id": int(row["authorship_id"]),
        "paper_id": int(row["paper_id"]),
        "author_order": int(row["author_order"]),
        "given": given,
        "family": family,
        "full": full,
        "normalized_full": normalize_name_part(full),
        "middle_initials": middle_initials(given),
        "affiliation": clean_text(row["affiliation_raw"]),
        "hint": clean_text(row["institution_hint"]),
        "institution_tokens": _institution_tokens(row["institution_hint"], row["affiliation_raw"]),
        "orcid": normalize_orcid(row["orcid"]),
        "suffix": clean_text(row["suffix"]),
        "match_key": match_key,
        "openalex_author_id": clean_text(row["openalex_author_id"]) or None,
        "openalex_name": clean_text(row["openalex_author_name"]) or None,
        "year": row["published_year"],
    }


def _suffix_key(value: str | None) -> str:
    return "".join(char for char in (value or "").lower() if char.isalnum())


def _is_known_namesake(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return frozenset({left["normalized_full"], right["normalized_full"]}) in KNOWN_NAMESAKE_PAIRS


def _compatible(
    left: dict[str, Any],
    right: dict[str, Any],
    separation_rules: tuple[set[frozenset[str]], set[frozenset[int]]] | None = None,
) -> bool:
    if left["paper_id"] == right["paper_id"]:
        return False
    if separation_rules:
        oa_pairs, authorship_pairs = separation_rules
        left_oa = left.get("openalex_author_id")
        right_oa = right.get("openalex_author_id")
        if left_oa and right_oa and frozenset({left_oa, right_oa}) in oa_pairs:
            return False
        if frozenset({left["authorship_id"], right["authorship_id"]}) in authorship_pairs:
            return False
    if left["suffix"] and right["suffix"] and _suffix_key(left["suffix"]) != _suffix_key(right["suffix"]):
        return False
    if left["orcid"] and right["orcid"] and left["orcid"] != right["orcid"]:
        return False
    if left["middle_initials"] and right["middle_initials"]:
        if not (left["middle_initials"] & right["middle_initials"]):
            return False
    if _is_known_namesake(left, right):
        return False
    return True


def _needs_review(profiles: list[dict[str, Any]]) -> bool:
    if len(profiles) < 2:
        return False
    names = {profile["full"] for profile in profiles if profile["full"]}
    if len(names) > 1 and not any(profile["institution_tokens"] for profile in profiles):
        return True
    for left_index in range(len(profiles)):
        for right_index in range(left_index + 1, len(profiles)):
            left = profiles[left_index]
            right = profiles[right_index]
            if not left["institution_tokens"] or not right["institution_tokens"]:
                continue
            if left["year"] is not None and left["year"] == right["year"]:
                if not (left["institution_tokens"] & right["institution_tokens"]):
                    return True
    return False


def _split_reason(left: dict[str, Any], right: dict[str, Any]) -> str:
    if left["paper_id"] == right["paper_id"]:
        return "same paper, same name (distinct coauthors)"
    if left["suffix"] and right["suffix"] and _suffix_key(left["suffix"]) != _suffix_key(right["suffix"]):
        return f"conflicting suffix: {left['suffix']} vs {right['suffix']}"
    if left["orcid"] and right["orcid"] and left["orcid"] != right["orcid"]:
        return "conflicting ORCID"
    if left["middle_initials"] and right["middle_initials"]:
        if not (left["middle_initials"] & right["middle_initials"]):
            return (
                "conflicting middle initials: "
                f"{''.join(sorted(left['middle_initials']))} vs "
                f"{''.join(sorted(right['middle_initials']))}"
            )
    if _is_known_namesake(left, right):
        return "known namesake pair"
    return "conflicting evidence"


def _components(
    profiles: list[dict[str, Any]],
    separation_rules: tuple[set[frozenset[str]], set[frozenset[int]]] | None = None,
) -> list[list[dict[str, Any]]]:
    if not profiles:
        return []
    parent = list(range(len(profiles)))

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

    for left in range(len(profiles)):
        for right in range(left + 1, len(profiles)):
            if _compatible(profiles[left], profiles[right], separation_rules):
                union(left, right)

    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for index, profile in enumerate(profiles):
        grouped[find(index)].append(profile)
    return list(grouped.values())


def _split_conflicting_components(
    components: list[list[dict[str, Any]]],
    separation_rules: tuple[set[frozenset[str]], set[frozenset[int]]] | None,
) -> list[list[dict[str, Any]]]:
    """Split components that are bridged across a known namesake rule.

    Pairwise separation rules are not enough: a byline with no OpenAlex ID can
    connect the two sides transitively (John W. Morgan 2001 -> an unlinked
    2009 byline -> John M. Morgan). Anchor the sides on the rule's OpenAlex
    IDs, then assign unlinked bylines by institution overlap, name
    compatibility, and year proximity. Ambiguous bylines stay in a separate
    review component instead of being forced onto one side.
    """
    if not separation_rules:
        return components
    oa_pairs, _authorship_pairs = separation_rules
    if not oa_pairs:
        return components
    result: list[list[dict[str, Any]]] = []
    for component in components:
        oa_ids = {
            profile["openalex_author_id"]
            for profile in component
            if profile.get("openalex_author_id")
        }
        conflicts = [pair for pair in oa_pairs if pair <= oa_ids]
        if not conflicts:
            result.append(component)
            continue
        side_ids = sorted(set().union(*conflicts))
        sides: dict[str, list[dict[str, Any]]] = {oa: [] for oa in side_ids}
        unassigned: list[dict[str, Any]] = []
        for profile in component:
            oa = profile.get("openalex_author_id")
            if oa in sides:
                sides[oa].append(profile)
            else:
                unassigned.append(profile)
        remaining: list[dict[str, Any]] = []
        for profile in unassigned:
            scores: dict[str, tuple[int, int, int]] = {}
            for oa, anchors in sides.items():
                if not anchors:
                    continue
                compatible = sum(
                    1 for anchor in anchors if _compatible(profile, anchor, None)
                )
                institution = sum(
                    1
                    for anchor in anchors
                    if profile["institution_tokens"] & anchor["institution_tokens"]
                )
                years = [
                    abs(int(profile["year"]) - int(anchor["year"]))
                    for anchor in anchors
                    if profile["year"] is not None and anchor["year"] is not None
                ]
                proximity = min(years) if years else 9999
                scores[oa] = (institution, compatible, -proximity)
            if not scores:
                remaining.append(profile)
                continue
            best = max(scores.values())
            winners = [oa for oa, score in scores.items() if score == best]
            if len(winners) == 1:
                sides[winners[0]].append(profile)
            else:
                remaining.append(profile)
        result.extend(anchors for anchors in sides.values() if anchors)
        if remaining:
            result.append(remaining)
    return result


def _name_tokens(value: str) -> set[str]:
    return set(normalize_name_part(value).split())


def _choose_name(profiles: list[dict[str, Any]]) -> tuple[str, str, str]:
    counts: Counter[str] = Counter()
    for profile in profiles:
        full = profile["full"]
        openalex_name = profile.get("openalex_name")
        # Prefer an OpenAlex name only when it is a strict token superset of
        # the Crossref byline (usually a fuller middle name). This preserves
        # Crossref names otherwise and prevents a rebuild from dropping the
        # middle initials that distinguish a confirmed split.
        if full and openalex_name and _name_tokens(full) < _name_tokens(openalex_name):
            counts[openalex_name] += 1
        elif full:
            counts[full] += 1
        elif openalex_name:
            counts[openalex_name] += 1
    if not counts:
        return "(unknown)", "", ""
    canonical = max(counts, key=lambda name: (counts[name], len(name), name))
    for profile in profiles:
        if profile["full"] == canonical and (profile["given"] or profile["family"]):
            return canonical, profile["given"], profile["family"]
        if profile.get("openalex_name") == canonical:
            family = profile["family"] or ""
            if family and canonical.lower().endswith(family.lower()):
                given = canonical[: -len(family)].strip(" ,")
                return canonical, given, family
            tokens = canonical.split()
            if len(tokens) >= 2:
                return canonical, " ".join(tokens[:-1]), tokens[-1]
            return canonical, "", canonical
    first = profiles[0]
    return canonical, first["given"], first["family"]


def _merge_primary(profiles: list[dict[str, Any]]) -> dict[str, Any]:
    return max(
        profiles,
        key=lambda profile: (
            sum(1 for other in profiles if other["paper_id"] == profile["paper_id"]),
            -profile["author_order"],
        ),
    )


def resolve_all_authors(conn: sqlite3.Connection) -> dict[str, int]:
    """Rebuild canonical authors from canonical research articles only.

    The pipeline must call this after content classification and deduplication
    so duplicate and non-research records cannot create ghost authors.
    """
    if conn.execute("SELECT COUNT(*) FROM career_events").fetchone()[0]:
        raise RuntimeError(
            "career_events is not empty; author-keyed CV events need an explicit migration "
            "before the author table can be rebuilt"
        )

    # Preserve the current identity ledger before deleting author rows. Career
    # assignments are keyed by authorship, so they can be re-attached after the
    # rebuild; career_events are author-keyed and are intentionally blocked.
    ensure_identity_ledger(conn)
    saved_assignments = [
        dict(row)
        for row in conn.execute(
            """
            SELECT authorship_id, author_id, paper_id, stage, evidence_type, confidence,
                   source_url, notes, created_at
            FROM career_assignments
            """
        ).fetchall()
    ]
    if saved_assignments:
        conn.execute("DELETE FROM career_assignments")

    conn.execute("DELETE FROM author_aliases")
    conn.execute("DELETE FROM author_merge_candidates")
    conn.execute("DELETE FROM coauthorship_edges")
    conn.execute("UPDATE authorships SET author_id=NULL")
    conn.execute("DELETE FROM authors")

    rows = conn.execute(
        """
        SELECT a.authorship_id, a.paper_id, a.author_order, a.given_name, a.family_name,
               a.full_name, a.affiliation_raw, a.institution_hint, a.orcid, a.suffix,
               a.openalex_author_id, a.openalex_author_name, p.published_year
        FROM authorships a
        JOIN papers p ON p.paper_id = a.paper_id
        WHERE p.content_type='article' AND p.is_duplicate=0
        ORDER BY a.paper_id, a.author_order
        """
    ).fetchall()
    profiles = [_profile(row) for row in rows]

    rule_rows = conn.execute(
        """
        SELECT left_openalex_id, right_openalex_id, left_authorship_id, right_authorship_id
        FROM author_separation_rules
        """
    ).fetchall()
    oa_pairs = {
        frozenset({row["left_openalex_id"], row["right_openalex_id"]})
        for row in rule_rows
        if row["left_openalex_id"] and row["right_openalex_id"]
    }
    authorship_pairs = {
        frozenset({row["left_authorship_id"], row["right_authorship_id"]})
        for row in rule_rows
        if row["left_authorship_id"] and row["right_authorship_id"]
    }
    separation_rules = (oa_pairs, authorship_pairs)

    # ORCID is authoritative; otherwise group by the normalised name key.
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for profile in profiles:
        key = f"orcid:{profile['orcid']}" if profile["orcid"] else profile["match_key"]
        if not key:
            key = f"single:{profile['authorship_id']}"
        grouped[key].append(profile)

    now = _utcnow()
    author_count = 0
    alias_count = 0
    candidate_count = 0
    review_count = 0

    for key, group_profiles in grouped.items():
        components = _components(group_profiles, separation_rules)
        components = _split_conflicting_components(components, separation_rules)
        components.sort(key=lambda component: (-len(component), component[0]["authorship_id"]))
        component_author_ids: list[tuple[int, dict[str, Any], list[dict[str, Any]]]] = []

        for component in components:
            canonical_name, given, family = _choose_name(component)
            orcids = sorted({profile["orcid"] for profile in component if profile["orcid"]})
            suffixes = Counter(profile["suffix"] for profile in component if profile["suffix"])
            suffix = max(suffixes, key=lambda value: (suffixes[value], len(value))) if suffixes else ""
            match_keys = Counter(profile["match_key"] for profile in component if profile["match_key"])
            match_key = max(match_keys, key=lambda value: (match_keys[value], value)) if match_keys else ""
            variants = len({profile["full"] for profile in component if profile["full"]})
            review = _needs_review(component) or len(components) > 1
            confidence = "high" if orcids else ("low" if review else "medium")
            method = "orcid" if orcids else ("name_variant" if variants > 1 else "name_key")
            orcid_value = orcids[0] if len(orcids) == 1 else None
            if orcid_value:
                # A separation rule can split one ORCID group into components
                # (known namesakes). Only the first component keeps the ORCID;
                # the others stay reviewable rather than violating the unique
                # constraint or silently merging distinct people.
                duplicate = conn.execute(
                    "SELECT 1 FROM authors WHERE orcid=?", (orcid_value,)
                ).fetchone()
                if duplicate:
                    orcid_value = None
                    review = True
                    confidence = "low"
            if review:
                review_count += 1

            cursor = conn.execute(
                """
                INSERT INTO authors (
                    canonical_name, given_name, family_name, orcid, name_key, match_key,
                    suffix, merged_variants, resolution_method, resolution_confidence,
                    needs_review, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    canonical_name,
                    given or None,
                    family or None,
                    orcid_value,
                    name_key(given, family),
                    match_key,
                    suffix or None,
                    max(variants, 1),
                    method,
                    confidence,
                    1 if review else 0,
                    now,
                    now,
                ),
            )
            author_id = int(cursor.lastrowid)
            author_count += 1
            conn.executemany(
                "UPDATE authorships SET author_id=? WHERE authorship_id=?",
                [(author_id, profile["authorship_id"]) for profile in component],
            )
            component_author_ids.append((author_id, _merge_primary(component), component))

            aliases: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
            for profile in component:
                alias_key = (
                    profile["given"],
                    profile["family"],
                    profile["full"],
                    profile["orcid"],
                    profile["suffix"],
                    profile["match_key"],
                )
                aliases[alias_key].append(profile)
            for alias_key, alias_profiles in aliases.items():
                years = [profile["year"] for profile in alias_profiles if profile["year"] is not None]
                conn.execute(
                    """
                    INSERT INTO author_aliases (
                        author_id, given_name, family_name, full_name, orcid, suffix,
                        name_key, match_key, first_year, last_year, paper_count, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        author_id,
                        alias_key[0] or None,
                        alias_key[1] or None,
                        alias_key[2] or None,
                        alias_key[3] or None,
                        alias_key[4] or None,
                        name_key(alias_key[0], alias_key[1]),
                        alias_key[5] or None,
                        min(years) if years else None,
                        max(years) if years else None,
                        len({profile["paper_id"] for profile in alias_profiles}),
                        now,
                    ),
                )
                alias_count += 1

        # If a name key produced more than one component, the split was forced
        # by conflicting evidence. Queue the pairs for review instead of
        # silently merging or silently dropping them.
        if len(component_author_ids) > 1:
            primary_id, primary_profile, primary_component = component_author_ids[0]
            for other_id, other_profile, other_component in component_author_ids[1:]:
                reason = _split_reason(primary_profile, other_profile)
                conn.execute(
                    """
                    INSERT INTO author_merge_candidates (
                        author_id_a, author_id_b, reason, institution_a, institution_b,
                        year_a, year_b, status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                    """,
                    (
                        primary_id,
                        other_id,
                        reason,
                        primary_profile["hint"] or primary_profile["affiliation"] or None,
                        other_profile["hint"] or other_profile["affiliation"] or None,
                        primary_profile["year"],
                        other_profile["year"],
                        now,
                    ),
                )
                candidate_count += 1

    identity_stats = assign_stable_ids(conn)
    restored_assignments = 0
    for assignment in saved_assignments:
        row = conn.execute(
            "SELECT author_id FROM authorships WHERE authorship_id=?",
            (assignment["authorship_id"],),
        ).fetchone()
        if not row or row["author_id"] is None:
            continue
        conn.execute(
            """
            INSERT INTO career_assignments
                (authorship_id, author_id, paper_id, stage, evidence_type, confidence,
                 source_url, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                assignment["authorship_id"],
                row["author_id"],
                assignment["paper_id"],
                assignment["stage"],
                assignment["evidence_type"],
                assignment["confidence"],
                assignment["source_url"],
                assignment["notes"],
                assignment["created_at"],
            ),
        )
        restored_assignments += 1

    edge_count = _rebuild_coauthorship(conn)
    conn.commit()

    stats = {
        "authors": author_count,
        "aliases": alias_count,
        "merge_candidates": candidate_count,
        "needs_review": review_count,
        "edges": edge_count,
        "stable_ids": identity_stats,
        "career_assignments_restored": restored_assignments,
    }
    log.info("Resolved authors: %s", stats)
    return stats


def _rebuild_coauthorship(conn: sqlite3.Connection) -> int:
    conn.execute("DELETE FROM coauthorship_edges")
    rows = conn.execute(
        """
        SELECT a.paper_id, a.author_id, p.published_year
        FROM authorships a
        JOIN papers p ON p.paper_id = a.paper_id
        WHERE p.content_type='article'
          AND p.is_duplicate=0
          AND a.author_id IS NOT NULL
        ORDER BY a.paper_id, a.author_id
        """
    ).fetchall()

    by_paper: dict[int, set[int]] = defaultdict(set)
    years: dict[int, int | None] = {}
    for row in rows:
        by_paper[int(row["paper_id"])].add(int(row["author_id"]))
        years[int(row["paper_id"])] = row["published_year"]

    edge_count = 0
    for paper_id, author_ids in by_paper.items():
        ordered = sorted(author_ids)
        for left_index in range(len(ordered)):
            for right_index in range(left_index + 1, len(ordered)):
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO coauthorship_edges
                        (author_a_id, author_b_id, paper_id, year)
                    VALUES (?, ?, ?, ?)
                    """,
                    (ordered[left_index], ordered[right_index], paper_id, years[paper_id]),
                )
                if cursor.rowcount:
                    edge_count += 1
    return edge_count

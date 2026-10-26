from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

import httpx

from . import db
from .authors import _rebuild_coauthorship
from .config import MAILTO, RAW_DIR
from .identity import ensure_identity_ledger
from .normalize import (
    clean_text,
    family_root,
    given_root,
    middle_initials,
    name_match_key,
    normalize_doi,
    normalize_name_part,
    normalize_orcid,
)

log = logging.getLogger(__name__)

OPENALEX_BASE = "https://api.openalex.org/works"
OPENALEX_RAW_DIR = RAW_DIR / "openalex"
WORKS_DIR = OPENALEX_RAW_DIR / "works"
USER_AGENT = f"EconPubDatabase/0.2 (mailto:{MAILTO})"

# OpenAlex byline recovery is a fallback for deposits that have no authors at
# all. It occasionally carries an issue-level or acknowledgement-level author
# list, so implausible backfills are rejected rather than promoted to a byline.
MAX_BACKFILL_AUTHORS = 12
_SUSPECT_BACKFILL_NAME = re.compile(
    r"\b(?:we\s+thank|thanks|acknowledg(?:e)?ment|anonymous|editor)\b", re.IGNORECASE
)


def _backfill_tokens(name: str | None) -> list[str]:
    return [token.lower() for token in re.findall(r"[^\W\d_]+", name or "", re.UNICODE)]


def _backfill_token_matches(left: str, right: str) -> bool:
    return (
        left == right
        or (len(left) == 1 and right.startswith(left))
        or (len(right) == 1 and left.startswith(right))
    )


def _backfill_compact(value: str | None) -> str:
    return "".join(re.findall(r"[^\W\d_]+", value or "", re.UNICODE)).lower()


def _backfill_name_quality(value: str | None) -> tuple[int, int, int]:
    tokens = _backfill_tokens(value)
    single_letters = sum(1 for token in tokens if len(token) == 1)
    return (single_letters, -len(tokens), -len(_backfill_compact(value)))


def _backfill_same_person(left: str | None, right: str | None) -> bool:
    """Detect repeated/abbreviated names within one OpenAlex byline.

    OpenAlex sometimes lists the same author twice: once in full and once as an
    initial or a bare given name. This is only used to collapse a single work's
    backfilled byline, never to merge canonical authors across works.
    """
    left_tokens = _backfill_tokens(left)
    right_tokens = _backfill_tokens(right)
    if not left_tokens or not right_tokens:
        return False
    if left_tokens == right_tokens:
        return True
    if _backfill_compact(left) == _backfill_compact(right):
        # Handles PDF/OpenAlex whitespace corruption such as "J Eremy T. F Ox"
        # versus "Jeremy T. Fox".
        return True
    left_family = left_tokens[-1]
    right_family = right_tokens[-1]
    if family_root(left_family) == family_root(right_family):
        left_given = left_tokens[:-1]
        right_given = right_tokens[:-1]
        if not left_given or not right_given:
            return False
        smaller, larger = (
            (left_given, right_given)
            if len(left_given) <= len(right_given)
            else (right_given, left_given)
        )
        if len(smaller) < len(larger) and all(
            any(_backfill_token_matches(token, other) for other in larger)
            for token in smaller
        ):
            return True
    if len(left_tokens) == 1 and left_tokens[0] in right_tokens[:-1]:
        return True
    if len(right_tokens) == 1 and right_tokens[0] in left_tokens[:-1]:
        return True
    return False


OPENALEX_SELECT = [
    "id",
    "doi",
    "title",
    "publication_date",
    "publication_year",
    "cited_by_count",
    "type",
    "authorships",
    "topics",
    "primary_topic",
    "abstract_inverted_index",
    "biblio",
    "primary_location",
]


def _request_json(
    client: httpx.Client,
    params: dict[str, Any],
    *,
    max_attempts: int = 6,
) -> dict[str, Any]:
    delay = 5.0
    last_error = "unknown error"
    for attempt in range(1, max_attempts + 1):
        try:
            response = client.get(OPENALEX_BASE, params=params)
            if response.status_code == 200:
                return response.json()
            if response.status_code in {429, 500, 502, 503, 504}:
                wait = delay
                retry_after = response.headers.get("Retry-After")
                if retry_after and retry_after.replace(".", "", 1).isdigit():
                    wait = float(retry_after)
                log.warning(
                    "OpenAlex HTTP %s (attempt %s/%s); sleeping %.1fs",
                    response.status_code,
                    attempt,
                    max_attempts,
                    wait,
                )
                last_error = f"HTTP {response.status_code}"
                time.sleep(wait)
                delay = min(delay * 2, 120.0)
                continue
            response.raise_for_status()
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_error = str(exc)
            log.warning(
                "OpenAlex request error (attempt %s/%s): %s",
                attempt,
                max_attempts,
                exc,
            )
            time.sleep(delay)
            delay = min(delay * 2, 120.0)
    raise RuntimeError(f"OpenAlex request failed after {max_attempts} attempts: {last_error}")


def _cache_path(dois: list[str]) -> Path:
    digest = hashlib.sha1("\n".join(sorted(dois)).encode("utf-8")).hexdigest()[:16]
    return WORKS_DIR / f"batch_{digest}.json"


def fetch_works_batch(
    client: httpx.Client,
    dois: list[str],
    *,
    per_page: int = 50,
) -> dict[str, Any]:
    filt = "doi:" + "|".join(dois)
    params = {
        "filter": filt,
        "per-page": per_page,
        "select": ",".join(OPENALEX_SELECT),
        "mailto": MAILTO,
    }
    return _request_json(client, params)


_CITATION_ABSTRACT_RE = re.compile(
    r"\bPublished in volume\b.*?\bof American Economic Review\b", re.IGNORECASE
)


def is_boilerplate_abstract(text: str | None) -> bool:
    """Reject OpenAlex abstracts that are really AEA page descriptions.

    OpenAlex occasionally reconstructs the meta description ("Title by Authors.
    Published in volume 108, issue 10 ... of American Economic Review") as an
    abstract. That is citation metadata, not an abstract.
    """
    if not text:
        return True
    if _CITATION_ABSTRACT_RE.search(text):
        return True
    lowered = text.lower()
    if lowered.startswith("abstract") and len(text) < 60:
        return True
    return False


def reconstruct_abstract(inverted_index: dict[str, Iterable[int]] | None) -> str | None:
    if not inverted_index:
        return None
    positions: dict[int, str] = {}
    for word, indexes in inverted_index.items():
        for index in indexes or []:
            try:
                positions[int(index)] = word
            except (TypeError, ValueError):
                continue
    if not positions:
        return None
    text = clean_text(" ".join(positions[index] for index in sorted(positions)))
    text = re.sub(r"^Abstract\s*[:.\-]?\s*", "", text, flags=re.IGNORECASE).strip()
    return text or None


def _strip_openalex_id(value: str | None) -> str | None:
    if not value:
        return None
    return value.rsplit("/", 1)[-1] or None


def parse_work(work: dict[str, Any]) -> dict[str, Any]:
    primary_location = work.get("primary_location") or {}
    source = primary_location.get("source") or {}
    authorships: list[dict[str, Any]] = []
    for entry in work.get("authorships") or []:
        author = entry.get("author") or {}
        institutions = []
        for institution in entry.get("institutions") or []:
            institutions.append(
                {
                    "openalex_id": _strip_openalex_id(institution.get("id")),
                    "display_name": clean_text(institution.get("display_name")) or None,
                    "country_code": institution.get("country_code"),
                    "ror": institution.get("ror"),
                    "type": institution.get("type"),
                }
            )
        authorships.append(
            {
                "openalex_author_id": _strip_openalex_id(author.get("id")),
                "author_name": clean_text(author.get("display_name")) or None,
                "orcid": normalize_orcid(author.get("orcid")) or None,
                "author_position": entry.get("author_position"),
                "is_corresponding": entry.get("is_corresponding"),
                "institutions": institutions,
                "raw_affiliation": "; ".join(
                    clean_text(value)
                    for value in (entry.get("raw_affiliation_strings") or [])
                    if clean_text(value)
                )
                or None,
            }
        )
    primary_topic = work.get("primary_topic") or {}
    primary_topic_id = primary_topic.get("id")
    topics = []
    for topic in work.get("topics") or []:
        topics.append(
            {
                "openalex_id": _strip_openalex_id(topic.get("id")),
                "label": clean_text(topic.get("display_name")) or None,
                "score": topic.get("score"),
                "is_primary": 1 if topic.get("id") == primary_topic_id else 0,
            }
        )
    return {
        "openalex_id": _strip_openalex_id(work.get("id")),
        "doi": normalize_doi(work.get("doi")),
        "title": clean_text(work.get("title")) or None,
        "publication_date": work.get("publication_date"),
        "publication_year": work.get("publication_year"),
        "cited_by_count": work.get("cited_by_count"),
        "type": work.get("type"),
        "source_id": _strip_openalex_id(source.get("id")),
        "source_name": clean_text(source.get("display_name")) or None,
        "authorships": authorships,
        "topics": topics,
        "abstract": reconstruct_abstract(work.get("abstract_inverted_index")),
        "biblio": work.get("biblio") or {},
    }


def _name_match(our_row: sqlite3.Row | dict[str, Any], oa_name: str | None) -> tuple[bool, str]:
    if not oa_name:
        return False, "low"
    our_full = clean_text(our_row["full_name"]) or (
        f"{clean_text(our_row['given_name'])} {clean_text(our_row['family_name'])}".strip()
    )
    our_norm = normalize_name_part(our_full)
    oa_norm = normalize_name_part(oa_name)
    if our_norm and our_norm == oa_norm:
        return True, "high"
    our_given = clean_text(our_row["given_name"])
    our_family = clean_text(our_row["family_name"])
    if not our_family and our_full:
        tokens = our_full.split()
        our_family = tokens[-1] if tokens else ""
        our_given = " ".join(tokens[:-1])
    if not our_family:
        return False, "low"
    our_given_tokens = normalize_name_part(our_given).split()
    our_initials_only = bool(our_given_tokens) and all(len(token) == 1 for token in our_given_tokens)
    tokens = oa_norm.split()
    for split in range(1, len(tokens)):
        oa_given = " ".join(tokens[:split])
        oa_family = " ".join(tokens[split:])
        if family_root(oa_family) != family_root(our_family):
            continue
        if given_root(oa_given) == given_root(our_given):
            return True, "medium"
        if our_initials_only:
            oa_given_tokens = normalize_name_part(oa_given).split()
            if oa_given_tokens and oa_given_tokens[0][0] == our_given_tokens[0][0]:
                return True, "low"
    return False, "low"


def match_authorships(
    our_rows: list[sqlite3.Row],
    oa_authorships: list[dict[str, Any]],
) -> list[tuple[sqlite3.Row, dict[str, Any], str, str]]:
    """Align our byline to OpenAlex authorships.

    Positional alignment is used only when the counts agree and every name is
    compatible. Otherwise names are matched uniquely; ambiguous names are left
    unmatched rather than guessed.
    """
    if not our_rows or not oa_authorships:
        return []
    if len(our_rows) == len(oa_authorships):
        checks = [
            _name_match(row, oa.get("author_name"))
            for row, oa in zip(our_rows, oa_authorships)
        ]
        if all(compatible for compatible, _ in checks):
            confidence = "high" if all(level == "high" for _, level in checks) else "medium"
            return [
                (row, oa, "position_name", confidence)
                for row, oa in zip(our_rows, oa_authorships)
            ]

    matches: list[tuple[sqlite3.Row, dict[str, Any], str, str]] = []
    used: set[int] = set()
    for row in our_rows:
        candidates: list[tuple[int, dict[str, Any], str]] = []
        for index, oa in enumerate(oa_authorships):
            if index in used:
                continue
            compatible, level = _name_match(row, oa.get("author_name"))
            if compatible:
                candidates.append((index, oa, level))
        if len(candidates) == 1:
            index, oa, level = candidates[0]
            used.add(index)
            matches.append((row, oa, "name", level))
    return matches


def _upsert_institution(conn: sqlite3.Connection, institution: dict[str, Any]) -> int | None:
    openalex_id = institution.get("openalex_id")
    display_name = institution.get("display_name")
    if not openalex_id or not display_name:
        return None
    row = conn.execute(
        "SELECT institution_id FROM institutions WHERE openalex_id=?", (openalex_id,)
    ).fetchone()
    if row:
        conn.execute(
            """
            UPDATE institutions
            SET display_name=?, country_code=?, country=?, ror=?, type=?
            WHERE institution_id=?
            """,
            (
                display_name,
                institution.get("country_code"),
                institution.get("country_code"),
                institution.get("ror"),
                institution.get("type"),
                row["institution_id"],
            ),
        )
        return int(row["institution_id"])

    normalized = normalize_name_part(display_name)
    row = conn.execute(
        "SELECT institution_id, openalex_id FROM institutions WHERE normalized_name=?",
        (normalized,),
    ).fetchone()
    if row:
        if not row["openalex_id"]:
            conn.execute(
                """
                UPDATE institutions
                SET openalex_id=?, display_name=?, country_code=?, country=?, ror=?, type=?
                WHERE institution_id=?
                """,
                (
                    openalex_id,
                    display_name,
                    institution.get("country_code"),
                    institution.get("country_code"),
                    institution.get("ror"),
                    institution.get("type"),
                    row["institution_id"],
                ),
            )
            return int(row["institution_id"])
        normalized = f"{normalized}#{openalex_id}"

    cursor = conn.execute(
        """
        INSERT INTO institutions
            (display_name, normalized_name, country, country_code, ror, type, openalex_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            display_name,
            normalized,
            institution.get("country_code"),
            institution.get("country_code"),
            institution.get("ror"),
            institution.get("type"),
            openalex_id,
            db.utcnow(),
        ),
    )
    return int(cursor.lastrowid)


def _apply_work(
    conn: sqlite3.Connection,
    paper_id: int,
    work: dict[str, Any],
    stats: dict[str, int],
) -> None:
    conn.execute(
        """
        UPDATE papers
        SET openalex_id=?,
            openalex_cited_by_count=?,
            openalex_publication_date=?,
            openalex_type=?,
            openalex_source_id=?
        WHERE paper_id=?
        """,
        (
            work["openalex_id"],
            work["cited_by_count"],
            work["publication_date"],
            work["type"],
            work["source_id"],
            paper_id,
        ),
    )

    conn.execute("DELETE FROM paper_topics WHERE paper_id=? AND scheme='openalex_topic'", (paper_id,))
    for topic in work["topics"]:
        if not topic["label"]:
            continue
        conn.execute(
            """
            INSERT OR IGNORE INTO paper_topics
                (paper_id, scheme, code, label, score, is_primary)
            VALUES (?, 'openalex_topic', ?, ?, ?, ?)
            """,
            (
                paper_id,
                topic["openalex_id"],
                topic["label"],
                topic["score"],
                topic["is_primary"],
            ),
        )
        stats["topics"] += 1

    row = conn.execute(
        "SELECT abstract_available FROM papers WHERE paper_id=?", (paper_id,)
    ).fetchone()
    if work["abstract"]:
        conn.execute(
            "UPDATE papers SET abstract_openalex=? WHERE paper_id=?",
            (work["abstract"], paper_id),
        )
        if not row["abstract_available"] and not is_boilerplate_abstract(work["abstract"]):
            conn.execute(
                """
                UPDATE papers
                SET abstract=?, abstract_available=1, abstract_source='openalex'
                WHERE paper_id=?
                """,
                (work["abstract"], paper_id),
            )
            stats["abstracts"] += 1

    our_rows = conn.execute(
        """
        SELECT authorship_id, author_order, given_name, family_name, full_name
        FROM authorships WHERE paper_id=? ORDER BY author_order
        """,
        (paper_id,),
    ).fetchall()
    if not our_rows and work["authorships"]:
        # Some publishers (notably Econometrica 2008–2014) deposit works
        # without author metadata. OpenAlex often has the byline; use it as a
        # bibliographic supplement while keeping the provenance explicit.
        backfill_authorships = list(work["authorships"])
        names = [
            clean_text(oa.get("author_name")) for oa in backfill_authorships
        ]
        if len(names) > MAX_BACKFILL_AUTHORS or any(
            _SUSPECT_BACKFILL_NAME.search(name) for name in names
        ):
            stats["authorships_skipped"] += 1
            return
        for order, oa in enumerate(backfill_authorships, start=1):
            display = clean_text(oa.get("author_name"))
            parts = display.split()
            given = " ".join(parts[:-1]) if len(parts) > 1 else None
            family = parts[-1] if parts else None
            institutions = [item for item in oa["institutions"] if item.get("openalex_id")]
            primary = institutions[0] if institutions else None
            for institution in institutions:
                _upsert_institution(conn, institution)
            conn.execute(
                """
                INSERT INTO authorships
                    (paper_id, author_order, given_name, family_name, full_name, orcid,
                     match_key, institution_hint, institution_source,
                     openalex_author_id, openalex_author_name, openalex_orcid,
                     openalex_raw_affiliation, openalex_match_method,
                     openalex_match_confidence, openalex_institution_id,
                     openalex_institution_name)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'openalex_backfill',
                        'medium', ?, ?)
                """,
                (
                    paper_id,
                    order,
                    given,
                    family,
                    display or None,
                    oa.get("orcid"),
                    name_match_key(given, family),
                    primary.get("display_name") if primary else None,
                    "openalex" if primary else None,
                    oa.get("openalex_author_id"),
                    display or None,
                    oa.get("orcid"),
                    oa.get("raw_affiliation"),
                    primary.get("openalex_id") if primary else None,
                    primary.get("display_name") if primary else None,
                ),
            )
            stats["authorships_created"] += 1
        conn.execute(
            "UPDATE papers SET content_type='article' "
            "WHERE paper_id=? AND content_type='unattributed'",
            (paper_id,),
        )
        return

    matches = match_authorships(our_rows, work["authorships"])
    stats["authorships_matched"] += len(matches)
    for our_row, oa, method, confidence in matches:
        institutions = [item for item in oa["institutions"] if item.get("openalex_id")]
        primary = institutions[0] if institutions else None
        institution_id = None
        institution_name = None
        for index, institution in enumerate(institutions):
            institution_id = _upsert_institution(conn, institution)
            if institution_id is None:
                continue
            if index == 0:
                institution_name = institution["display_name"]
            conn.execute(
                """
                INSERT OR IGNORE INTO authorship_institutions
                    (authorship_id, institution_id, source, is_primary, raw_name)
                VALUES (?, ?, 'openalex', ?, ?)
                """,
                (
                    our_row["authorship_id"],
                    institution_id,
                    1 if index == 0 else 0,
                    oa.get("raw_affiliation"),
                ),
            )
            stats["institutions"] += 1

        conn.execute(
            """
            UPDATE authorships
            SET openalex_author_id=?,
                openalex_author_name=?,
                openalex_raw_affiliation=?,
                openalex_match_method=CASE
                    WHEN openalex_match_method='openalex_backfill'
                    THEN 'openalex_backfill' ELSE ? END,
                openalex_match_confidence=?,
                openalex_institution_id=?,
                openalex_institution_name=?,
                institution_hint=CASE
                    WHEN (institution_hint IS NULL OR TRIM(institution_hint)='')
                         AND ? IS NOT NULL
                    THEN ? ELSE institution_hint END,
                institution_source=CASE
                    WHEN (institution_hint IS NULL OR TRIM(institution_hint)='')
                         AND ? IS NOT NULL
                    THEN 'openalex' ELSE institution_source END
            WHERE authorship_id=?
            """,
            (
                oa.get("openalex_author_id"),
                oa.get("author_name"),
                oa.get("raw_affiliation"),
                method,
                confidence,
                primary.get("openalex_id") if primary else None,
                primary.get("display_name") if primary else None,
                institution_name,
                institution_name,
                institution_name,
                our_row["authorship_id"],
            ),
        )


def enrich_openalex(
    conn,
    *,
    limit: int | None = None,
    batch_size: int = 50,
    resume: bool = True,
    refresh: bool = False,
) -> dict[str, int]:
    """DOI-keyed OpenAlex work enrichment. Never replaces the Crossref record."""
    WORKS_DIR.mkdir(parents=True, exist_ok=True)
    params = {"limit": limit, "batch_size": batch_size, "resume": resume, "refresh": refresh}
    run_id = db.start_run(conn, "openalex_work", params)
    stats = {
        "requested": 0,
        "matched": 0,
        "missing": 0,
        "abstracts": 0,
        "topics": 0,
        "authorships_matched": 0,
        "authorships_created": 0,
        "authorships_skipped": 0,
        "institutions": 0,
        "failed_batches": 0,
    }
    rows = conn.execute(
        """
        SELECT paper_id, doi
        FROM papers
        WHERE content_type IN ('article','unattributed')
          AND is_duplicate=0 AND doi_synthetic=0
        ORDER BY paper_id
        """
    ).fetchall()
    paper_by_doi = {}
    ordered: list[tuple[int, str]] = []
    for row in rows:
        doi = normalize_doi(row["doi"])
        if not doi or doi in paper_by_doi:
            continue
        paper_by_doi[doi] = int(row["paper_id"])
        ordered.append((int(row["paper_id"]), doi))
    if limit is not None:
        ordered = ordered[:limit]

    try:
        with httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=180.0,
            follow_redirects=True,
        ) as client:
            for batch_index in range(0, len(ordered), batch_size):
                batch = ordered[batch_index : batch_index + batch_size]
                dois = [doi for _, doi in batch]
                cache_path = _cache_path(dois)
                payload: dict[str, Any] | None = None
                if resume and not refresh and cache_path.exists():
                    try:
                        payload = json.loads(cache_path.read_text(encoding="utf-8"))
                    except Exception:
                        payload = None
                if payload is None:
                    try:
                        payload = fetch_works_batch(client, dois, per_page=batch_size)
                    except Exception as exc:
                        stats["failed_batches"] += 1
                        log.warning("OpenAlex batch failed (%s DOIs): %s", len(dois), exc)
                        continue
                    cache_path.write_text(
                        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
                    )
                    time.sleep(0.3)

                results = payload.get("results") or []
                by_doi = {
                    normalize_doi(work.get("doi")): work
                    for work in results
                    if normalize_doi(work.get("doi"))
                }
                for paper_id, doi in batch:
                    stats["requested"] += 1
                    work = by_doi.get(doi)
                    if not work:
                        stats["missing"] += 1
                        continue
                    try:
                        parsed = parse_work(work)
                        _apply_work(conn, paper_id, parsed, stats)
                    except Exception as exc:
                        log.warning("OpenAlex work parse/apply failed for %s: %s", doi, exc)
                        continue
                    db.save_source_record(conn, "openalex_work", doi, run_id, work)
                    stats["matched"] += 1
                conn.commit()
                log.info(
                    "OpenAlex batch %s/%s: requested=%s matched=%s missing=%s",
                    batch_index // batch_size + 1,
                    (len(ordered) + batch_size - 1) // batch_size,
                    stats["requested"],
                    stats["matched"],
                    stats["missing"],
                )
        db.finish_run(conn, run_id, "success", stats["matched"])
        log.info("OpenAlex enrichment complete: %s", stats)
        return stats
    except Exception as exc:
        conn.commit()
        db.finish_run(conn, run_id, "failed", stats["matched"], str(exc))
        raise


def clean_openalex_abstracts(conn) -> dict[str, int]:
    """Replace or drop OpenAlex abstracts that are citation boilerplate.

    AEA abstracts already stored in ``abstract_aea`` are preferred when they
    exist; otherwise the record returns to the missing state.
    """
    rows = conn.execute(
        """
        SELECT paper_id, abstract_openalex, abstract_aea
        FROM papers
        WHERE abstract_source='openalex'
        """
    ).fetchall()
    cleared = 0
    recovered = 0
    for row in rows:
        if not is_boilerplate_abstract(row["abstract_openalex"]):
            continue
        if row["abstract_aea"]:
            conn.execute(
                """
                UPDATE papers
                SET abstract=?, abstract_source='aea', abstract_available=1
                WHERE paper_id=?
                """,
                (row["abstract_aea"], row["paper_id"]),
            )
            recovered += 1
        else:
            conn.execute(
                """
                UPDATE papers
                SET abstract=NULL, abstract_source=NULL, abstract_available=0
                WHERE paper_id=?
                """,
                (row["paper_id"],),
            )
            cleared += 1
    conn.commit()
    stats = {"cleared": cleared, "recovered_from_aea": recovered}
    log.info("OpenAlex abstract cleanup: %s", stats)
    return stats


def apply_author_links(conn) -> dict[str, int]:
    """Link canonical authors to OpenAlex IDs and surface conflicts.

    OpenAlex is evidence, not authority: a conflict is queued for review rather
    than silently merging or splitting a canonical author.
    """
    conn.execute("DELETE FROM author_openalex_evidence")
    conn.execute(
        """
        UPDATE authors
        SET openalex_id=NULL,
            openalex_match_confidence=NULL,
            openalex_works_count=NULL,
            openalex_cited_by_count=NULL,
            openalex_last_institution_id=NULL,
            openalex_last_institution_name=NULL
        """
    )

    rows = conn.execute(
        """
        SELECT a.author_id,
               a.openalex_author_id,
               COUNT(*) AS paper_count,
               MIN(p.published_year) AS first_year,
               MAX(p.published_year) AS last_year,
               GROUP_CONCAT(DISTINCT a.openalex_institution_name) AS institutions
        FROM authorships a
        JOIN papers p ON p.paper_id = a.paper_id
        WHERE p.content_type='article'
          AND p.is_duplicate=0
          AND a.author_id IS NOT NULL
          AND a.openalex_author_id IS NOT NULL
        GROUP BY a.author_id, a.openalex_author_id
        """
    ).fetchall()

    by_author: dict[int, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        by_author[int(row["author_id"])].append(row)

    now = db.utcnow()
    authors_with_links = 0
    multi_id_authors = 0
    for author_id, evidence_rows in by_author.items():
        evidence_rows.sort(
            key=lambda row: (row["paper_count"], row["last_year"] or 0), reverse=True
        )
        total = sum(int(row["paper_count"]) for row in evidence_rows)
        dominant = evidence_rows[0]
        consistent = 1 if len(evidence_rows) == 1 else 0
        if not consistent:
            multi_id_authors += 1
            conn.execute("UPDATE authors SET needs_review=1 WHERE author_id=?", (author_id,))
        confidence = "high" if consistent and total >= 2 else ("medium" if consistent else "low")
        linked_id = dominant["openalex_author_id"] if consistent or dominant["paper_count"] >= 0.8 * total else None
        if linked_id:
            authors_with_links += 1
        last_institution = conn.execute(
            """
            SELECT a.openalex_institution_id, a.openalex_institution_name
            FROM authorships a
            JOIN papers p ON p.paper_id = a.paper_id
            WHERE a.author_id=? AND a.openalex_author_id=?
              AND a.openalex_institution_id IS NOT NULL
            ORDER BY p.published_year DESC, a.author_order
            LIMIT 1
            """,
            (author_id, dominant["openalex_author_id"]),
        ).fetchone()
        cited = conn.execute(
            """
            SELECT COALESCE(SUM(p.openalex_cited_by_count), 0) AS cited
            FROM authorships a
            JOIN papers p ON p.paper_id = a.paper_id
            WHERE a.author_id=? AND a.openalex_author_id=?
            """,
            (author_id, dominant["openalex_author_id"]),
        ).fetchone()["cited"]
        conn.execute(
            """
            UPDATE authors
            SET openalex_id=?,
                openalex_match_confidence=?,
                openalex_works_count=?,
                openalex_cited_by_count=?,
                openalex_last_institution_id=?,
                openalex_last_institution_name=?
            WHERE author_id=?
            """,
            (
                linked_id,
                confidence if linked_id else None,
                total,
                cited if linked_id else None,
                last_institution["openalex_institution_id"] if last_institution else None,
                last_institution["openalex_institution_name"] if last_institution else None,
                author_id,
            ),
        )
        for row in evidence_rows:
            conn.execute(
                """
                INSERT INTO author_openalex_evidence
                    (author_id, openalex_id, paper_count, first_year, last_year,
                     institutions, is_consistent, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    author_id,
                    row["openalex_author_id"],
                    row["paper_count"],
                    row["first_year"],
                    row["last_year"],
                    row["institutions"],
                    consistent,
                    now,
                ),
            )

    shared = conn.execute(
        """
        SELECT openalex_author_id,
               COUNT(DISTINCT author_id) AS n,
               GROUP_CONCAT(DISTINCT author_id) AS author_ids
        FROM authorships
        WHERE author_id IS NOT NULL AND openalex_author_id IS NOT NULL
        GROUP BY openalex_author_id
        HAVING COUNT(DISTINCT author_id) > 1
        """
    ).fetchall()

    new_candidates = 0
    shared_ids = 0
    for row in shared:
        author_ids = sorted({int(value) for value in str(row["author_ids"]).split(",") if value})
        if len(author_ids) < 2:
            continue
        shared_ids += 1
        for left_index in range(len(author_ids)):
            for right_index in range(left_index + 1, len(author_ids)):
                left_id = author_ids[left_index]
                right_id = author_ids[right_index]
                coauthored = conn.execute(
                    """
                    SELECT 1
                    FROM authorships a
                    JOIN authorships b ON b.paper_id = a.paper_id
                    WHERE a.author_id=? AND b.author_id=?
                    LIMIT 1
                    """,
                    (left_id, right_id),
                ).fetchone()
                if coauthored:
                    # The same OpenAlex ID on two coauthors is an OpenAlex
                    # error, not evidence that they are one person.
                    continue
                left = conn.execute(
                    "SELECT canonical_name FROM authors WHERE author_id=?", (left_id,)
                ).fetchone()
                right = conn.execute(
                    "SELECT canonical_name FROM authors WHERE author_id=?", (right_id,)
                ).fetchone()
                if not left or not right:
                    continue
                existing = conn.execute(
                    """
                    SELECT candidate_id FROM author_merge_candidates
                    WHERE (author_id_a=? AND author_id_b=?)
                       OR (author_id_a=? AND author_id_b=?)
                    """,
                    (left_id, right_id, right_id, left_id),
                ).fetchone()
                left_evidence = conn.execute(
                    """
                    SELECT MIN(p.published_year) AS first_year, MAX(p.published_year) AS last_year,
                           GROUP_CONCAT(DISTINCT a.openalex_institution_name) AS institutions
                    FROM authorships a JOIN papers p ON p.paper_id=a.paper_id
                    WHERE a.author_id=? AND a.openalex_author_id=?
                    """,
                    (left_id, row["openalex_author_id"]),
                ).fetchone()
                right_evidence = conn.execute(
                    """
                    SELECT MIN(p.published_year) AS first_year, MAX(p.published_year) AS last_year,
                           GROUP_CONCAT(DISTINCT a.openalex_institution_name) AS institutions
                    FROM authorships a JOIN papers p ON p.paper_id=a.paper_id
                    WHERE a.author_id=? AND a.openalex_author_id=?
                    """,
                    (right_id, row["openalex_author_id"]),
                ).fetchone()
                evidence = json.dumps(
                    {
                        "openalex_id": row["openalex_author_id"],
                        "shared_papers": int(row["n"]),
                        "left": left["canonical_name"],
                        "right": right["canonical_name"],
                    },
                    ensure_ascii=False,
                )
                if existing:
                    conn.execute(
                        "UPDATE author_merge_candidates SET evidence=? WHERE candidate_id=?",
                        (evidence, existing["candidate_id"]),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO author_merge_candidates
                            (author_id_a, author_id_b, reason, institution_a, institution_b,
                             year_a, year_b, evidence, status, created_at)
                        VALUES (?, ?, 'shared OpenAlex author ID', ?, ?, ?, ?, ?, 'pending', ?)
                        """,
                        (
                            left_id,
                            right_id,
                            left_evidence["institutions"],
                            right_evidence["institutions"],
                            left_evidence["first_year"],
                            right_evidence["first_year"],
                            evidence,
                            now,
                        ),
                    )
                    new_candidates += 1

    # Annotate every existing candidate with OpenAlex agreement/disagreement.
    candidates = conn.execute(
        "SELECT candidate_id, author_id_a, author_id_b FROM author_merge_candidates"
    ).fetchall()
    for candidate in candidates:
        left = conn.execute(
            "SELECT openalex_id FROM authors WHERE author_id=?", (candidate["author_id_a"],)
        ).fetchone()
        right = conn.execute(
            "SELECT openalex_id FROM authors WHERE author_id=?", (candidate["author_id_b"],)
        ).fetchone()
        evidence = json.dumps(
            {
                "left_openalex_id": left["openalex_id"] if left else None,
                "right_openalex_id": right["openalex_id"] if right else None,
                "verdict": (
                    "same"
                    if left and right and left["openalex_id"] and left["openalex_id"] == right["openalex_id"]
                    else "different"
                    if left and right and left["openalex_id"] and right["openalex_id"]
                    else "insufficient"
                ),
            },
            ensure_ascii=False,
        )
        conn.execute(
            "UPDATE author_merge_candidates SET evidence=? WHERE candidate_id=?",
            (evidence, candidate["candidate_id"]),
        )

    conn.commit()
    stats = {
        "authors_with_openalex": authors_with_links,
        "multi_id_authors": multi_id_authors,
        "shared_openalex_ids": shared_ids,
        "new_merge_candidates": new_candidates,
        "evidence_rows": len(rows),
    }
    log.info("OpenAlex author links: %s", stats)
    return stats


def _suffix_key(value: str | None) -> str:
    return "".join(char for char in (value or "").lower() if char.isalnum())


def _given_tokens(value: str | None) -> list[str]:
    return re.findall(r"[^\W\d_]+", value or "", re.UNICODE)


def _given_initials_compatible(left: str | None, right: str | None) -> bool:
    """Match ``N. G.`` to ``N. Gregory`` when every token is an initial.

    OpenAlex sometimes stores a shortened given name for the same profile.
    This is only used alongside an identical OpenAlex author ID and family
    name, so it does not open the door to unconstrained name matching.
    """
    left_tokens = _given_tokens(left)
    right_tokens = _given_tokens(right)
    if not left_tokens or len(left_tokens) != len(right_tokens):
        return False
    for left_token, right_token in zip(left_tokens, right_tokens):
        left_key = left_token.lower()
        right_key = right_token.lower()
        if left_key == right_key:
            continue
        if len(left_key) == 1 and right_key.startswith(left_key):
            continue
        if len(right_key) == 1 and left_key.startswith(right_key):
            continue
        return False
    return True


def _names_compatible_for_merge(left: sqlite3.Row, right: sqlite3.Row) -> bool:
    if left["suffix"] and right["suffix"] and _suffix_key(left["suffix"]) != _suffix_key(
        right["suffix"]
    ):
        return False
    left_initials = middle_initials(left["given_name"])
    right_initials = middle_initials(right["given_name"])
    if left_initials and right_initials and not (left_initials & right_initials):
        return False
    left_full = normalize_name_part(left["canonical_name"])
    right_full = normalize_name_part(right["canonical_name"])
    if left_full and left_full == right_full:
        return True
    left_family = clean_text(left["family_name"]) or left_full.split()[-1]
    right_family = clean_text(right["family_name"]) or right_full.split()[-1]
    if family_root(left_family) != family_root(right_family):
        return False
    left_given = clean_text(left["given_name"]) or " ".join(left_full.split()[:-1])
    right_given = clean_text(right["given_name"]) or " ".join(right_full.split()[:-1])
    if _given_initials_compatible(left_given, right_given):
        return True
    left_root = given_root(left_given)
    right_root = given_root(right_given)
    if left_root == right_root:
        return True
    if len(left_root) == 1 and right_root.startswith(left_root):
        return True
    if len(right_root) == 1 and left_root.startswith(right_root):
        return True
    return False


def dedupe_backfilled_authorships(conn) -> dict[str, int]:
    """Collapse repeated/abbreviated names inside OpenAlex backfilled bylines.

    A fresh enrichment pass now dedupes before inserting. This repair pass
    handles databases built before that guard existed.
    """
    paper_ids = [
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT paper_id FROM authorships "
            "WHERE openalex_match_method='openalex_backfill'"
        )
    ]
    removed = 0
    changed_papers = 0
    for paper_id in paper_ids:
        rows = conn.execute(
            """
            SELECT s.authorship_id, s.author_order, s.full_name, s.author_id,
                   (SELECT COUNT(*) FROM authorships x WHERE x.author_id=s.author_id)
                       AS author_papers
            FROM authorships s WHERE s.paper_id=? ORDER BY s.author_order
            """,
            (paper_id,),
        ).fetchall()
        clusters: list[dict[str, Any]] = []
        for row in rows:
            match = next(
                (
                    cluster
                    for cluster in clusters
                    if _backfill_same_person(
                        row["full_name"], cluster["best"]["full_name"]
                    )
                ),
                None,
            )
            if match is None:
                clusters.append(
                    {"best": row, "rows": [row], "min_order": row["author_order"]}
                )
                continue
            match["rows"].append(row)
            match["min_order"] = min(match["min_order"], row["author_order"])
            row_quality = (
                -int(row["author_papers"] or 0),
                *_backfill_name_quality(row["full_name"]),
            )
            best_quality = (
                -int(match["best"]["author_papers"] or 0),
                *_backfill_name_quality(match["best"]["full_name"]),
            )
            if row_quality < best_quality:
                match["best"] = row
        drop = [
            int(row["authorship_id"])
            for cluster in clusters
            for row in cluster["rows"]
            if row["authorship_id"] != cluster["best"]["authorship_id"]
        ]
        if not drop:
            continue
        conn.executemany(
            "DELETE FROM authorships WHERE authorship_id=?",
            [(authorship_id,) for authorship_id in drop],
        )
        # Break the (paper_id, author_order) uniqueness constraint before
        # assigning the final order.
        remaining = conn.execute(
            "SELECT authorship_id, author_order FROM authorships "
            "WHERE paper_id=? ORDER BY author_order",
            (paper_id,),
        ).fetchall()
        for row in remaining:
            conn.execute(
                "UPDATE authorships SET author_order=? WHERE authorship_id=?",
                (-row["author_order"], row["authorship_id"]),
            )
        desired_order = {
            cluster["best"]["authorship_id"]: cluster["min_order"]
            for cluster in clusters
        }
        remaining = conn.execute(
            "SELECT authorship_id, author_order FROM authorships "
            "WHERE paper_id=? ORDER BY author_order",
            (paper_id,),
        ).fetchall()
        remaining.sort(
            key=lambda row: (
                desired_order.get(row["authorship_id"], -row["author_order"]),
                row["authorship_id"],
            )
        )
        for order, row in enumerate(remaining, start=1):
            conn.execute(
                "UPDATE authorships SET author_order=? WHERE authorship_id=?",
                (order, row["authorship_id"]),
            )
        removed += len(drop)
        changed_papers += 1
    edges = _rebuild_coauthorship(conn) if removed else 0
    conn.commit()
    stats = {"papers_changed": changed_papers, "authorships_removed": removed, "edges": edges}
    log.info("Backfilled-byline dedupe: %s", stats)
    return stats


def merge_openalex_supported_authors(conn) -> dict[str, int]:
    """Merge two canonical authors only when OpenAlex says they are one person.

    This is deliberately narrow: the pair must already be a shared-OpenAlex-ID
    candidate, the OpenAlex IDs must agree, the names must be compatible, and
    the two authors must never appear on the same paper. The merge re-points
    authorships and aliases, removes the stale candidate, and rebuilds edges.
    """
    ensure_identity_ledger(conn)
    rows = conn.execute(
        """
        SELECT c.candidate_id, c.author_id_a, c.author_id_b, c.evidence,
               a.canonical_name AS name_a, a.given_name AS given_a,
               a.family_name AS family_a, a.suffix AS suffix_a,
               a.merged_variants AS variants_a,
               b.canonical_name AS name_b, b.given_name AS given_b,
               b.family_name AS family_b, b.suffix AS suffix_b,
               b.merged_variants AS variants_b
        FROM author_merge_candidates c
        JOIN authors a ON a.author_id = c.author_id_a
        JOIN authors b ON b.author_id = c.author_id_b
        WHERE c.reason='shared OpenAlex author ID' AND c.status='pending'
        ORDER BY c.candidate_id
        """
    ).fetchall()

    merges: list[tuple[int, int, int]] = []
    for row in rows:
        try:
            evidence = json.loads(row["evidence"] or "{}")
        except (TypeError, ValueError):
            continue
        left_id = evidence.get("left_openalex_id")
        right_id = evidence.get("right_openalex_id")
        if evidence.get("verdict") != "same" or not left_id or left_id != right_id:
            continue
        left = {
            "canonical_name": row["name_a"],
            "given_name": row["given_a"],
            "family_name": row["family_a"],
            "suffix": row["suffix_a"],
        }
        right = {
            "canonical_name": row["name_b"],
            "given_name": row["given_b"],
            "family_name": row["family_b"],
            "suffix": row["suffix_b"],
        }
        if not _names_compatible_for_merge(left, right):
            continue
        count_a = conn.execute(
            "SELECT COUNT(*) FROM authorships WHERE author_id=?", (row["author_id_a"],)
        ).fetchone()[0]
        count_b = conn.execute(
            "SELECT COUNT(*) FROM authorships WHERE author_id=?", (row["author_id_b"],)
        ).fetchone()[0]
        if (count_a, len(row["name_a"] or "")) >= (count_b, len(row["name_b"] or "")):
            target_id, source_id = row["author_id_a"], row["author_id_b"]
        else:
            target_id, source_id = row["author_id_b"], row["author_id_a"]
        merges.append((row["candidate_id"], target_id, source_id))

    if not merges:
        return {"merged": 0}

    conn.execute("DELETE FROM coauthorship_edges")
    merged = 0
    for candidate_id, target_id, source_id in merges:
        target = conn.execute(
            "SELECT stable_id FROM authors WHERE author_id=?", (target_id,)
        ).fetchone()
        source = conn.execute(
            "SELECT stable_id FROM authors WHERE author_id=?", (source_id,)
        ).fetchone()
        if not target or not source or not target["stable_id"] or not source["stable_id"]:
            # A previous merge in this pass can remove one side, or the
            # identity ledger may not have assigned a stable ID yet. Leave the
            # candidate pending rather than merging without an audit trail.
            continue
        target_stable = target["stable_id"]
        source_stable = source["stable_id"]
        conn.execute(
            "UPDATE authorships SET author_id=? WHERE author_id=?", (target_id, source_id)
        )
        conn.execute(
            "UPDATE author_aliases SET author_id=? WHERE author_id=?", (target_id, source_id)
        )
        conn.execute(
            "UPDATE career_events SET author_id=? WHERE author_id=?", (target_id, source_id)
        )
        conn.execute(
            "UPDATE career_assignments SET author_id=? WHERE author_id=?", (target_id, source_id)
        )
        conn.execute(
            "UPDATE author_merge_candidates SET author_id_a=? WHERE author_id_a=?",
            (target_id, source_id),
        )
        conn.execute(
            "UPDATE author_merge_candidates SET author_id_b=? WHERE author_id_b=?",
            (target_id, source_id),
        )
        conn.execute("DELETE FROM author_merge_candidates WHERE author_id_a=author_id_b")
        conn.execute("DELETE FROM author_merge_candidates WHERE candidate_id=?", (candidate_id,))
        conn.execute("DELETE FROM author_openalex_evidence WHERE author_id=?", (source_id,))
        conn.execute(
            """
            UPDATE authors
            SET merged_variants=merged_variants+?,
                updated_at=?
            WHERE author_id=?
            """,
            (
                conn.execute(
                    "SELECT merged_variants FROM authors WHERE author_id=?", (source_id,)
                ).fetchone()[0],
                db.utcnow(),
                target_id,
            ),
        )
        if source_stable:
            conn.execute(
                """
                UPDATE author_identity_ledger
                SET status='merged', current_author_id=?, updated_at=?
                WHERE stable_id=?
                """,
                (target_id, db.utcnow(), source_stable),
            )
            conn.execute(
                """
                INSERT INTO author_identity_events
                    (stable_id, event_type, related_stable_id, author_id, reason, created_at)
                VALUES (?, 'merged', ?, ?, 'shared OpenAlex author ID', ?)
                """,
                (source_stable, target_stable, target_id, db.utcnow()),
            )
        conn.execute("DELETE FROM authors WHERE author_id=?", (source_id,))
        merged += 1
    edges = _rebuild_coauthorship(conn)
    conn.commit()
    stats = {"merged": merged, "edges": edges}
    log.info("OpenAlex-supported author merges: %s", stats)
    return stats

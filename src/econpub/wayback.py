from __future__ import annotations

import hashlib
import json
import logging
import re

import httpx
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import quote

from . import db
from .career import ROLE_PATTERNS
from .config import RAW_DIR
from .cv import _fetch, _html_text_and_links
from .normalize import clean_text, normalize_name_part

log = logging.getLogger(__name__)

WAYBACK_DIR = RAW_DIR / "wayback"
DOCUMENTS_DIR = WAYBACK_DIR / "documents"
TEXTS_DIR = WAYBACK_DIR / "text"
CDX_API = "https://web.archive.org/cdx/search/cdx"
SNAPSHOT_BASE = "https://web.archive.org/web"

_STUDENT_PATTERNS = [
    (re.compile(r"\bph\.?\s*d\.?\s+(?:student|candidate)\b", re.I), "phd_student", "high"),
    (re.compile(r"\bdoctoral\s+(?:student|candidate)\b", re.I), "phd_student", "high"),
    (re.compile(r"\bgraduate\s+student\b", re.I), "phd_student", "medium"),
    (re.compile(r"\bpost-?doc(?:toral)?\b", re.I), "postdoc", "high"),
]


def _hash_bytes(content: bytes) -> str:
    return hashlib.sha1(content).hexdigest()


def _snapshot_year(timestamp: str) -> int | None:
    try:
        return int(str(timestamp)[:4])
    except (TypeError, ValueError):
        return None


def _cdx_url(source_url: str) -> str:
    return (
        f"{CDX_API}?url={quote(source_url, safe='')}&output=json"
        "&fl=timestamp,original,statuscode,mimetype"
        "&filter=statuscode:200&filter=mimetype:text/html"
        "&from=2000&to=2026&collapse=digest&limit=60"
    )


def _fetch_cdx(source_url: str) -> list[dict[str, str]]:
    content, _content_type, _final_url, error = _fetch(_cdx_url(source_url))
    if error or not content:
        return []
    try:
        rows = json.loads(content.decode("utf-8", errors="replace"))
    except ValueError:
        return []
    if not rows or not isinstance(rows, list):
        return []
    result = []
    for row in rows[1:]:
        if not isinstance(row, list) or len(row) < 2:
            continue
        result.append({"timestamp": str(row[0]), "original": str(row[1])})
    return result


def _pick_snapshots(
    snapshots: list[dict[str, str]], years: list[int]
) -> list[tuple[int, dict[str, str]]]:
    picked: list[tuple[int, dict[str, str]]] = []
    used: set[str] = set()
    for year in years:
        candidates = [
            item
            for item in snapshots
            if item["timestamp"] not in used
            and _snapshot_year(item["timestamp"]) is not None
            and abs((_snapshot_year(item["timestamp"]) or year) - year) <= 3
        ]
        if not candidates:
            continue
        best = min(
            candidates,
            key=lambda item: abs((_snapshot_year(item["timestamp"]) or year) - year),
        )
        used.add(best["timestamp"])
        picked.append((year, best))
    return picked


def _paper_years(conn, author_id: int, max_years: int) -> list[int]:
    rows = conn.execute(
        """
        SELECT DISTINCT p.published_year
        FROM authorships s
        JOIN papers p ON p.paper_id=s.paper_id
        WHERE s.author_id=? AND p.content_type='article' AND p.is_duplicate=0
          AND p.published_year IS NOT NULL
        ORDER BY p.published_year
        """,
        (author_id,),
    ).fetchall()
    years = [int(row["published_year"]) for row in rows]
    if len(years) <= max_years:
        return years
    indexes = {0, len(years) - 1}
    for part in range(1, max_years - 1):
        indexes.add(round(part * (len(years) - 1) / (max_years - 1)))
    return [years[index] for index in sorted(indexes)]


def collect_wayback_snapshots(
    conn,
    *,
    limit: int | None = None,
    max_years: int = 3,
    workers: int = 3,
) -> dict[str, int]:
    """Find archive snapshots near each author's AER publication years.

    Authors with the least career coverage are prioritized; the query also
    requires at least one public researcher URL from ORCID.
    """
    rows = conn.execute(
        """
        SELECT a.author_id, a.canonical_name, COUNT(DISTINCT s.paper_id) AS papers,
               COUNT(DISTINCT ca.paper_id) AS assigned
        FROM authors a
        JOIN authorships s ON s.author_id=a.author_id
        JOIN papers p ON p.paper_id=s.paper_id
            AND p.content_type='article' AND p.is_duplicate=0
        LEFT JOIN career_assignments ca ON ca.authorship_id=s.authorship_id
        WHERE EXISTS (
            SELECT 1 FROM author_cv_sources cv
            WHERE cv.author_id=a.author_id AND cv.source_type='orcid_researcher_url'
        )
        GROUP BY a.author_id
        ORDER BY (1.0 * COUNT(DISTINCT ca.paper_id) / COUNT(DISTINCT s.paper_id)) ASC,
                 papers DESC, a.canonical_name
        """
    ).fetchall()
    if limit is not None:
        rows = rows[:limit]
    stats = {
        "authors": len(rows),
        "urls": 0,
        "cdx_failed": 0,
        "snapshots": 0,
        "no_snapshots": 0,
    }
    tasks = []
    for row in rows:
        years = _paper_years(conn, int(row["author_id"]), max_years)
        if not years:
            continue
        sources = conn.execute(
            """
            SELECT url FROM author_cv_sources
            WHERE author_id=? AND source_type='orcid_researcher_url'
            ORDER BY source_id LIMIT 2
            """,
            (row["author_id"],),
        ).fetchall()
        for source in sources:
            tasks.append((int(row["author_id"]), source["url"], years))
            stats["urls"] += 1
    if not tasks:
        return stats
    try:
        probe = httpx.get(
            f"{CDX_API}?url=example.com&output=json&limit=1",
            timeout=10.0,
            follow_redirects=True,
        )
        healthy = probe.status_code == 200
    except httpx.HTTPError:
        healthy = False
    if not healthy:
        stats["archive_unavailable"] = 1
        log.warning("Wayback CDX is unreachable; skipping snapshot collection")
        return stats

    def cdx_task(task):
        author_id, url, years = task
        return author_id, url, years, _fetch_cdx(url)

    try:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            futures = {pool.submit(cdx_task, task): task for task in tasks}
            for index, future in enumerate(as_completed(futures), start=1):
                try:
                    author_id, url, years, snapshots = future.result()
                except Exception as exc:
                    log.warning("Wayback CDX worker failed: %s", exc)
                    stats["cdx_failed"] += 1
                    continue
                if not snapshots:
                    stats["cdx_failed"] += 1
                    continue
                picked = _pick_snapshots(snapshots, years)
                if not picked:
                    stats["no_snapshots"] += 1
                    continue
                for paper_year, snapshot in picked:
                    snapshot_url = f"{SNAPSHOT_BASE}/{snapshot['timestamp']}id_/{snapshot['original']}"
                    cursor = conn.execute(
                        """
                        INSERT OR IGNORE INTO author_wayback_snapshots
                            (author_id, source_url, original_url, snapshot_timestamp,
                             snapshot_url, paper_year, status, notes, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, 'candidate', ?, ?)
                        """,
                        (
                            author_id,
                            url,
                            snapshot["original"],
                            snapshot["timestamp"],
                            snapshot_url,
                            paper_year,
                            f"CDX snapshot {snapshot['timestamp']}",
                            db.utcnow(),
                        ),
                    )
                    if cursor.rowcount:
                        stats["snapshots"] += 1
                if index % 25 == 0:
                    conn.commit()
                    log.info(
                        "Wayback CDX %s/%s (snapshots=%s failed=%s)",
                        index,
                        len(tasks),
                        stats["snapshots"],
                        stats["cdx_failed"],
                    )
        conn.commit()
    finally:
        from .cv import _close_clients

        _close_clients()
    log.info("Wayback snapshot discovery: %s", stats)
    return stats


def fetch_wayback_snapshots(
    conn,
    *,
    limit: int | None = None,
    workers: int = 3,
) -> dict[str, int]:
    rows = conn.execute(
        """
        SELECT snapshot_id, snapshot_url
        FROM author_wayback_snapshots
        WHERE status='candidate'
        ORDER BY snapshot_id
        """
    ).fetchall()
    if limit is not None:
        rows = rows[:limit]
    stats = {"snapshots": len(rows), "fetched": 0, "failed": 0, "empty": 0}

    def fetch_task(row):
        content, content_type, final_url, error = _fetch(row["snapshot_url"])
        return row, content, content_type, final_url, error

    try:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            futures = {pool.submit(fetch_task, row): row for row in rows}
            for index, future in enumerate(as_completed(futures), start=1):
                try:
                    row, content, _content_type, final_url, error = future.result()
                except Exception as exc:
                    row = futures[future]
                    content = None
                    final_url = None
                    error = f"worker_error: {exc}"
                if error or content is None:
                    stats["failed"] += 1
                    conn.execute(
                        "UPDATE author_wayback_snapshots SET status='failed', notes=? WHERE snapshot_id=?",
                        (error or "fetch_failed", row["snapshot_id"]),
                    )
                    continue
                text, _links = _html_text_and_links(content, final_url or row["snapshot_url"])
                text = text[:300_000]
                digest = _hash_bytes(content)
                path = DOCUMENTS_DIR / f"{digest}.html"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
                TEXTS_DIR.mkdir(parents=True, exist_ok=True)
                (TEXTS_DIR / f"{digest}.txt").write_text(text, encoding="utf-8")
                status = "fetched" if len(text.strip()) >= 200 else "empty"
                if status == "empty":
                    stats["empty"] += 1
                else:
                    stats["fetched"] += 1
                conn.execute(
                    """
                    UPDATE author_wayback_snapshots
                    SET status=?, content_hash=?, local_path=?, fetched_at=?, notes=?
                    WHERE snapshot_id=?
                    """,
                    (
                        status,
                        digest,
                        str(path),
                        db.utcnow(),
                        f"{len(text)} chars; {final_url or row['snapshot_url']}",
                        row["snapshot_id"],
                    ),
                )
                if index % 25 == 0:
                    conn.commit()
                    log.info(
                        "Wayback fetch %s/%s (fetched=%s failed=%s empty=%s)",
                        index,
                        len(rows),
                        stats["fetched"],
                        stats["failed"],
                        stats["empty"],
                    )
        conn.commit()
    finally:
        from .cv import _close_clients

        _close_clients()
    log.info("Wayback snapshot fetch: %s", stats)
    return stats


def _fold_with_positions(text: str) -> tuple[str, list[int]]:
    """Transliterate text while keeping a map back to original offsets.

    Faculty pages often spell names with characters that NFKD does not
    decompose (Møller, Hortaçsu). Folding the page text makes the family-name
    search work without losing the positions used for proximity scoring.
    """
    from .normalize import transliterate

    chars: list[str] = []
    positions: list[int] = []
    for index, char in enumerate(text):
        for folded in transliterate(char):
            chars.append(folded)
            positions.append(index)
    return "".join(chars), positions


def _name_anchors(folded: str, name: str) -> list[tuple[int, int]]:
    """Find family-name occurrences that plausibly refer to this person."""
    parts = normalize_name_part(name).split()
    if not parts:
        return []
    family = parts[-1]
    given = parts[0]
    family_re = re.compile(rf"\b{re.escape(family)}\b", re.IGNORECASE)
    anchors: list[tuple[int, int]] = []
    all_matches = []
    for match in family_re.finditer(folded):
        all_matches.append((match.start(), match.end()))
        if len(all_matches) >= 80:
            break
    if len(parts) > 1 and given:
        given_re = re.compile(rf"\b{re.escape(given)}\b", re.IGNORECASE)
        initial_re = re.compile(rf"\b{re.escape(given[0])}\s*\.", re.IGNORECASE)
        for start, end in all_matches:
            nearby = folded[max(0, start - 100) : end + 100]
            if given_re.search(nearby) or initial_re.search(nearby):
                anchors.append((start, end))
    if not anchors:
        anchors = all_matches[:20]
    # Collapse anchors from repeated name mentions in the same heading.
    collapsed: list[tuple[int, int]] = []
    for start, end in anchors:
        if collapsed and start - collapsed[-1][1] < 120:
            continue
        collapsed.append((start, end))
        if len(collapsed) >= 20:
            break
    return collapsed


def _role_rank(stage: str, confidence: str) -> int:
    if confidence == "high" and stage in {
        "assistant_professor",
        "associate_professor",
        "full_professor",
        "emeritus",
        "lecturer_other_academic",
    }:
        return 5
    if stage == "phd_student":
        return 4
    if confidence == "high":
        return 4
    if confidence == "medium":
        return 3
    return 2


def _stage_near_name(text: str, name: str) -> tuple[str, str, str] | None:
    """Find the academic role phrase closest to the author's name.

    Proximity matters more than pattern specificity: a biography that
    mentions an NBER "Research Fellow" affiliation far from the name should
    not outrank the "Professor" title directly under it. A more specific
    title within a short distance still wins over a generic one.
    """
    folded, _positions = _fold_with_positions(text[:400_000])
    anchors = _name_anchors(folded, name)
    if not anchors:
        return None
    candidates: list[tuple[int, int, str, str, str]] = []
    for anchor_start, anchor_end in anchors:
        window_start = max(0, anchor_start - 220)
        window_end = min(len(folded), anchor_end + 220)
        window = folded[window_start:window_end]
        found_here: list[tuple[int, int, int, str, str, str]] = []
        for pattern, stage, confidence in _STUDENT_PATTERNS:
            for match in pattern.finditer(window):
                span = (window_start + match.start(), window_start + match.end())
                found_here.append(
                    (*span, _role_rank(stage, confidence), stage, confidence, clean_text(match.group(0)))
                )
        for pattern, stage, confidence in ROLE_PATTERNS:
            if stage == "non_academic":
                continue
            for match in pattern.finditer(window):
                span = (window_start + match.start(), window_start + match.end())
                if confidence == "low" and any(
                    not (span[1] <= other[0] or span[0] >= other[1])
                    and other[2] >= 4
                    for other in found_here
                ):
                    continue
                found_here.append(
                    (*span, _role_rank(stage, confidence), stage, confidence, clean_text(match.group(0)))
                )
        for span_start, span_end, rank, stage, confidence, phrase in found_here:
            if anchor_end <= span_start:
                distance = span_start - anchor_end
            elif span_end <= anchor_start:
                distance = anchor_start - span_end
            else:
                distance = 0
            candidates.append((distance, rank, stage, confidence, phrase))
    if not candidates:
        return None
    nearest = min(candidate[0] for candidate in candidates)
    close = [candidate for candidate in candidates if candidate[0] <= nearest + 30]
    _distance, _rank, stage, confidence, phrase = max(
        close, key=lambda candidate: (candidate[1], -candidate[0])
    )
    return stage, confidence, phrase


def _institution_for_year(conn, author_id: int, year: int) -> str | None:
    row = conn.execute(
        """
        SELECT COALESCE(s.openalex_institution_name, s.institution_hint) AS institution
        FROM authorships s
        JOIN papers p ON p.paper_id=s.paper_id
        WHERE s.author_id=? AND p.published_year=?
          AND p.content_type='article' AND p.is_duplicate=0
        ORDER BY (s.openalex_institution_name IS NULL), s.author_order
        LIMIT 1
        """,
        (author_id, year),
    ).fetchone()
    if row and row["institution"]:
        return clean_text(row["institution"])
    row = conn.execute(
        "SELECT openalex_last_institution_name FROM authors WHERE author_id=?",
        (author_id,),
    ).fetchone()
    return clean_text(row["openalex_last_institution_name"]) if row else None


def _event_key(author_id: int, year: int, stage: str) -> str:
    return f"wayback:{author_id}:{year}:{stage}"


def parse_wayback_snapshots(conn, *, limit: int | None = None) -> dict[str, int]:
    rows = conn.execute(
        """
        SELECT snapshot_id, author_id, paper_year, snapshot_url, content_hash,
               snapshot_timestamp
        FROM author_wayback_snapshots
        WHERE status='fetched' AND content_hash IS NOT NULL
        ORDER BY snapshot_id
        """
    ).fetchall()
    if limit is not None:
        rows = rows[:limit]
    stats = {
        "snapshots": len(rows),
        "parsed": 0,
        "events": 0,
        "no_signal": 0,
        "no_institution": 0,
    }
    for row in rows:
        text_path = TEXTS_DIR / f"{row['content_hash']}.txt"
        if not text_path.exists():
            stats["no_signal"] += 1
            continue
        text = text_path.read_text(encoding="utf-8", errors="replace")
        author = conn.execute(
            "SELECT canonical_name FROM authors WHERE author_id=?", (row["author_id"],)
        ).fetchone()
        if not author:
            continue
        match = _stage_near_name(text, author["canonical_name"])
        if not match:
            stats["no_signal"] += 1
            conn.execute(
                "UPDATE author_wayback_snapshots SET status='parsed', notes='0 signals' WHERE snapshot_id=?",
                (row["snapshot_id"],),
            )
            continue
        stage, confidence, phrase = match
        year = int(row["paper_year"])
        institution = _institution_for_year(conn, int(row["author_id"]), year)
        if not institution:
            stats["no_institution"] += 1
            conn.execute(
                "UPDATE author_wayback_snapshots SET status='parsed', notes='stage found, no institution' WHERE snapshot_id=?",
                (row["snapshot_id"],),
            )
            continue
        if confidence == "high":
            gap = abs((_snapshot_year(row["snapshot_timestamp"]) or year) - year)
            confidence = "medium" if gap <= 1 else "low"
        else:
            confidence = "low"
        conn.execute(
            "DELETE FROM career_events WHERE source_type='wayback' AND author_id=? AND start_year=? AND end_year=?",
            (row["author_id"], year, year),
        )
        conn.execute(
            """
            INSERT INTO career_events
                (author_id, event_type, title, institution, start_year, end_year,
                 is_current, source_url, source_type, source_snippet, event_key,
                 confidence, created_at)
            VALUES (?, 'employment', ?, ?, ?, ?, 0, ?, 'wayback', ?, ?, ?, ?)
            """,
            (
                row["author_id"],
                phrase,
                institution,
                year,
                year,
                row["snapshot_url"],
                json.dumps(
                    {
                        "phrase": phrase,
                        "snapshot": row["snapshot_timestamp"],
                        "source": row["snapshot_url"],
                    },
                    ensure_ascii=False,
                ),
                _event_key(int(row["author_id"]), year, stage),
                confidence,
                db.utcnow(),
            ),
        )
        stats["parsed"] += 1
        stats["events"] += 1
        conn.execute(
            "UPDATE author_wayback_snapshots SET status='parsed', notes=? WHERE snapshot_id=?",
            (f"{stage} ({phrase})", row["snapshot_id"]),
        )
        if stats["parsed"] % 25 == 0:
            conn.commit()
    conn.commit()
    log.info("Wayback parse: %s", stats)
    return stats


def run_wayback(
    conn,
    *,
    limit: int | None = None,
    max_years: int = 3,
    workers: int = 3,
    skip_collect: bool = False,
    skip_fetch: bool = False,
    skip_parse: bool = False,
) -> dict[str, Any]:
    from .career import assign_wayback_careers

    stats: dict[str, Any] = {}
    if not skip_collect:
        stats["collect"] = collect_wayback_snapshots(
            conn, limit=limit, max_years=max_years, workers=workers
        )
    if not skip_fetch:
        stats["fetch"] = fetch_wayback_snapshots(conn, limit=limit, workers=workers)
    if not skip_parse:
        stats["parse"] = parse_wayback_snapshots(conn, limit=limit)
    stats["careers"] = assign_wayback_careers(conn)
    return stats

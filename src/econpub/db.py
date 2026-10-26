from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .config import DB_PATH, SCHEMA_PATH
from .normalize import clean_text, name_match_key


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: Path | str = DB_PATH) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def connect_readonly(path: Path | str = DB_PATH) -> sqlite3.Connection:
    """Open an existing database without running migrations or writing."""
    path = Path(path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Database not found: {path}")
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


MIGRATION_COLUMNS: dict[str, dict[str, str]] = {
    "papers": {
        "journal_code": "TEXT",
        "abstract_source": "TEXT",
        "abstract_aea": "TEXT",
        "abstract_openalex": "TEXT",
        "openalex_id": "TEXT",
        "openalex_cited_by_count": "INTEGER",
        "openalex_publication_date": "TEXT",
        "openalex_type": "TEXT",
        "openalex_source_id": "TEXT",
        "date_source": "TEXT",
        "date_confidence": "TEXT",
        "aea_url": "TEXT",
        "aea_fetched_at": "TEXT",
    },
    "authors": {
        "stable_id": "TEXT",
        "orcid_source": "TEXT",
        "orcid_match_confidence": "TEXT",
        "wikidata_id": "TEXT",
        "openalex_match_confidence": "TEXT",
        "openalex_works_count": "INTEGER",
        "openalex_cited_by_count": "INTEGER",
        "openalex_last_institution_id": "TEXT",
        "openalex_last_institution_name": "TEXT",
        "review_status": "TEXT",
    },
    "authorships": {
        "institution_source": "TEXT",
        "openalex_author_id": "TEXT",
        "openalex_author_name": "TEXT",
        "openalex_orcid": "TEXT",
        "openalex_institution_id": "TEXT",
        "openalex_institution_name": "TEXT",
        "openalex_raw_affiliation": "TEXT",
        "openalex_match_method": "TEXT",
        "openalex_match_confidence": "TEXT",
    },
    "author_merge_candidates": {
        "evidence": "TEXT",
        "review_notes": "TEXT",
        "reviewed_at": "TEXT",
    },
    "career_events": {
        "source_snippet": "TEXT",
        "event_key": "TEXT",
    },
    "career_assignments": {
        "career_event_id": "INTEGER",
    },
    "institutions": {
        "country_code": "TEXT",
        "ror": "TEXT",
        "type": "TEXT",
    },
    "paper_topics": {
        "score": "REAL",
        "is_primary": "INTEGER NOT NULL DEFAULT 0",
    },
}


def migrate_db(conn: sqlite3.Connection) -> None:
    """Add M2 columns to a database created by an earlier pipeline run.

    SQLite has no ``ADD COLUMN IF NOT EXISTS``, so each table is inspected
    first. The provenance backfills are idempotent.
    """
    for table, columns in MIGRATION_COLUMNS.items():
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        for name, declaration in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_papers_openalex ON papers(openalex_id)")
    # Everything ingested before the journal registry existed is AER. New
    # harvests write journal_code explicitly, so the backfill is safe.
    conn.execute(
        "UPDATE papers SET journal_code='AER' WHERE journal_code IS NULL OR journal_code=''"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_papers_journal_year "
        "ON papers(journal_code, published_year)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_authorships_openalex ON authorships(openalex_author_id)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_authors_stable "
        "ON authors(stable_id) WHERE stable_id IS NOT NULL"
    )
    conn.execute("DROP INDEX IF EXISTS idx_career_event_key")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_career_event_key "
        "ON career_events(event_key)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_authorships_orcid ON authorships(openalex_orcid)"
    )
    conn.execute(
        "UPDATE papers SET abstract_source='crossref' "
        "WHERE abstract_available=1 AND abstract_source IS NULL"
    )
    conn.execute(
        "UPDATE papers SET date_source='crossref' "
        "WHERE published_year IS NOT NULL AND date_source IS NULL"
    )
    conn.execute(
        "UPDATE authorships SET institution_source='crossref' "
        "WHERE institution_hint IS NOT NULL AND TRIM(institution_hint) <> '' "
        "AND institution_source IS NULL"
    )
    conn.commit()


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    migrate_db(conn)
    conn.commit()


def start_run(conn: sqlite3.Connection, source: str, params: dict[str, Any]) -> int:
    cursor = conn.execute(
        "INSERT INTO harvest_runs (source, started_at, status, params_json) VALUES (?, ?, 'running', ?)",
        (source, utcnow(), json.dumps(params, ensure_ascii=False, default=str)),
    )
    conn.commit()
    return int(cursor.lastrowid)


def finish_run(
    conn: sqlite3.Connection,
    run_id: int,
    status: str,
    records_seen: int,
    error: str | None = None,
) -> None:
    conn.execute(
        "UPDATE harvest_runs SET finished_at=?, status=?, records_seen=?, error=? WHERE run_id=?",
        (utcnow(), status, records_seen, error, run_id),
    )
    conn.commit()


def save_source_record(
    conn: sqlite3.Connection,
    source: str,
    source_key: str,
    run_id: int,
    payload: dict[str, Any],
) -> None:
    conn.execute(
        """INSERT INTO source_records (source, source_key, run_id, fetched_at, payload_json)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(source, source_key) DO UPDATE SET
             run_id=excluded.run_id,
             fetched_at=excluded.fetched_at,
             payload_json=excluded.payload_json""",
        (source, source_key, run_id, utcnow(), json.dumps(payload, ensure_ascii=False, default=str)),
    )


def upsert_paper(conn: sqlite3.Connection, paper: dict[str, Any]) -> int:
    now = utcnow()
    params = {**paper, "now": now}
    conn.execute(
        """INSERT INTO papers (
              doi, doi_synthetic, title, item_type, content_type, journal_code, container_title, issn, publisher,
              volume, issue, page_first, page_last, published_year, published_month,
              published_day, published_date, published_print_date, published_online_date,
              abstract, abstract_available, citation_count,
              url, is_pp, pp_confidence, source_primary, created_at, updated_at
           ) VALUES (
              :doi, :doi_synthetic, :title, :item_type, :content_type, :journal_code, :container_title, :issn, :publisher,
              :volume, :issue, :page_first, :page_last, :published_year, :published_month,
              :published_day, :published_date, :published_print_date, :published_online_date,
              :abstract, :abstract_available, :citation_count,
              :url, :is_pp, :pp_confidence, :source_primary, :now, :now
           )
           ON CONFLICT(doi) DO UPDATE SET
              doi_synthetic=excluded.doi_synthetic,
              title=excluded.title,
              item_type=excluded.item_type,
              content_type=excluded.content_type,
              journal_code=excluded.journal_code,
              container_title=excluded.container_title,
              issn=excluded.issn,
              publisher=excluded.publisher,
              volume=excluded.volume,
              issue=excluded.issue,
              page_first=excluded.page_first,
              page_last=excluded.page_last,
              published_year=excluded.published_year,
              published_month=excluded.published_month,
              published_day=excluded.published_day,
              published_date=excluded.published_date,
              published_print_date=excluded.published_print_date,
              published_online_date=excluded.published_online_date,
              abstract=excluded.abstract,
              abstract_available=excluded.abstract_available,
              citation_count=excluded.citation_count,
              url=excluded.url,
              is_pp=excluded.is_pp,
              pp_confidence=excluded.pp_confidence,
              source_primary=excluded.source_primary,
              updated_at=excluded.updated_at""",
        params,
    )
    row = conn.execute("SELECT paper_id FROM papers WHERE doi=?", (paper["doi"],)).fetchone()
    if row is None:
        raise RuntimeError(f"paper upsert failed for DOI {paper['doi']!r}")
    return int(row["paper_id"])


def upsert_authorships(
    conn: sqlite3.Connection,
    paper_id: int,
    authorships: list[dict[str, Any]],
) -> None:
    for authorship in authorships:
        params = {
            **authorship,
            "paper_id": paper_id,
            "author_id": None,
            "match_key": name_match_key(authorship.get("given_name"), authorship.get("family_name")) or None,
        }
        conn.execute(
            """INSERT INTO authorships (
                  paper_id, author_id, author_order, given_name, family_name, full_name,
                  affiliation_raw, institution_hint, orcid, suffix, match_key,
                  sequence, is_corresponding, rank_raw, rank_category
               ) VALUES (
                  :paper_id, :author_id, :author_order, :given_name, :family_name, :full_name,
                  :affiliation_raw, :institution_hint, :orcid, :suffix, :match_key,
                  :sequence, :is_corresponding, :rank_raw, :rank_category
               )
               ON CONFLICT(paper_id, author_order) DO UPDATE SET
                  author_id=excluded.author_id,
                  given_name=excluded.given_name,
                  family_name=excluded.family_name,
                  full_name=excluded.full_name,
                  affiliation_raw=excluded.affiliation_raw,
                  institution_hint=excluded.institution_hint,
                  orcid=excluded.orcid,
                  suffix=excluded.suffix,
                  match_key=excluded.match_key,
                  sequence=excluded.sequence,
                  is_corresponding=excluded.is_corresponding,
                  rank_raw=excluded.rank_raw,
                  rank_category=excluded.rank_category""",
            params,
        )
    if authorships:
        conn.execute(
            "DELETE FROM authorships WHERE paper_id=? AND author_order > ?",
            (paper_id, len(authorships)),
        )
    else:
        conn.execute("DELETE FROM authorships WHERE paper_id=?", (paper_id,))


def insert_topics(conn: sqlite3.Connection, paper_id: int, topics: Iterable[str]) -> None:
    conn.execute("DELETE FROM paper_topics WHERE paper_id=? AND scheme='crossref_subject'", (paper_id,))
    for label in topics:
        label_text = clean_text(label)
        if not label_text:
            continue
        conn.execute(
            """INSERT OR IGNORE INTO paper_topics (paper_id, scheme, code, label)
               VALUES (?, 'crossref_subject', NULL, ?)""",
            (paper_id, label_text),
        )

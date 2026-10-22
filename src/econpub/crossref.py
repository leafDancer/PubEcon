from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import httpx

from . import db
from .config import (
    CROSSREF_BASE,
    CROSSREF_SELECT,
    JOURNAL_ISSN,
    MAILTO,
    RAW_DIR,
    START_YEAR,
    USER_AGENT,
)
from .normalize import (
    canonical_name,
    clean_text,
    date_parts,
    extract_date,
    extract_institution_hint,
    extract_rank,
    normalize_doi,
    normalize_orcid,
    split_pages,
    synthetic_key,
)

log = logging.getLogger(__name__)

RAW_CROSSREF_DIR = RAW_DIR / "crossref"
PAGES_DIR = RAW_CROSSREF_DIR / "pages"


def _request_json(
    client: httpx.Client,
    url: str,
    params: dict[str, Any],
    max_attempts: int = 6,
) -> dict[str, Any]:
    delay = 5.0
    last_error = "unknown error"
    for attempt in range(1, max_attempts + 1):
        try:
            response = client.get(url, params=params)
            if response.status_code == 200:
                return response.json()
            if response.status_code in {429, 500, 502, 503, 504}:
                retry_after = response.headers.get("Retry-After")
                if retry_after and retry_after.replace(".", "", 1).isdigit():
                    wait = float(retry_after)
                else:
                    wait = delay
                log.warning(
                    "Crossref HTTP %s (attempt %s/%s); sleeping %.1fs",
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
                "Crossref request error (attempt %s/%s): %s",
                attempt,
                max_attempts,
                exc,
            )
            time.sleep(delay)
            delay = min(delay * 2, 120.0)
    raise RuntimeError(f"Crossref request failed after {max_attempts} attempts: {last_error}")


def fetch_page(
    client: httpx.Client,
    *,
    cursor: str = "*",
    rows: int = 1000,
    start_year: int = START_YEAR,
) -> dict[str, Any]:
    params = {
        "filter": f"from-pub-date:{start_year}-01-01",
        "rows": rows,
        "cursor": cursor,
        "select": ",".join(CROSSREF_SELECT),
        "mailto": MAILTO,
    }
    url = f"{CROSSREF_BASE}/journals/{JOURNAL_ISSN}/works"
    return _request_json(client, url, params)


def _format_date(year: int | None, month: int | None, day: int | None) -> str | None:
    if year and month and day:
        return f"{year:04d}-{month:02d}-{day:02d}"
    if year and month:
        return f"{year:04d}-{month:02d}"
    if year:
        return f"{year:04d}"
    return None


def parse_item(item: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    title = clean_text(item.get("title"))
    doi = normalize_doi(item.get("DOI"))
    year, month, day = extract_date(item)
    print_year, print_month, print_day = date_parts(item, "published-print")
    online_year, online_month, online_day = date_parts(item, "published-online")
    page_first, page_last = split_pages(item.get("page"))
    if not doi:
        doi = synthetic_key(title, year, page_first)
        doi_synthetic = 1
    else:
        doi_synthetic = 0

    abstract = clean_text(item.get("abstract"))
    published_date = _format_date(year, month, day)

    paper = {
        "doi": doi,
        "doi_synthetic": doi_synthetic,
        "title": title or None,
        "item_type": item.get("type"),
        "content_type": "article",
        "container_title": clean_text(item.get("container-title")) or None,
        "issn": ", ".join(item.get("ISSN") or []) or None,
        "publisher": item.get("publisher"),
        "volume": str(item.get("volume")) if item.get("volume") is not None else None,
        "issue": str(item.get("issue")) if item.get("issue") is not None else None,
        "page_first": page_first,
        "page_last": page_last,
        "published_year": year,
        "published_month": month,
        "published_day": day,
        "published_date": published_date,
        "published_print_date": _format_date(print_year, print_month, print_day),
        "published_online_date": _format_date(online_year, online_month, online_day),
        "abstract": abstract or None,
        "abstract_available": 1 if abstract else 0,
        "citation_count": item.get("is-referenced-by-count"),
        "url": item.get("URL"),
        "is_pp": 0,
        "pp_confidence": None,
        "source_primary": "crossref",
    }

    authors: list[dict[str, Any]] = []
    for order, author in enumerate(item.get("author") or [], start=1):
        given = clean_text(author.get("given"))
        family = clean_text(author.get("family"))
        full_name = clean_text(author.get("name")) or canonical_name(given, family)
        affiliations = [
            clean_text(affiliation.get("name"))
            for affiliation in (author.get("affiliation") or [])
            if clean_text(affiliation.get("name"))
        ]
        affiliation_raw = "; ".join(affiliations)
        rank_raw, rank_category = extract_rank(affiliation_raw)
        authors.append(
            {
                "author_order": order,
                "given_name": given or None,
                "family_name": family or None,
                "full_name": full_name or None,
                "affiliation_raw": affiliation_raw or None,
                "institution_hint": extract_institution_hint(affiliation_raw),
                "orcid": normalize_orcid(author.get("ORCID")) or None,
                "suffix": clean_text(author.get("suffix")) or None,
                "sequence": author.get("sequence"),
                "is_corresponding": None,
                "rank_raw": rank_raw,
                "rank_category": rank_category,
            }
        )

    topics = [clean_text(subject) for subject in (item.get("subject") or []) if clean_text(subject)]
    return paper, authors, topics


def harvest(
    conn,
    *,
    rows: int = 1000,
    max_pages: int | None = None,
    resume: bool = False,
    refresh: bool = False,
    request_interval: float = 1.0,
    start_year: int = START_YEAR,
) -> int:
    PAGES_DIR.mkdir(parents=True, exist_ok=True)
    params = {
        "issn": JOURNAL_ISSN,
        "start_year": start_year,
        "rows": rows,
        "select": CROSSREF_SELECT,
    }
    run_id = db.start_run(conn, "crossref", params)
    seen = 0
    page_number = 0
    cursor = "*"
    started = time.monotonic()

    try:
        with httpx.Client(
            timeout=180.0,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        ) as client:
            while True:
                page_number += 1
                page_path = PAGES_DIR / f"page_{page_number:04d}.json"
                if resume and not refresh and page_path.exists():
                    log.info("Page %s loaded from %s", page_number, page_path)
                    payload = json.loads(page_path.read_text(encoding="utf-8"))
                else:
                    log.info("Fetching page %s (cursor=%s...)", page_number, cursor[:18])
                    payload = fetch_page(client, cursor=cursor, rows=rows, start_year=start_year)
                    temp_path = page_path.with_suffix(".json.tmp")
                    temp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                    temp_path.replace(page_path)
                    if request_interval:
                        time.sleep(request_interval)

                message = payload.get("message") or {}
                items = message.get("items") or []
                for item in items:
                    paper, authors, topics = parse_item(item)
                    db.save_source_record(conn, "crossref", paper["doi"], run_id, item)
                    paper_id = db.upsert_paper(conn, paper)
                    db.upsert_authorships(conn, paper_id, authors)
                    db.insert_topics(conn, paper_id, topics)
                conn.commit()

                seen += len(items)
                total = message.get("total-results")
                log.info(
                    "Page %s: %s items (seen=%s / total=%s)",
                    page_number,
                    len(items),
                    seen,
                    total,
                )

                next_cursor = message.get("next-cursor")
                if not items or len(items) < rows or not next_cursor or next_cursor == cursor:
                    break
                cursor = next_cursor
                if max_pages is not None and page_number >= max_pages:
                    log.info("Stopping after max_pages=%s", max_pages)
                    break

        db.finish_run(conn, run_id, "success", seen)
        log.info("Harvest complete: %s records in %.1fs", seen, time.monotonic() - started)
        return seen
    except Exception as exc:
        db.finish_run(conn, run_id, "failed", seen, str(exc))
        raise

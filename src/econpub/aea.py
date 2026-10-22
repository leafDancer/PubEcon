from __future__ import annotations

import html as html_lib
import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import httpx

from . import db
from .config import MAILTO, RAW_DIR
from .normalize import clean_text, normalize_doi, normalize_issue

log = logging.getLogger(__name__)

AEA_BASE = "https://www.aeaweb.org/articles"
ISSUES_URL = "https://www.aeaweb.org/journals/aer/issues"
RAW_AEA_DIR = RAW_DIR / "aea"
PAGES_DIR = RAW_AEA_DIR / "pages"
ISSUE_LIST_PATH = RAW_AEA_DIR / "issue_list.html"
FAILURES_PATH = RAW_AEA_DIR / "failures.jsonl"

# AEA serves the public article pages to browsers. The generic pipeline UA is
# not rejected, but a browser-like UA plus the proxy settings inherited from
# the environment is markedly more reliable.
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

_META_RE = re.compile(r"<meta\b(?:\"[^\"]*\"|'[^']*'|[^'\">])*>", re.IGNORECASE | re.DOTALL)
_ATTR_RE = re.compile(
    r"([A-Za-z_:][-A-Za-z0-9_:.]*)\s*=\s*(['\"])(.*?)\2",
    re.DOTALL,
)
_JEL_BLOCK_RE = re.compile(
    r"<ul\s+class=['\"]jel-codes['\"]\s*>(.*?)</ul>",
    re.IGNORECASE | re.DOTALL,
)
_JEL_ITEM_RE = re.compile(
    r"<(?:strong|span)\s+class=['\"]code['\"]\s*>\s*([A-Z]\d{1,2})\s*"
    r"</(?:strong|span)>(.*?)(?=<li\b|</li\b|</ul>)",
    re.IGNORECASE | re.DOTALL,
)
_ABSTRACT_RE = re.compile(
    r"<section\s+class=['\"][^'\"]*article-information\s+abstract[^'\"]*['\"]\s*>(.*?)</section>",
    re.IGNORECASE | re.DOTALL,
)
_ISSUE_LINK_RE = re.compile(
    r"<a\s+href=['\"]/issues/(\d+)['\"][^>]*>(.*?)</a>",
    re.IGNORECASE | re.DOTALL,
)
_ISSUE_LABEL_RE = re.compile(
    r"([A-Z][a-z]+)\s+(\d{4})\s*\(Vol\.\s*(\d+),\s*No\.\s*(\d+(?:\s*-\s*\d+)?)\)",
    re.IGNORECASE,
)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_MONTHS = {
    name.lower(): index
    for index, name in enumerate(
        [
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ],
        start=1,
    )
}


def _parse_attributes(tag: str) -> dict[str, str]:
    return {
        match.group(1).lower(): html_lib.unescape(match.group(3))
        for match in _ATTR_RE.finditer(tag)
    }


def _meta_tags(html_text: str) -> dict[str, list[str]]:
    tags: dict[str, list[str]] = {}
    for match in _META_RE.finditer(html_text):
        attrs = _parse_attributes(match.group(0))
        name = attrs.get("name") or attrs.get("property")
        content = attrs.get("content")
        if name and content is not None:
            tags.setdefault(name.lower(), []).append(content)
    return tags


def _first(tags: dict[str, list[str]], *names: str) -> str | None:
    for name in names:
        values = tags.get(name.lower())
        if values:
            return values[0]
    return None


def _plain(fragment: str) -> str:
    text = _TAG_RE.sub(" ", fragment)
    text = html_lib.unescape(text).replace("\xa0", " ")
    return _WS_RE.sub(" ", text).strip()


def _parse_jel(html_text: str) -> list[dict[str, str]]:
    block = _JEL_BLOCK_RE.search(html_text)
    if not block:
        return []
    entries: list[dict[str, str]] = []
    for match in _JEL_ITEM_RE.finditer(block.group(1)):
        code = match.group(1).strip().upper()
        label = _plain(match.group(2)).strip(" ;,.")
        if code and label:
            entries.append({"code": code, "label": label})
    return entries


def _looks_truncated(text: str) -> bool:
    stripped = text.rstrip()
    return stripped.endswith("...") or stripped.endswith("…")


def _parse_abstract(html_text: str, tags: dict[str, list[str]]) -> str | None:
    block = _ABSTRACT_RE.search(html_text)
    if block:
        text = _plain(block.group(1))
        text = re.sub(r"^Abstract\s*", "", text, flags=re.IGNORECASE).strip()
        if text:
            return text
    twitter = _first(tags, "twitter:description")
    if twitter:
        text = re.sub(r"^\([^)]*\)\s*[-–—]\s*", "", clean_text(twitter)).strip()
        if len(text) >= 80 and not _looks_truncated(text):
            return text
    description = _first(tags, "description")
    if description and "Abstract:" in description:
        text = clean_text(description.split("Abstract:", 1)[1])
        if len(text) >= 80 and not _looks_truncated(text):
            return text
    return None


def _parse_date(tags: dict[str, list[str]]) -> tuple[int | None, int | None]:
    value = _first(tags, "citation_publication_date")
    if value:
        match = re.match(r"\s*(\d{4})[/-](\d{1,2})", value)
        if match:
            return int(match.group(1)), int(match.group(2))
    description = _first(tags, "description") or ""
    match = re.search(
        r"of\s+American Economic Review,\s*([A-Z][a-z]+)\s+(\d{4})",
        description,
    )
    if match:
        month = _MONTHS.get(match.group(1).lower())
        if month:
            return int(match.group(2)), month
    return None, None


def parse_article_page(html_text: str, doi: str) -> dict[str, Any]:
    """Parse the subset of the AEA article page the project needs."""
    tags = _meta_tags(html_text)
    year, month = _parse_date(tags)
    parsed_doi = normalize_doi(_first(tags, "citation_doi")) or normalize_doi(doi)
    volume = _first(tags, "citation_volume")
    issue = _first(tags, "citation_issue")
    first_page = _first(tags, "citation_firstpage")
    last_page = _first(tags, "citation_lastpage")
    abstract = _parse_abstract(html_text, tags)
    return {
        "doi": parsed_doi,
        "title": clean_text(_first(tags, "citation_title")) or None,
        "journal": clean_text(_first(tags, "citation_journal_title")) or None,
        "publication_year": year,
        "publication_month": month,
        "publication_date": f"{year:04d}-{month:02d}" if year and month else None,
        "volume": str(volume).strip() if volume else None,
        "issue": str(issue).strip() if issue else None,
        "first_page": str(first_page).strip() if first_page else None,
        "last_page": str(last_page).strip() if last_page else None,
        "jel": _parse_jel(html_text),
        "abstract": abstract,
        "authors": [clean_text(value) for value in tags.get("citation_author", []) if clean_text(value)],
        "author_institutions": [
            clean_text(value)
            for value in tags.get("citation_author_institution", [])
            if clean_text(value)
        ],
        "source_url": f"{AEA_BASE}?id={doi}",
    }


def _safe_filename(doi: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", doi).strip("_") + ".html"


def _record_failure(doi: str, reason: str) -> None:
    FAILURES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with FAILURES_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"doi": doi, "reason": reason, "at": db.utcnow()}) + "\n")


def _request_html(
    client: httpx.Client,
    doi: str,
    *,
    max_attempts: int = 5,
) -> str | None:
    delay = 5.0
    last_error = "unknown error"
    for attempt in range(1, max_attempts + 1):
        try:
            response = client.get(AEA_BASE, params={"id": doi})
            if response.status_code == 404:
                log.info("AEA page not found for %s", doi)
                return None
            if response.status_code in {429, 500, 502, 503, 504}:
                wait = delay
                retry_after = response.headers.get("Retry-After")
                if retry_after and retry_after.replace(".", "", 1).isdigit():
                    wait = float(retry_after)
                log.warning(
                    "AEA HTTP %s for %s (attempt %s/%s); sleeping %.1fs",
                    response.status_code,
                    doi,
                    attempt,
                    max_attempts,
                    wait,
                )
                last_error = f"HTTP {response.status_code}"
                time.sleep(wait)
                delay = min(delay * 2, 120.0)
                continue
            response.raise_for_status()
            text = response.text
            if "citation_title" not in text and "citation_doi" not in text:
                last_error = "response did not contain AEA citation metadata"
                log.warning("AEA challenge/empty page for %s (attempt %s)", doi, attempt)
                time.sleep(delay)
                delay = min(delay * 2, 120.0)
                continue
            return text
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_error = str(exc)
            log.warning(
                "AEA request error for %s (attempt %s/%s): %s",
                doi,
                attempt,
                max_attempts,
                exc,
            )
            time.sleep(delay)
            delay = min(delay * 2, 120.0)
    raise RuntimeError(f"AEA request failed for {doi} after {max_attempts} attempts: {last_error}")


def parse_issue_list(html_text: str) -> list[dict[str, Any]]:
    """Parse the AEA all-issues page into a volume/issue -> cover-month map."""
    rows: list[dict[str, Any]] = []
    for issue_id, raw_label in _ISSUE_LINK_RE.findall(html_text):
        label = _plain(raw_label)
        match = _ISSUE_LABEL_RE.match(label)
        if not match:
            continue
        month = _MONTHS.get(match.group(1).lower())
        if not month:
            continue
        issue_text = re.sub(r"\s+", "", match.group(4))
        issue_parts = [part for part in issue_text.split("-") if part.isdigit()]
        # Combined issues (e.g. "No. 4-5") map each constituent issue number,
        # and the raw range, to the same cover month.
        for issue in [issue_text] + [part for part in issue_parts if part != issue_text]:
            rows.append(
                {
                    "issue_id": issue_id,
                    "label": label,
                    "year": int(match.group(2)),
                    "volume": str(int(match.group(3))),
                    "issue": issue,
                    "month": month,
                }
            )
    return rows


def fetch_issue_list(*, refresh: bool = False) -> str | None:
    ISSUE_LIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    if ISSUE_LIST_PATH.exists() and not refresh:
        return ISSUE_LIST_PATH.read_text(encoding="utf-8", errors="replace")
    delay = 5.0
    with httpx.Client(
        headers={
            "User-Agent": BROWSER_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
        timeout=30.0,
        follow_redirects=True,
    ) as client:
        for attempt in range(1, 4):
            try:
                response = client.get(ISSUES_URL)
                if response.status_code == 200 and "journal-issues" in response.text:
                    ISSUE_LIST_PATH.write_text(response.text, encoding="utf-8")
                    return response.text
                if response.status_code in {429, 500, 502, 503, 504}:
                    time.sleep(delay)
                    delay = min(delay * 2, 60.0)
                    continue
                response.raise_for_status()
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                log.warning("AEA issue-list request failed (attempt %s/3): %s", attempt, exc)
                time.sleep(delay)
                delay = min(delay * 2, 60.0)
    log.warning("AEA issue list unavailable; keeping existing issue months")
    return None


def apply_issue_calendar_rows(conn, rows: list[dict[str, Any]]) -> dict[str, int]:
    mapping = {
        (str(row["volume"]), normalize_issue(row["issue"])): (row["year"], row["month"])
        for row in rows
    }
    # Also accept a combined issue stored as "4-5" when the calendar only
    # lists the constituent numbers.
    for (volume, issue), value in list(mapping.items()):
        if "-" in issue:
            for part in issue.split("-"):
                mapping.setdefault((volume, part), value)
    article_rows = conn.execute(
        """
        SELECT paper_id, published_year, published_month, volume, issue, date_source
        FROM papers
        WHERE content_type='article' AND is_duplicate=0
        """
    ).fetchall()
    matched = 0
    updated = 0
    for row in article_rows:
        if not row["volume"] or not row["issue"]:
            continue
        issue_text = normalize_issue(row["issue"])
        target = mapping.get((str(row["volume"]).strip(), issue_text))
        if target is None and "-" in issue_text:
            for part in issue_text.split("-"):
                target = mapping.get((str(row["volume"]).strip(), part))
                if target is not None:
                    break
        if target is None:
            continue
        year, month = target
        if row["published_year"] is not None and int(row["published_year"]) != year:
            continue
        matched += 1
        if row["published_month"] == month and row["date_source"] in {
            "aea_issue_calendar",
            "aea_article_page",
        }:
            continue
        conn.execute(
            """
            UPDATE papers
            SET published_month=?,
                published_day=NULL,
                published_date=?,
                date_source='aea_issue_calendar',
                date_confidence='high'
            WHERE paper_id=?
            """,
            (month, f"{year:04d}-{month:02d}", row["paper_id"]),
        )
        updated += 1
    conn.commit()
    stats = {"available": len(rows), "matched": matched, "updated": updated}
    log.info("AEA issue calendar: %s", stats)
    return stats


def apply_issue_calendar(conn, *, refresh: bool = False) -> dict[str, int]:
    text = fetch_issue_list(refresh=refresh)
    if not text:
        return {"available": 0, "matched": 0, "updated": 0}
    rows = parse_issue_list(text)
    if not rows:
        return {"available": 0, "matched": 0, "updated": 0}
    return apply_issue_calendar_rows(conn, rows)


_THREAD_LOCAL = threading.local()
_WORKER_CLIENTS: list[httpx.Client] = []
_WORKER_CLIENTS_LOCK = threading.Lock()


def _worker_client() -> httpx.Client:
    client = getattr(_THREAD_LOCAL, "client", None)
    if client is None:
        client = httpx.Client(
            headers={
                "User-Agent": BROWSER_USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=30.0,
            follow_redirects=True,
        )
        _THREAD_LOCAL.client = client
        with _WORKER_CLIENTS_LOCK:
            _WORKER_CLIENTS.append(client)
    return client


def _close_worker_clients() -> None:
    with _WORKER_CLIENTS_LOCK:
        for client in _WORKER_CLIENTS:
            try:
                client.close()
            except Exception:
                pass
        _WORKER_CLIENTS.clear()


def _fetch_and_cache(doi: str, cache_path: Path, request_interval: float) -> str | None:
    client = _worker_client()
    try:
        text = _request_html(client, doi, max_attempts=2)
    except Exception:
        # A stale proxy connection can cause repeated timeouts. Drop it so the
        # next task opens a fresh connection.
        try:
            client.close()
        finally:
            del _THREAD_LOCAL.client
        raise
    if text is None:
        return None
    cache_path.write_text(text, encoding="utf-8")
    if request_interval:
        time.sleep(request_interval)
    return text


def harvest_aea(
    conn,
    *,
    limit: int | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    resume: bool = True,
    refresh: bool = False,
    request_interval: float = 0.5,
    workers: int = 1,
) -> dict[str, int]:
    """Fetch AEA article pages and store JEL, abstracts, and issue months."""
    PAGES_DIR.mkdir(parents=True, exist_ok=True)
    params = {
        "limit": limit,
        "year_from": year_from,
        "year_to": year_to,
        "resume": resume,
        "refresh": refresh,
        "workers": workers,
    }
    run_id = db.start_run(conn, "aea_article", params)
    stats = {
        "fetched": 0,
        "cached": 0,
        "parsed": 0,
        "dates_corrected": 0,
        "abstracts_filled": 0,
        "jel_papers": 0,
        "failures": 0,
    }
    rows = conn.execute(
        """
        SELECT paper_id, doi, published_year, published_month, published_day,
               volume, issue, page_first, page_last, abstract_available, date_source
        FROM papers
        WHERE content_type='article' AND is_duplicate=0 AND doi_synthetic=0
        ORDER BY paper_id
        """
    ).fetchall()
    selected = [
        row
        for row in rows
        if (year_from is None or (row["published_year"] or 0) >= year_from)
        and (year_to is None or (row["published_year"] or 9999) <= year_to)
    ]
    if limit is not None:
        selected = selected[:limit]

    processed = 0

    def process_row(row, text: str) -> None:
        nonlocal processed
        doi = row["doi"]
        try:
            parsed = parse_article_page(text, doi)
        except Exception as exc:
            stats["failures"] += 1
            _record_failure(doi, f"parse error: {exc}")
            log.warning("AEA parse failed for %s: %s", doi, exc)
            return
        if parsed["doi"] and parsed["doi"] != normalize_doi(doi):
            stats["failures"] += 1
            _record_failure(doi, f"DOI mismatch: {parsed['doi']}")
            log.warning("AEA DOI mismatch: expected %s, got %s", doi, parsed["doi"])
            return
        stats["parsed"] += 1
        date_corrected = _apply_parsed_article(conn, row, parsed)
        stats["dates_corrected"] += date_corrected
        parsed["previous_month"] = row["published_month"]
        parsed["date_corrected"] = bool(date_corrected)
        if parsed["abstract"] and not row["abstract_available"]:
            stats["abstracts_filled"] += 1
        if parsed["jel"]:
            stats["jel_papers"] += 1
        db.save_source_record(conn, "aea_article", normalize_doi(doi), run_id, parsed)
        processed += 1
        if processed % 50 == 0:
            conn.commit()
            log.info(
                "AEA %s/%s (fetched=%s cached=%s failures=%s dates=%s abstracts=%s)",
                processed,
                len(selected),
                stats["fetched"],
                stats["cached"],
                stats["failures"],
                stats["dates_corrected"],
                stats["abstracts_filled"],
            )

    try:
        pending = []
        for row in selected:
            cache_path = PAGES_DIR / _safe_filename(row["doi"])
            if resume and not refresh and cache_path.exists():
                stats["cached"] += 1
                process_row(row, cache_path.read_text(encoding="utf-8", errors="replace"))
            else:
                pending.append(row)

        log.info(
            "AEA start: %s selected, %s cached, %s to fetch, workers=%s",
            len(selected),
            stats["cached"],
            len(pending),
            workers,
        )

        if workers <= 1:
            with httpx.Client(
                headers={
                    "User-Agent": BROWSER_USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                },
                timeout=30.0,
                follow_redirects=True,
            ) as client:
                for row in pending:
                    doi = row["doi"]
                    try:
                        text = _request_html(client, doi, max_attempts=3)
                    except Exception as exc:
                        stats["failures"] += 1
                        _record_failure(doi, str(exc))
                        log.warning("AEA fetch failed for %s: %s", doi, exc)
                        continue
                    if text is None:
                        stats["failures"] += 1
                        _record_failure(doi, "not found")
                        continue
                    stats["fetched"] += 1
                    (PAGES_DIR / _safe_filename(doi)).write_text(text, encoding="utf-8")
                    if request_interval:
                        time.sleep(request_interval)
                    process_row(row, text)
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {
                    pool.submit(
                        _fetch_and_cache,
                        row["doi"],
                        PAGES_DIR / _safe_filename(row["doi"]),
                        request_interval,
                    ): row
                    for row in pending
                }
                for future in as_completed(futures):
                    row = futures[future]
                    doi = row["doi"]
                    try:
                        text = future.result()
                    except Exception as exc:
                        stats["failures"] += 1
                        _record_failure(doi, str(exc))
                        log.warning("AEA fetch failed for %s: %s", doi, exc)
                        continue
                    if text is None:
                        stats["failures"] += 1
                        _record_failure(doi, "not found")
                        continue
                    stats["fetched"] += 1
                    process_row(row, text)
            _close_worker_clients()
        conn.commit()
        db.finish_run(conn, run_id, "success", stats["parsed"])
        log.info("AEA harvest complete: %s", stats)
        return stats
    except Exception as exc:
        _close_worker_clients()
        conn.commit()
        db.finish_run(conn, run_id, "failed", stats["parsed"], str(exc))
        raise


def clean_truncated_aea_abstracts(conn) -> dict[str, int]:
    """Drop AEA abstracts that came from a truncated meta description.

    The article-page abstract section is preferred; meta descriptions can end
    in an ellipsis and are not presented as full abstracts.
    """
    rows = conn.execute(
        """
        SELECT paper_id, abstract, abstract_openalex
        FROM papers
        WHERE abstract_source='aea'
        """
    ).fetchall()
    cleared = 0
    replaced = 0
    for row in rows:
        if not _looks_truncated(row["abstract"] or ""):
            continue
        fallback = row["abstract_openalex"]
        if (
            fallback
            and not _looks_truncated(fallback)
            and "Published in volume" not in fallback
        ):
            conn.execute(
                """
                UPDATE papers
                SET abstract=?, abstract_source='openalex', abstract_available=1
                WHERE paper_id=?
                """,
                (fallback, row["paper_id"]),
            )
            replaced += 1
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
    stats = {"cleared": cleared, "replaced_from_openalex": replaced}
    log.info("AEA truncated-abstract cleanup: %s", stats)
    return stats


def _apply_parsed_article(conn, row, parsed: dict[str, Any]) -> int:
    """Apply one parsed page. Returns 1 if the issue month changed."""
    paper_id = int(row["paper_id"])
    updates: dict[str, Any] = {
        "paper_id": paper_id,
        "aea_url": parsed["source_url"],
        "aea_fetched_at": db.utcnow(),
    }
    date_corrected = 0
    current_year = row["published_year"]
    parsed_year = parsed["publication_year"]
    parsed_month = parsed["publication_month"]
    # A combined issue such as "4-5" has one cover month in the AEA issue
    # calendar. An individual article page may label it by the second month;
    # keep the calendar's issue month rather than splitting the issue.
    preserve_issue_month = (
        row["date_source"] == "aea_issue_calendar" and "-" in str(row["issue"] or "")
    )
    if (
        parsed_year
        and parsed_month
        and not preserve_issue_month
        and (current_year is None or parsed_year == current_year)
    ):
        if row["published_month"] != parsed_month:
            date_corrected = 1
        updates.update(
            published_month=parsed_month,
            published_date=parsed["publication_date"],
            date_source="aea_article_page",
            date_confidence="high",
        )
    conn.execute(
        """
        UPDATE papers
        SET aea_url=:aea_url,
            aea_fetched_at=:aea_fetched_at,
            published_month=COALESCE(:published_month, published_month),
            published_day=CASE WHEN :date_source IS NOT NULL THEN NULL ELSE published_day END,
            published_date=COALESCE(:published_date, published_date),
            date_source=COALESCE(:date_source, date_source),
            date_confidence=COALESCE(:date_confidence, date_confidence)
        WHERE paper_id=:paper_id
        """,
        {
            **updates,
            "published_month": updates.get("published_month"),
            "published_date": updates.get("published_date"),
            "date_source": updates.get("date_source"),
            "date_confidence": updates.get("date_confidence"),
        },
    )

    if parsed["volume"] and not row["volume"]:
        conn.execute("UPDATE papers SET volume=? WHERE paper_id=?", (parsed["volume"], paper_id))
    if parsed["issue"] and not row["issue"]:
        conn.execute("UPDATE papers SET issue=? WHERE paper_id=?", (parsed["issue"], paper_id))
    if parsed["first_page"] and not row["page_first"]:
        conn.execute(
            "UPDATE papers SET page_first=? WHERE paper_id=?", (parsed["first_page"], paper_id)
        )
    if parsed["last_page"] and not row["page_last"]:
        conn.execute(
            "UPDATE papers SET page_last=? WHERE paper_id=?", (parsed["last_page"], paper_id)
        )

    if parsed["abstract"]:
        conn.execute(
            "UPDATE papers SET abstract_aea=? WHERE paper_id=?",
            (parsed["abstract"], paper_id),
        )
        if not row["abstract_available"]:
            conn.execute(
                """
                UPDATE papers
                SET abstract=?, abstract_available=1, abstract_source='aea'
                WHERE paper_id=?
                """,
                (parsed["abstract"], paper_id),
            )

    conn.execute("DELETE FROM paper_topics WHERE paper_id=? AND scheme='jel'", (paper_id,))
    for entry in parsed["jel"]:
        conn.execute(
            """
            INSERT OR IGNORE INTO paper_topics
                (paper_id, scheme, code, label, score, is_primary)
            VALUES (?, 'jel', ?, ?, NULL, 0)
            """,
            (paper_id, entry["code"], entry["label"]),
        )
    return date_corrected


# AER's five-issue spring-to-winter calendar was stable in the 2000s. Issue
# metadata from Crossref confirms it for 2002-2007; this table is only a
# fallback for 2008-2009, where Crossref issue records are absent. AEA article
# pages override it with high-confidence dates.
AER_ISSUE_MONTHS_2008_2009 = {1: 3, 2: 5, 3: 6, 4: 9, 5: 12}


def fix_issue_months(conn) -> dict[str, int]:
    """Correct Crossref's one-month-early issue dates.

    The hierarchy is:
    1. Crossref issue-metadata month (2002-2007), high confidence.
    2. AER's five-issue calendar for 2008-2009, medium confidence.
    AEA article pages, when available, override both with high confidence.
    """
    issue_rows = conn.execute(
        """
        SELECT published_year, volume, issue, published_month
        FROM papers
        WHERE content_type='issue_metadata' AND published_month IS NOT NULL
        """
    ).fetchall()
    issue_map = {
        (int(row["published_year"]), str(row["volume"]), int(row["issue"])): int(
            row["published_month"]
        )
        for row in issue_rows
    }

    article_rows = conn.execute(
        """
        SELECT paper_id, published_year, volume, issue, published_month
        FROM papers
        WHERE content_type='article' AND is_duplicate=0
          AND published_year BETWEEN 2002 AND 2009
        """
    ).fetchall()

    corrected_issue_metadata = 0
    corrected_calendar = 0
    for row in article_rows:
        year = int(row["published_year"])
        try:
            issue = int(row["issue"])
        except (TypeError, ValueError):
            continue
        target = None
        source = None
        confidence = None
        if year <= 2007:
            target = issue_map.get((year, str(row["volume"]), issue))
            source = "crossref_issue_metadata"
            confidence = "high"
        if target is None and year in {2008, 2009}:
            target = AER_ISSUE_MONTHS_2008_2009.get(issue)
            source = "aer_issue_calendar"
            confidence = "medium"
        if target is None or row["published_month"] == target:
            continue
        conn.execute(
            """
            UPDATE papers
            SET published_month=?,
                published_day=NULL,
                published_date=?,
                date_source=?,
                date_confidence=?
            WHERE paper_id=?
            """,
            (
                target,
                f"{year:04d}-{target:02d}",
                source,
                confidence,
                row["paper_id"],
            ),
        )
        if source == "crossref_issue_metadata":
            corrected_issue_metadata += 1
        else:
            corrected_calendar += 1
    conn.commit()
    stats = {
        "corrected_issue_metadata": corrected_issue_metadata,
        "corrected_calendar": corrected_calendar,
    }
    log.info("Issue-month corrections: %s", stats)
    return stats

from __future__ import annotations

import hashlib
import json
import logging
import re
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
from lxml import html as lxml_html

from . import db
from .career import classify_role
from .config import MAILTO, RAW_DIR
from .normalize import clean_text, normalize_name_part, normalize_orcid

log = logging.getLogger(__name__)

RAW_CV_DIR = RAW_DIR / "cvs"
HOMEPAGES_DIR = RAW_CV_DIR / "homepages"
DOCUMENTS_DIR = RAW_CV_DIR / "documents"
TEXTS_DIR = RAW_CV_DIR / "text"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    f"(KHTML, like Gecko) Chrome/126.0 Safari/537.36 EconPubDatabase/0.4 "
    f"(mailto:{MAILTO})"
)
MAX_BYTES = 30_000_000

_THREAD_LOCAL = threading.local()
_CLIENTS: list[httpx.Client] = []
_CLIENT_LOCK = threading.Lock()

_EDUCATION_HEADER = re.compile(
    r"^(education|academic education|degrees|earned degrees|educational background|education and training|academic training)(?=\s|:|$|[A-Z])",
    re.IGNORECASE,
)
_EMPLOYMENT_HEADER = re.compile(
    r"^(academic appointments|academic positions|professional appointments|"
    r"professional experience|employment|positions held|work experience|"
    r"appointments|past appointments|current position|experience|visiting appointments|affiliations)(?=\s|:|$|[A-Z])",
    re.IGNORECASE,
)
_OTHER_HEADER = re.compile(
    r"^(research(?!\s+(?:fellow|scientist))|publications|working papers|"
    r"selected publications|teaching|awards|honors|honorary degrees|grants|service|"
    r"professional service|referee|conferences|seminars|fields|fields of interest|"
    r"invited|presentations|media|other)\b",
    re.IGNORECASE,
)
_DEGREE_RE = re.compile(
    r"\b(ph\.?\s*d\.?|doctorate|doctor of philosophy|master(?:'s)?|m\.?\s*a\.?|"
    r"m\.?\s*sc\.?|bachelor(?:'s)?|b\.?\s*a\.?|b\.?\s*sc\.?)\b",
    re.IGNORECASE,
)
_RANGE_RE = re.compile(
    r"((?:19|20)\d{2})\s*[-–—]{1,2}\s*(?:[A-Z][a-z]+\s+)?"
    r"((?:19|20)\d{2}|present|current|now|\d{2})?",
    re.IGNORECASE,
)
_SINGLE_YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\b")
_SKIP_LINE = re.compile(
    r"\b(journal|vol\.|pp\.|doi|working paper|ssrn|nber working|http|"
    r"editor|referee|seminar|conference|award|grant|university press|"
    r"course|workshop|summer school)\b",
    re.IGNORECASE,
)


def _hash_bytes(content: bytes) -> str:
    return hashlib.sha1(content).hexdigest()


def _url_digest(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()


def _load_cached_page(url: str) -> tuple[bytes, str | None, str] | None:
    digest = _url_digest(url)
    path = HOMEPAGES_DIR / f"{digest}.html"
    meta_path = HOMEPAGES_DIR / f"{digest}.json"
    if not path.exists():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        return path.read_bytes(), meta.get("content_type"), meta.get("final_url") or url
    except (OSError, ValueError):
        return None


def _store_cached_page(url: str, content: bytes, content_type: str | None, final_url: str) -> str:
    digest = _url_digest(url)
    HOMEPAGES_DIR.mkdir(parents=True, exist_ok=True)
    path = HOMEPAGES_DIR / f"{digest}.html"
    path.write_bytes(content)
    (HOMEPAGES_DIR / f"{digest}.json").write_text(
        json.dumps(
            {"content_type": content_type, "final_url": final_url, "source_url": url},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return digest


def _normalize_document_url(url: str) -> str:
    """Turn common file-landing URLs into direct downloads."""
    lower = url.lower()
    if "dropbox.com" in lower:
        if "dl=0" in url:
            return url.replace("dl=0", "dl=1")
        if "dl=1" not in url:
            return url + ("&" if "?" in url else "?") + "dl=1"
    if "drive.google.com/file/d/" in lower:
        match = re.search(r"/file/d/([^/]+)", url)
        if match:
            return f"https://drive.google.com/uc?export=download&id={match.group(1)}"
    if "google.com/url" in lower:
        from urllib.parse import parse_qs

        query = parse_qs(urlsplit(url).query)
        target = (query.get("q") or [""])[0]
        if target.startswith(("http://", "https://")):
            return target
    return url


def _safe_url(url: str) -> bool:
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return False
    host = parts.hostname.lower()
    if host in {"localhost", "127.0.0.1", "::1"}:
        return False
    if host.startswith(("10.", "192.168.", "169.254.")):
        return False
    if host.startswith("172."):
        try:
            second = int(host.split(".")[1])
            if 16 <= second <= 31:
                return False
        except (IndexError, ValueError):
            return False
    return True


def _client() -> httpx.Client:
    client = getattr(_THREAD_LOCAL, "client", None)
    if client is None:
        client = httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/pdf,*/*"},
            timeout=httpx.Timeout(10.0, connect=5.0),
            follow_redirects=True,
        )
        _THREAD_LOCAL.client = client
        with _CLIENT_LOCK:
            _CLIENTS.append(client)
    return client


def _close_clients() -> None:
    with _CLIENT_LOCK:
        for client in _CLIENTS:
            try:
                client.close()
            except Exception:
                pass
        _CLIENTS.clear()


def _fetch(url: str) -> tuple[bytes | None, str | None, str | None, str | None]:
    if not _safe_url(url):
        return None, None, None, "unsafe_url"
    delay = 1.5
    last_error = "unknown error"
    for attempt in range(1, 3):
        try:
            response = _client().get(url)
            if response.status_code == 200:
                content = response.content
                if len(content) > MAX_BYTES:
                    return None, None, None, "too_large"
                return content, response.headers.get("content-type"), str(response.url), None
            # 403s and 404s are usually permanent; do not hammer the host.
            if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                time.sleep(delay)
                delay = min(delay * 2, 20.0)
                last_error = f"http_{response.status_code}"
                continue
            return None, None, None, f"http_{response.status_code}"
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_error = str(exc)
            if attempt < 2:
                time.sleep(delay)
                delay = min(delay * 2, 20.0)
                continue
    return None, None, None, last_error


def _looks_like_cv_text(text: str) -> bool:
    lower = text.lower()
    signals = sum(
        1
        for term in (
            "education",
            "employment",
            "academic appointments",
            "professional experience",
            "ph.d",
            "phd",
        )
        if term in lower
    )
    return signals >= 2


def _cv_link_candidates(links: list[tuple[str, str]]) -> list[tuple[int, str, str]]:
    candidates: list[tuple[int, str, str]] = []
    for label, href in links:
        low = f"{label} {href}".lower()
        score = 0
        if any(term in low for term in ("curriculum vitae", " cv", "cv ", "vita", "resume")):
            score += 5
        if href.lower().endswith(".pdf"):
            score += 3
        if "download" in low:
            score += 1
        if any(
            term in low
            for term in (
                "publication",
                "research",
                "teaching",
                "twitter",
                "linkedin",
                "scholar.google",
                "mailto",
            )
        ):
            score -= 5
        if score >= 4:
            candidates.append((score, label, href))
    candidates.sort(reverse=True, key=lambda item: item[0])
    return candidates


def _fetch_page(url: str) -> tuple[bytes | None, str | None, str | None, str | None]:
    """Fetch a page, retrying an old HTTP URL over HTTPS once."""
    result = _fetch(url)
    if result[3] and url.lower().startswith("http://"):
        secure = "https://" + url[7:]
        secure_result = _fetch(secure)
        if secure_result[3] is None:
            return secure_result
    return result


def _html_text_and_links(content: bytes, base_url: str) -> tuple[str, list[tuple[str, str]]]:
    try:
        doc = lxml_html.fromstring(content)
        for bad in doc.xpath("//script|//style|//noscript"):
            bad.drop_tree()
        text = doc.text_content()
        links = []
        for anchor in doc.xpath("//a[@href]"):
            href = (anchor.get("href") or "").strip()
            label = clean_text(anchor.text_content())
            if href:
                links.append((label, urljoin(base_url, href)))
        return text, links
    except Exception:
        text = re.sub(r"<[^>]+>", " ", content.decode("utf-8", errors="replace"))
        return text, []


def _pdf_text(path: Path) -> str:
    try:
        result = subprocess.run(
            ["pdftotext", "-layout", str(path), "-"],
            capture_output=True,
            timeout=90,
        )
        if result.returncode == 0:
            return result.stdout.decode("utf-8", errors="replace")
    except Exception:
        pass
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception:
        return ""


def _institution_names(conn) -> list[str]:
    return [
        row["display_name"]
        for row in conn.execute(
            "SELECT DISTINCT display_name FROM institutions WHERE display_name IS NOT NULL"
        )
        if row["display_name"]
    ]


_GENERIC_INSTITUTION_NAMES = {
    "university",
    "college",
    "institute",
    "school",
    "bank",
    "bureau",
    "center",
    "centre",
    "foundation",
    "agency",
    "ministry",
    "board",
    "council",
    "university of",
    "department of",
    "school of",
    "college of",
    "institute of",
}


def _match_institution(line: str, names: list[str]) -> str | None:
    lower = line.lower()
    matches = [
        name
        for name in names
        if name.lower() in lower and name.strip().lower() not in _GENERIC_INSTITUTION_NAMES
    ]
    if matches:
        return max(matches, key=len)
    # Prefer a named entity immediately before an institution suffix.
    named = re.search(
        r"\b(?:at|,)\s+([A-Z][A-Za-z&.'-]+(?:\s+[A-Z][A-Za-z&.'-]+){1,5}\s+"
        r"(?:University|College|Institute|School|Bank|Bureau|Center|Centre|"
        r"Foundation|Agency|Ministry|Board|Council))\b",
        line,
    )
    if named:
        return clean_text(named.group(1))[:200]
    university_of = re.search(
        r"(?:\bat\s+|[,;]\s*)(University of\s+[A-Z][A-Za-z&.'-]+(?:\s+[A-Z][A-Za-z&.'-]+){0,3})",
        line,
    )
    if university_of:
        return clean_text(university_of.group(1))[:200]
    # Fallback for institution names not in the OpenAlex entity table.
    cleaned = _RANGE_RE.sub("", line)
    cleaned = _SINGLE_YEAR_RE.sub("", cleaned)
    parts = [part.strip(" .;") for part in cleaned.split(",") if part.strip(" .;")]
    for part in reversed(parts):
        if part.lower() in _GENERIC_INSTITUTION_NAMES:
            continue
        if re.search(
            r"\b(?:assistant|associate|professor|lecturer|instructor|director|"
            r"department|faculty|postdoctoral|fellow)\b",
            part,
            re.IGNORECASE,
        ):
            continue
        if re.search(
            r"\b(university|institute|bank|bureau|center|centre|school|college|"
            r"foundation|agency|ministry|board|council)\b",
            part,
            re.IGNORECASE,
        ):
            return part[:200]
    return None


def _extract_years(line: str) -> tuple[int | None, int | None, int]:
    match = _RANGE_RE.search(line)
    if match:
        start = int(match.group(1))
        end_text = (match.group(2) or "").lower()
        if end_text in {"present", "current", "now"} or not end_text:
            return start, None, 1
        if len(end_text) == 2:
            end = (start // 100) * 100 + int(end_text)
            if end < start:
                end += 100
            return start, end, 0
        end = int(end_text)
        if end < start or end > 2026:
            return start, start, 0
        return start, end, 0
    match = _SINGLE_YEAR_RE.search(line)
    if match:
        year = int(match.group(1))
        return year, year, 0
    return None, None, 0


def extract_cv_events(text: str, institution_names: list[str]) -> list[dict[str, Any]]:
    """Conservative rule-based extraction from CV text.

    Only lines inside an Education or Employment section are parsed. A line
    needs either a degree keyword or a recognized role title; institution and
    dates are optional but increase confidence.
    """
    text = text.replace("�", "-").replace("–", "-").replace("—", "-")
    # Normalize month/year ranges such as 05/2014-07/2017 before year parsing.
    text = re.sub(
        r"\b\d{1,2}/((?:19|20)\d{2})\s*-\s*\d{1,2}/((?:19|20)\d{2})\b",
        r"\1-\2",
        text,
    )
    text = re.sub(r"\b\d{1,2}/((?:19|20)\d{2})\b", r"\1", text)
    # Some CMS pages render a whole CV as one run of text. Add line breaks
    # before section headers and explicit role titles.
    text = re.sub(
        r"(?=(?:Education|Employment|Publications|Teaching|Research|Awards|"
        r"Service|Fields of Interest|Earned Degrees|Past Appointments))",
        "\n",
        text,
    )
    text = re.sub(
        r"(?i)(?=(?:education|earned degrees|academic appointments|professional appointments|"
        r"past appointments|employment|publications|teaching|research interests|research papers|"
        r"working papers|awards|service|fields of interest)\b)",
        "\n",
        text,
    )
    text = re.sub(
        r"(?i)(?=(?:assistant|associate|full)\s+professor\b|"
        r"(?:senior\s+)?lecturer\b|research fellow\b|postdoctoral\b|economist\b)",
        "\n",
        text,
    )
    text = re.sub(
        r"(?=(?:Ph\.?\s*D\.?|M\.?\s*A\.?|M\.?\s*Sc\.?|B\.?\s*A\.?|B\.?\s*Sc\.?))",
        "\n",
        text,
    )
    # Join date ranges wrapped across lines ("2022-" / "2025").
    lines: list[str] = []
    raw_lines = text.splitlines()
    index = 0
    while index < len(raw_lines):
        line = raw_lines[index]
        while line.rstrip().endswith("-") and index + 1 < len(raw_lines):
            next_line = raw_lines[index + 1].strip()
            if re.match(r"^(?:19|20)\d{2}\b|^(?:present|current|now)\b", next_line, re.I):
                line = line.rstrip() + next_line
                index += 1
            else:
                break
        lines.append(line)
        index += 1
    section: str | None = None
    events: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for raw_line in lines:
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line or len(line) < 5:
            continue
        education_header = _EDUCATION_HEADER.match(line)
        if education_header:
            section = "education"
            line = line[education_header.end() :].strip(" :-")
            if not line:
                continue
        else:
            employment_header = _EMPLOYMENT_HEADER.match(line)
            if employment_header:
                section = "employment"
                line = line[employment_header.end() :].strip(" :-")
                if not line:
                    continue
            elif _OTHER_HEADER.match(line):
                section = None
                continue
        if section is None:
            continue
        if _SKIP_LINE.search(line):
            continue
        start_year, end_year, is_current = _extract_years(line)
        institution = _match_institution(line, institution_names)
        if section == "education":
            degree = _DEGREE_RE.search(line)
            if not degree:
                continue
            title = clean_text(line)[:240]
            confidence = "high" if institution and start_year else (
                "medium" if start_year or institution else "low"
            )
            key = ("education", title.lower(), institution, start_year, end_year)
            if key in seen:
                continue
            seen.add(key)
            events.append(
                {
                    "event_type": "education",
                    "title": title,
                    "institution": institution,
                    "start_year": start_year,
                    "end_year": end_year,
                    "is_current": 0,
                    "confidence": confidence,
                    "source_snippet": line[:500],
                }
            )
            continue
        stage, role_confidence = classify_role(line)
        if stage is None:
            continue
        # Keep a short role phrase rather than the entire line.
        title = re.split(r"\s{2,}|,|\b(?:19|20)\d{2}\b", line, maxsplit=1)[0]
        title = clean_text(title)[:160] or line[:160]
        confidence = "high" if institution and start_year and (
            is_current or (end_year is not None and end_year != start_year)
        ) else ("medium" if institution or start_year else "low")
        key = ("employment", title.lower(), institution, start_year, end_year)
        if key in seen:
            continue
        seen.add(key)
        events.append(
            {
                "event_type": "employment",
                "title": title,
                "institution": institution,
                "start_year": start_year,
                "end_year": end_year,
                "is_current": is_current,
                "confidence": confidence,
                "source_snippet": line[:500],
            }
        )
    return events


def _upsert_institution(conn, name: str | None) -> int | None:
    if not name:
        return None
    normalized = normalize_name_part(name)
    if not normalized:
        return None
    row = conn.execute(
        "SELECT institution_id FROM institutions WHERE normalized_name=?", (normalized,)
    ).fetchone()
    if row:
        return int(row["institution_id"])
    cursor = conn.execute(
        """
        INSERT INTO institutions (display_name, normalized_name, created_at)
        VALUES (?, ?, ?)
        """,
        (name, normalized, db.utcnow()),
    )
    return int(cursor.lastrowid)


def _event_key(source_url: str, event: dict[str, Any]) -> str:
    payload = "|".join(
        str(event.get(key) or "")
        for key in ("event_type", "title", "institution", "start_year", "end_year")
    )
    digest = hashlib.sha1(f"{source_url}|{payload}".encode("utf-8")).hexdigest()
    return f"cv:{digest}"


def upsert_cv_events(conn, author_id: int, source_url: str, events: list[dict[str, Any]]) -> int:
    # Reparse is authoritative for this CV: drop stale events first so a
    # corrected date range does not leave an old row behind.
    conn.execute(
        "DELETE FROM career_events WHERE source_type='cv' AND author_id=? AND source_url=?",
        (author_id, source_url),
    )
    count = 0
    for event in events:
        institution_id = _upsert_institution(conn, event.get("institution"))
        conn.execute(
            """
            INSERT INTO career_events
                (author_id, event_type, title, institution, institution_id,
                 start_year, end_year, is_current, source_url, source_type,
                 source_snippet, event_key, confidence, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'cv', ?, ?, ?, ?)
            ON CONFLICT(event_key) DO UPDATE SET
                author_id=excluded.author_id,
                event_type=excluded.event_type,
                title=excluded.title,
                institution=excluded.institution,
                institution_id=excluded.institution_id,
                start_year=excluded.start_year,
                end_year=excluded.end_year,
                is_current=excluded.is_current,
                source_url=excluded.source_url,
                source_type='cv',
                source_snippet=excluded.source_snippet,
                confidence=excluded.confidence
            """,
            (
                author_id,
                event["event_type"],
                event["title"],
                event.get("institution"),
                institution_id,
                event.get("start_year"),
                event.get("end_year"),
                event.get("is_current") or 0,
                source_url,
                event.get("source_snippet"),
                _event_key(source_url, event),
                event.get("confidence", "low"),
                db.utcnow(),
            ),
        )
        count += 1
    return count


def collect_orcid_urls(conn) -> dict[str, int]:
    """Seed CV discovery with public researcher URLs from ORCID records."""
    rows = conn.execute(
        "SELECT source_key, payload_json FROM source_records WHERE source='orcid_record'"
    ).fetchall()
    inserted = 0
    skipped = 0
    for row in rows:
        payload = json.loads(row["payload_json"])
        orcid = normalize_orcid(row["source_key"])
        author = conn.execute(
            "SELECT author_id FROM authors WHERE orcid=? ORDER BY author_id LIMIT 1",
            (orcid,),
        ).fetchone()
        if not author:
            author = conn.execute(
                """
                SELECT author_id FROM authorships
                WHERE openalex_orcid=? AND author_id IS NOT NULL
                ORDER BY authorship_id LIMIT 1
                """,
                (orcid,),
            ).fetchone()
        if not author:
            continue
        urls = ((payload.get("person") or {}).get("researcher-urls") or {}).get(
            "researcher-url"
        ) or []
        for item in urls:
            url = ((item.get("url") or {}).get("value")) or ""
            label = clean_text(item.get("url-name") or "")
            if not url or not _safe_url(url):
                skipped += 1
                continue
            lower = url.lower()
            if any(
                host in lower
                for host in (
                    "scholar.google",
                    "twitter.com",
                    "x.com",
                    "linkedin.com",
                    "facebook.com",
                    "researchgate.net",
                    "ssrn.com",
                    "youtube.com",
                    "bsky.app",
                    "mendeley.com",
                )
            ):
                skipped += 1
                continue
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO author_cv_sources
                    (author_id, url, source_type, status, notes, created_at)
                VALUES (?, ?, 'orcid_researcher_url', 'candidate', ?, ?)
                """,
                (author["author_id"], url, label or None, db.utcnow()),
            )
            if cursor.rowcount:
                inserted += 1
    conn.commit()
    stats = {"records": len(rows), "inserted": inserted, "skipped": skipped}
    log.info("CV seed URLs: %s", stats)
    return stats


def discover_cv_links(
    conn,
    *,
    limit: int | None = None,
    workers: int = 4,
    refresh: bool = False,
    retry_failed: bool = False,
) -> dict[str, int]:
    if retry_failed:
        conn.execute(
            """
            UPDATE author_cv_sources
            SET status='candidate', notes='retry requested'
            WHERE status='failed' AND source_type='orcid_researcher_url'
            """
        )
        conn.commit()
    rows = conn.execute(
        """
        SELECT source_id, author_id, url, notes
        FROM author_cv_sources
        WHERE status='candidate' AND source_type='orcid_researcher_url'
        ORDER BY source_id
        """
    ).fetchall()
    if limit is not None:
        rows = rows[:limit]
    stats = {
        "pages": len(rows),
        "cached": 0,
        "fetched": 0,
        "documents": 0,
        "links": 0,
        "failed": 0,
    }

    def fetch_row(row):
        if not refresh:
            cached = _load_cached_page(row["url"])
            if cached is not None:
                content, content_type, final_url = cached
                return row, content, content_type, final_url, "cached", None
        content, content_type, final_url, error = _fetch_page(row["url"])
        if error or content is None:
            return row, None, None, None, "failed", error or "fetch_failed"
        _store_cached_page(row["url"], content, content_type, final_url or row["url"])
        return row, content, content_type, final_url or row["url"], "fetched", None

    try:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            futures = {pool.submit(fetch_row, row): row for row in rows}
            for index, future in enumerate(as_completed(futures), start=1):
                try:
                    row, content, content_type, final_url, status, error = future.result()
                except Exception as exc:
                    row = futures[future]
                    content = None
                    content_type = None
                    final_url = None
                    status = "failed"
                    error = f"worker_error: {exc}"
                if status == "failed" or content is None:
                    stats["failed"] += 1
                    conn.execute(
                        "UPDATE author_cv_sources SET status='failed', notes=? WHERE source_id=?",
                        (error or "fetch_failed", row["source_id"]),
                    )
                else:
                    stats[status] += 1
                    digest = _url_digest(row["url"])
                    is_pdf = "application/pdf" in (content_type or "") or row["url"].lower().endswith(
                        ".pdf"
                    )
                    if is_pdf:
                        path = DOCUMENTS_DIR / f"{digest}.pdf"
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(content)
                        text = _pdf_text(path)[:300_000]
                        TEXTS_DIR.mkdir(parents=True, exist_ok=True)
                        (TEXTS_DIR / f"{digest}.txt").write_text(text, encoding="utf-8")
                        conn.execute(
                            """
                            UPDATE author_cv_sources
                            SET status='fetched', content_hash=?, local_path=?, fetched_at=?,
                                source_type='cv_document', notes=?
                            WHERE source_id=?
                            """,
                            (
                                digest,
                                str(path),
                                db.utcnow(),
                                f"{len(text)} chars; direct PDF",
                                row["source_id"],
                            ),
                        )
                        stats["documents"] += 1
                    else:
                        text, links = _html_text_and_links(content, final_url or row["url"])
                        candidates: list[tuple[int, str, str]] = []
                        for label, href in links:
                            low = f"{label} {href}".lower()
                            score = 0
                            if any(
                                term in low
                                for term in ("curriculum vitae", " cv", "cv ", "vita", "resume")
                            ):
                                score += 5
                            if href.lower().endswith(".pdf"):
                                score += 3
                            if "download" in low:
                                score += 1
                            if any(
                                term in low
                                for term in (
                                    "publication",
                                    "research",
                                    "teaching",
                                    "twitter",
                                    "linkedin",
                                    "scholar.google",
                                    "mailto",
                                )
                            ):
                                score -= 5
                            if score >= 4:
                                candidates.append((score, label, href))
                        candidates.sort(reverse=True, key=lambda item: item[0])
                        seen: set[str] = set()
                        for _score, label, href in candidates[:3]:
                            if href in seen:
                                continue
                            seen.add(href)
                            conn.execute(
                                """
                                INSERT OR IGNORE INTO author_cv_sources
                                    (author_id, url, source_type, status, notes, created_at)
                                VALUES (?, ?, 'cv_link', 'candidate', ?, ?)
                                """,
                                (row["author_id"], href, label or None, db.utcnow()),
                            )
                            stats["links"] += 1
                        conn.execute(
                            """
                            UPDATE author_cv_sources
                            SET status='homepage_fetched', content_hash=?, local_path=?,
                                fetched_at=?, notes=?
                            WHERE source_id=?
                            """,
                            (
                                digest,
                                str(HOMEPAGES_DIR / f"{digest}.html"),
                                db.utcnow(),
                                f"{len(candidates)} cv-like links",
                                row["source_id"],
                            ),
                        )
                if index % 25 == 0:
                    conn.commit()
                    log.info(
                        "CV discovery %s/%s (cached=%s fetched=%s links=%s failed=%s)",
                        index,
                        len(rows),
                        stats["cached"],
                        stats["fetched"],
                        stats["links"],
                        stats["failed"],
                    )
        conn.commit()
    finally:
        _close_clients()
    log.info("CV link discovery: %s", stats)
    return stats

def fetch_cv_documents(
    conn,
    *,
    limit: int | None = None,
    workers: int = 4,
) -> dict[str, int]:
    rows = conn.execute(
        """
        SELECT source_id, author_id, url
        FROM author_cv_sources
        WHERE status='candidate' AND source_type IN ('cv_link','cv_document')
        ORDER BY source_id
        """
    ).fetchall()
    if limit is not None:
        rows = rows[:limit]
    stats = {"documents": len(rows), "fetched": 0, "failed": 0, "empty": 0}

    def fetch_task(row):
        url = _normalize_document_url(row["url"])
        content, content_type, final_url, error = _fetch_page(url)
        if error or content is None:
            return row, None, None, None, False, error or "fetch_failed"
        is_pdf = "application/pdf" in (content_type or "") or url.lower().endswith(".pdf")
        if is_pdf and content.lstrip()[:64].lower().startswith((b"<!doctype", b"<html")):
            is_pdf = False
        if not is_pdf:
            text_preview, links = _html_text_and_links(content, final_url or url)
            # Landing pages often contain only a "Download CV" link, even when
            # the visible page is long. Follow the strongest CV link when the
            # text does not look like a CV.
            if not _looks_like_cv_text(text_preview):
                candidates = _cv_link_candidates(links)
                follow = candidates[0][2] if candidates else None
                if follow and follow != url:
                    content2, content_type2, final_url2, error2 = _fetch_page(
                        _normalize_document_url(follow)
                    )
                    if content2 is not None and not error2:
                        content = content2
                        content_type = content_type2
                        final_url = final_url2
                        is_pdf = "application/pdf" in (content_type2 or "") or follow.lower().endswith(
                            ".pdf"
                        )
        return row, content, content_type, final_url or url, is_pdf, None

    try:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            futures = {pool.submit(fetch_task, row): row for row in rows}
            for index, future in enumerate(as_completed(futures), start=1):
                try:
                    row, content, _content_type, final_url, is_pdf, error = future.result()
                except Exception as exc:
                    row = futures[future]
                    content = None
                    final_url = None
                    is_pdf = False
                    error = f"worker_error: {exc}"
                if error or content is None:
                    stats["failed"] += 1
                    conn.execute(
                        "UPDATE author_cv_sources SET status='failed', notes=? WHERE source_id=?",
                        (error or "fetch_failed", row["source_id"]),
                    )
                    continue
                digest = _hash_bytes(content)
                suffix = "pdf" if is_pdf else "html"
                path = DOCUMENTS_DIR / f"{digest}.{suffix}"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
                if is_pdf:
                    text = _pdf_text(path)
                else:
                    text, _links = _html_text_and_links(content, final_url or row["url"])
                text = text[:300_000]
                TEXTS_DIR.mkdir(parents=True, exist_ok=True)
                (TEXTS_DIR / f"{digest}.txt").write_text(text, encoding="utf-8")
                status = "fetched" if text.strip() else "empty"
                if status == "empty":
                    stats["empty"] += 1
                else:
                    stats["fetched"] += 1
                conn.execute(
                    """
                    UPDATE author_cv_sources
                    SET status=?, content_hash=?, local_path=?, fetched_at=?,
                        notes=?
                    WHERE source_id=?
                    """,
                    (
                        status,
                        digest,
                        str(path),
                        db.utcnow(),
                        f"{len(text)} chars; {final_url or row['url']}",
                        row["source_id"],
                    ),
                )
                if index % 25 == 0:
                    conn.commit()
                    log.info(
                        "CV document fetch %s/%s (fetched=%s failed=%s empty=%s)",
                        index,
                        len(rows),
                        stats["fetched"],
                        stats["failed"],
                        stats["empty"],
                    )
        conn.commit()
    finally:
        _close_clients()
    log.info("CV document fetch: %s", stats)
    return stats

def queue_landing_links(conn, *, limit: int | None = None) -> dict[str, int]:
    """Queue the strongest CV link from an HTML page that parsed to zero events."""
    rows = conn.execute(
        """
        SELECT source_id, author_id, url, local_path
        FROM author_cv_sources
        WHERE status='parsed' AND notes='0 events'
          AND local_path LIKE '%.html'
        ORDER BY source_id
        """
    ).fetchall()
    if limit is not None:
        rows = rows[:limit]
    stats = {"pages": len(rows), "inserted": 0, "skipped": 0}
    for row in rows:
        path = Path(row["local_path"]) if row["local_path"] else None
        if not path or not path.exists():
            stats["skipped"] += 1
            continue
        try:
            text, links = _html_text_and_links(path.read_bytes(), row["url"])
        except OSError:
            stats["skipped"] += 1
            continue
        if _looks_like_cv_text(text):
            stats["skipped"] += 1
            continue
        candidates = _cv_link_candidates(links)
        if not candidates:
            stats["skipped"] += 1
            continue
        href = candidates[0][2]
        if href == row["url"]:
            stats["skipped"] += 1
            continue
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO author_cv_sources
                (author_id, url, source_type, status, notes, created_at)
            VALUES (?, ?, 'cv_link', 'candidate', 'followed from landing page', ?)
            """,
            (row["author_id"], href, db.utcnow()),
        )
        if cursor.rowcount:
            stats["inserted"] += 1
        else:
            stats["skipped"] += 1
    conn.commit()
    log.info("CV landing-page links: %s", stats)
    return stats


def parse_cv_sources(conn, *, limit: int | None = None) -> dict[str, int]:
    rows = conn.execute(
        """
        SELECT source_id, author_id, url, content_hash
        FROM author_cv_sources
        WHERE status IN ('fetched','parsed') AND content_hash IS NOT NULL
        ORDER BY source_id
        """
    ).fetchall()
    if limit is not None:
        rows = rows[:limit]
    institution_names = _institution_names(conn)
    stats = {"documents": len(rows), "parsed": 0, "events": 0, "name_mismatch": 0, "empty": 0}
    for row in rows:
        text_path = TEXTS_DIR / f"{row['content_hash']}.txt"
        if not text_path.exists():
            stats["empty"] += 1
            continue
        text = text_path.read_text(encoding="utf-8", errors="replace")
        author = conn.execute(
            "SELECT canonical_name FROM authors WHERE author_id=?", (row["author_id"],)
        ).fetchone()
        if not author:
            continue
        family = normalize_name_part(author["canonical_name"]).split()[-1]
        if family and family not in normalize_name_part(text):
            stats["name_mismatch"] += 1
            conn.execute(
                "UPDATE author_cv_sources SET status='name_mismatch' WHERE source_id=?",
                (row["source_id"],),
            )
            continue
        events = extract_cv_events(text, institution_names)
        # A reparse is authoritative: remove events from an older parser pass
        # even when the new pass finds nothing.
        conn.execute(
            "DELETE FROM career_events WHERE source_type='cv' AND author_id=? AND source_url=?",
            (row["author_id"], row["url"]),
        )
        if not events:
            stats["empty"] += 1
            conn.execute(
                "UPDATE author_cv_sources SET status='parsed', notes='0 events' WHERE source_id=?",
                (row["source_id"],),
            )
            continue
        count = upsert_cv_events(conn, row["author_id"], row["url"], events)
        stats["parsed"] += 1
        stats["events"] += count
        conn.execute(
            "UPDATE author_cv_sources SET status='parsed', notes=? WHERE source_id=?",
            (f"{count} events", row["source_id"]),
        )
        conn.commit()
    conn.commit()
    log.info("CV parse: %s", stats)
    return stats

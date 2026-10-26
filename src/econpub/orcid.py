from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import httpx

from . import db
from .authors import INSTITUTION_ALIASES, INSTITUTION_STOPWORDS
from .config import MAILTO, RAW_DIR
from .normalize import (
    clean_text,
    family_root,
    given_root,
    normalize_doi,
    normalize_name_part,
    normalize_orcid,
)
from .openalex import match_authorships, parse_work

log = logging.getLogger(__name__)

ORCID_API = "https://pub.orcid.org/v3.0"
RAW_ORCID_DIR = RAW_DIR / "orcid"
RECORDS_DIR = RAW_ORCID_DIR / "records"
USER_AGENT = f"EconPubDatabase/0.4 (mailto:{MAILTO})"

_THREAD_LOCAL = threading.local()
_CLIENTS: list[httpx.Client] = []
_CLIENT_LOCK = threading.Lock()

_CONFIDENCE_ORDER = {"low": 0, "medium": 1, "high": 2}

# A field signal is deliberately conservative: it must point to economics as a
# discipline, not merely contain a word such as "market" or "trade" that also
# appears in medicine, archaeology, or engineering.
_ECON_FIELD_RE = re.compile(
    r"(economic|econometric|macroeconomic|microeconomic|monetary economics|"
    r"fiscal policy|labor economics|labour economics|labor market|labour market|"
    r"unemployment|wage|income inequality|wealth inequality|taxation|tax policy|"
    r"public economics|health economics|development economics|international trade|"
    r"industrial organization|game theory|auction|contract theory|mechanism design|"
    r"financial economics|asset pricing|corporate finance|banking|central bank|"
    r"stock market|journal of economic|review of economic|economic review|"
    r"economic journal|econometrics|journal of finance|review of financial studies|"
    r"world bank economic review|imf economic review|department of economics|"
    r"school of economics|economics department|federal reserve|world bank|"
    r"international monetary fund|\bimf\b|nber|bank of england|"
    r"european central bank|research in economics)",
    re.IGNORECASE,
)
_NON_ECON_FIELD_RE = re.compile(
    r"(cardiolog|cardiac|surg|medical|medicine|clinical|cancer|oncolog|"
    r"physiotherap|nursing|hospital|archaeolog|anthropolog|marine|forest|"
    r"ecology|aquaculture|agronom|nutrition|epidemiolog|architect|dentist|"
    r"pharmac|veterinar|pediatr|radiolog|neurolog|psychiatr|theolog|religion|"
    r"mathematic|physics|chemistry|biology|optometr|dance|music|library|"
    r"librarian|electric power|geographic|drama|divinity|built environment)",
    re.IGNORECASE,
)
_ECON_JOURNAL_RE = re.compile(
    r"(american economic|econometrica|journal of political economy|"
    r"quarterly journal of economics|review of economic studies|economic journal|"
    r"journal of economic|review of economic|economics letters|economic theory|"
    r"games and economic behavior|rand journal|journal of finance|"
    r"review of financial studies|journal of financial economics|"
    r"journal of monetary economics|journal of public economics|"
    r"journal of development economics|journal of international economics|"
    r"journal of labor economics|journal of human resources|"
    r"journal of health economics|journal of urban economics|"
    r"journal of econometrics|quantitative economics|american economic journal|"
    r"aea papers|brookings papers|nber|imf economic review|"
    r"world bank economic review|"
    r"labour economics|labor economics|journal of economic history|"
    r"explorations in economic history|journal of economic growth|"
    r"review of economics and statistics|journal of economic behavior|"
    r"journal of economic perspectives|journal of economic literature)",
    re.IGNORECASE,
)
_PHD_ECONOMICS_RE = re.compile(
    r"(?:ph\.?\s*d\.?|doctor(?:ate|al)?)\s+(?:in\s+)?economics\b",
    re.IGNORECASE,
)

_ACCEPTED_STATUSES = {
    "verified_doi",
    "verified_title",
    "verified_institution",
    "field_economics",
}

_ORCID_STATUS_RANK = {
    "verified_doi": 7,
    "verified_title": 6,
    "verified_institution": 5,
    "field_economics": 4,
    "unverified": 3,
    "rejected_career_risk": 2,
    "rejected_field": 1,
    "rejected_name": 0,
}


def _assessment_score(assessment: dict[str, Any]) -> tuple[int, int, int, int]:
    return (
        _ORCID_STATUS_RANK.get(assessment.get("status"), -1),
        len(assessment.get("doi_overlap") or []),
        len(assessment.get("title_overlap") or []),
        int(assessment.get("event_count") or 0),
    )


def _bare_orcid(orcid: str) -> str:
    return normalize_orcid(orcid).rsplit("/", 1)[-1]


def _orcid_path(orcid: str) -> Path:
    return RECORDS_DIR / f"{_bare_orcid(orcid)}.json"


def _record_key(orcid: str, event_type: str, put_code: int | str) -> str:
    digest = hashlib.sha1(f"{orcid}|{event_type}|{put_code}".encode("utf-8")).hexdigest()
    return f"orcid:{digest}"


def apply_openalex_orcids(conn) -> dict[str, int]:
    """Copy ORCIDs from cached OpenAlex works onto our authorships.

    This is an offline pass over `source_records`; it uses the same positional/
    name author matching as the OpenAlex enrichment.
    """
    rows = conn.execute(
        """
        SELECT source_key, payload_json
        FROM source_records
        WHERE source='openalex_work'
        """
    ).fetchall()
    works = 0
    matched_slots = 0
    with_orcid = 0
    for row in rows:
        try:
            work = json.loads(row["payload_json"])
        except (TypeError, ValueError):
            continue
        doi = normalize_doi(work.get("doi") or row["source_key"])
        paper = conn.execute("SELECT paper_id FROM papers WHERE doi=?", (doi,)).fetchone()
        if not paper:
            continue
        our_rows = conn.execute(
            """
            SELECT authorship_id, author_order, given_name, family_name, full_name
            FROM authorships WHERE paper_id=? ORDER BY author_order
            """,
            (paper["paper_id"],),
        ).fetchall()
        parsed = parse_work(work)
        matches = match_authorships(our_rows, parsed["authorships"])
        works += 1
        matched_slots += len(matches)
        for our_row, oa, _method, _confidence in matches:
            orcid = normalize_orcid(oa.get("orcid"))
            if not orcid:
                continue
            conn.execute(
                "UPDATE authorships SET openalex_orcid=? WHERE authorship_id=?",
                (orcid, our_row["authorship_id"]),
            )
            with_orcid += 1
    conn.commit()
    stats = {"works": works, "matched_slots": matched_slots, "slots_with_orcid": with_orcid}
    log.info("OpenAlex ORCID mapping: %s", stats)
    return stats


def assign_author_orcids(conn) -> dict[str, int]:
    """Aggregate authorship ORCIDs onto canonical authors with conflict flags."""
    rows = conn.execute(
        """
        SELECT a.author_id, a.orcid AS existing_orcid,
               GROUP_CONCAT(DISTINCT s.openalex_orcid) AS orcids,
               COUNT(DISTINCT s.openalex_orcid) AS n
        FROM authors a
        JOIN authorships s ON s.author_id = a.author_id
        WHERE s.openalex_orcid IS NOT NULL
        GROUP BY a.author_id
        """
    ).fetchall()
    assigned = 0
    multiple = 0
    conflicts = 0
    for row in rows:
        orcids = sorted({value for value in str(row["orcids"]).split(",") if value})
        if not orcids:
            continue
        existing = normalize_orcid(row["existing_orcid"])
        chosen = existing or orcids[0]
        if len(orcids) > 1:
            multiple += 1
            other = conn.execute(
                "SELECT author_id FROM authors WHERE orcid=? AND author_id<>?",
                (chosen, row["author_id"]),
            ).fetchone()
            if other:
                # Two canonical authors claim the same ORCID through different
                # authorship evidence. Flag both rather than violating the
                # unique constraint or silently dropping one.
                conflicts += 1
                conn.execute(
                    """
                    UPDATE authors
                    SET needs_review=1, review_status='orcid_conflict', updated_at=?
                    WHERE author_id=?
                    """,
                    (db.utcnow(), row["author_id"]),
                )
                continue
            conn.execute(
                """
                UPDATE authors
                SET orcid=COALESCE(orcid, ?), orcid_source='openalex_work_authorship',
                    orcid_match_confidence='low', needs_review=1,
                    review_status=COALESCE(review_status,'orcid_conflict'), updated_at=?
                WHERE author_id=?
                """,
                (chosen, db.utcnow(), row["author_id"]),
            )
            continue
        if existing and existing != chosen:
            conflicts += 1
            conn.execute(
                """
                UPDATE authors
                SET needs_review=1, review_status='orcid_conflict', updated_at=?
                WHERE author_id=?
                """,
                (db.utcnow(), row["author_id"]),
            )
            continue
        other = conn.execute(
            "SELECT author_id FROM authors WHERE orcid=? AND author_id<>?",
            (chosen, row["author_id"]),
        ).fetchone()
        if other:
            conflicts += 1
            conn.execute(
                """
                UPDATE authors
                SET needs_review=1, review_status='orcid_conflict', updated_at=?
                WHERE author_id=?
                """,
                (db.utcnow(), row["author_id"]),
            )
            continue
        conn.execute(
            """
            UPDATE authors
            SET orcid=?, orcid_source='openalex_work_authorship',
                orcid_match_confidence='low', updated_at=?
            WHERE author_id=?
            """,
            (chosen, db.utcnow(), row["author_id"]),
        )
        assigned += 1
    conn.commit()
    stats = {
        "authors_with_orcid_evidence": len(rows),
        "assigned": assigned,
        "multiple_orcids": multiple,
        "conflicts": conflicts,
    }
    log.info("Author ORCID assignment: %s", stats)
    return stats


def _date_year(value: Any) -> int | None:
    if not isinstance(value, dict):
        return None
    year = value.get("year") or {}
    raw = year.get("value") if isinstance(year, dict) else None
    try:
        return int(raw) if raw else None
    except (TypeError, ValueError):
        return None


_NAME_SUFFIX_RE = re.compile(r"\b(?:jr|sr|ii|iii|iv)\b\.?", re.IGNORECASE)
_NICKNAMES = {
    "alex": "alexander",
    "andy": "andrew",
    "ben": "benjamin",
    "bill": "william",
    "bob": "robert",
    "dan": "daniel",
    "dave": "david",
    "doug": "douglas",
    "ed": "edward",
    "heski": "yeheskel",
    "itzik": "yizhak",
    "jim": "james",
    "joe": "joseph",
    "mike": "michael",
    "peggy": "margaret",
    "tom": "thomas",
}


def _person_names(payload: dict[str, Any]) -> list[str]:
    """All public name variants in an ORCID record.

    ORCID often stores a legal name ("K. Acemoglu") and a credit name
    ("K. Daron Acemoglu"). A single field is not enough for identity matching.
    """
    person = payload.get("person") or {}
    name = person.get("name") or {}
    given = ((name.get("given-names") or {}).get("value")) or ""
    family = ((name.get("family-name") or {}).get("value")) or ""
    credit = ((name.get("credit-name") or {}).get("value")) or ""
    variants: list[str] = []
    if given and family:
        variants.append(clean_text(f"{given} {family}"))
    if credit:
        variants.append(clean_text(credit))
    for other in ((person.get("other-names") or {}).get("other-name") or []):
        value = other.get("value") if isinstance(other, dict) else other
        if value:
            variants.append(clean_text(str(value)))
    expanded: list[str] = []
    for variant in variants:
        for part in re.split(r"\s*(?:,|\bor\b|;)\s*", variant):
            part = clean_text(part)
            if part:
                expanded.append(part)
    seen: set[str] = set()
    result = []
    for value in expanded:
        key = normalize_name_part(value)
        if key and key not in seen:
            seen.add(key)
            result.append(value)
    return result


def _person_name(payload: dict[str, Any]) -> str:
    names = _person_names(payload)
    return names[0] if names else ""


def _strip_name_suffix(value: str) -> str:
    return _NAME_SUFFIX_RE.sub(" ", value)


def _fold_umlaut(value: str) -> str:
    """Collapse German transliteration variants: Gaechter -> Gachter."""
    return value.replace("ae", "a").replace("oe", "o").replace("ue", "u")


def _name_compatible(author_name: str, orcid_name: str) -> bool:
    author_norm = normalize_name_part(_strip_name_suffix(author_name))
    orcid_norm = normalize_name_part(_strip_name_suffix(orcid_name))
    if not author_norm or not orcid_norm:
        return True
    if author_norm == orcid_norm:
        return True
    author_tokens = author_norm.split()
    orcid_tokens = orcid_norm.split()
    if len(author_tokens) < 2 or len(orcid_tokens) < 2:
        return False
    author_family = family_root(author_tokens[-1])
    orcid_family = family_root(orcid_tokens[-1])
    if author_family != orcid_family and _fold_umlaut(author_family) != _fold_umlaut(
        orcid_family
    ):
        return False
    author_given = given_root(" ".join(author_tokens[:-1]))
    orcid_given = given_root(" ".join(orcid_tokens[:-1]))
    if author_given == orcid_given:
        return True
    if _fold_umlaut(author_given) == _fold_umlaut(orcid_given):
        return True
    if len(author_given) == 1 and orcid_given.startswith(author_given):
        return True
    if len(orcid_given) == 1 and author_given.startswith(orcid_given):
        return True
    if (
        min(len(author_given), len(orcid_given)) >= 3
        and (
            author_given.startswith(orcid_given)
            or orcid_given.startswith(author_given)
        )
    ):
        return True
    return bool(
        _NICKNAMES.get(author_given) == orcid_given
        or _NICKNAMES.get(orcid_given) == author_given
    )


def _institution_tokens(value: str | None) -> set[str]:
    if not value:
        return set()
    tokens = set(normalize_name_part(value).split())
    expanded: set[str] = set()
    for token in tokens:
        expanded.update(INSTITUTION_ALIASES.get(token, {token}))
    return {
        token
        for token in expanded
        if len(token) >= 2 and token not in INSTITUTION_STOPWORDS
    }


def _orcid_institution_tokens(payload: dict[str, Any]) -> set[str]:
    tokens: set[str] = set()
    activities = payload.get("activities-summary") or {}
    for section in ("employments", "educations"):
        for group in (activities.get(section) or {}).get("affiliation-group") or []:
            for item in group.get("summaries") or []:
                summary = item.get(
                    "employment-summary" if section == "employments" else "education-summary"
                ) or {}
                name = ((summary.get("organization") or {}).get("name")) or ""
                tokens.update(_institution_tokens(name))
    return tokens


def _author_institution_tokens(conn, author_id: int) -> set[str]:
    tokens: set[str] = set()
    rows = conn.execute(
        """
        SELECT institution_hint, openalex_institution_name
        FROM authorships WHERE author_id=?
        """,
        (author_id,),
    ).fetchall()
    for row in rows:
        tokens.update(_institution_tokens(row["institution_hint"]))
        tokens.update(_institution_tokens(row["openalex_institution_name"]))
    return tokens


def _institutions_compatible(author_tokens: set[str], orcid_tokens: set[str]) -> bool:
    if not author_tokens or not orcid_tokens:
        # No evidence to reject; the name check remains the only guard.
        return True
    return bool(author_tokens & orcid_tokens)


def _title_key(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def _titles_match(left: str, right: str) -> bool:
    left_key = _title_key(left)
    right_key = _title_key(right)
    if not left_key or not right_key:
        return False
    if left_key == right_key:
        return True
    left_tokens = set(left_key.split())
    right_tokens = set(right_key.split())
    if min(len(left_tokens), len(right_tokens)) < 6:
        return False
    union = left_tokens | right_tokens
    return bool(union) and len(left_tokens & right_tokens) / len(union) >= 0.9


def _orcid_work_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    works = ((payload.get("activities-summary") or {}).get("works") or {}).get("group") or []
    for group in works:
        for summary in group.get("work-summary") or []:
            title = ((summary.get("title") or {}).get("title") or {}).get("value") or ""
            journal = ((summary.get("journal-title") or {}).get("value")) or ""
            dois: set[str] = set()
            external_ids = ((summary.get("external-ids") or {}).get("external-id") or [])
            for external_id in external_ids:
                kind = (external_id.get("external-id-type") or "").lower()
                value = (external_id.get("external-id-value") or "").strip()
                if "doi" in kind or value.lower().startswith("10."):
                    normalized = normalize_doi(value)
                    if normalized:
                        dois.add(normalized.lower())
            items.append({"title": title, "journal": journal, "dois": dois})
    return items


def _orcid_field_signals(
    items: list[dict[str, Any]], events: list[dict[str, Any]]
) -> tuple[bool, bool]:
    """Classify the record's field from affiliation and journal evidence.

    A word such as "economic" in one paper title is not enough: a political
    scientist, computer scientist, or medical researcher can easily produce
    that. Economics is accepted when the *affiliation* is an economics
    department/business school or a *journal* is a recognised economics journal.
    The negative signal is used only when neither positive signal exists.
    """
    affiliation_parts: list[str] = []
    for event in events:
        title = str(event.get("title") or "")
        department = str(event.get("department") or "")
        institution = str(event.get("institution") or "")
        if event.get("event_type") == "employment":
            affiliation_parts.extend((title, department, institution))
        elif event.get("event_type") == "education" and re.search(
            r"\bph\.?\s*d\.?\b|\bdoctor(?:ate|al)?\b", title, re.IGNORECASE
        ):
            # A doctoral field matters, but a certificate or a non-economics
            # degree title (e.g. "PhD in health economics" in a public-health
            # school) does not make the person an economist.
            affiliation_parts.extend((department, institution))
            if _PHD_ECONOMICS_RE.search(title):
                affiliation_parts.append(title)
    affiliation_text = " \n".join(part for part in affiliation_parts if part)
    journal_text = " \n".join(item["journal"] for item in items if item["journal"])
    all_text = " \n".join(
        [f"{item['title']} {item['journal']}" for item in items] + [affiliation_text]
    )
    affiliation_economics = bool(_ECON_FIELD_RE.search(affiliation_text))
    journal_economics = bool(_ECON_JOURNAL_RE.search(journal_text))
    economics = affiliation_economics or journal_economics
    other_hits = len(_NON_ECON_FIELD_RE.findall(all_text))
    economics_hits = len(_ECON_FIELD_RE.findall(all_text))
    other = (not economics) and other_hits > 0 and other_hits >= economics_hits
    return economics, other


def _author_papers(conn, author_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT p.title, p.doi, p.published_year
        FROM papers p
        JOIN authorships s ON s.paper_id = p.paper_id
        WHERE s.author_id=? AND p.content_type='article' AND p.is_duplicate=0
        """,
        (author_id,),
    ).fetchall()


def _career_risk(
    papers: list[sqlite3.Row], events: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Return ORCID events that would create a career assignment.

    These are the only events where a wrong identity can change the career
    layer. Events that do not cover a paper year are harmless for inference,
    although they still matter for the displayed timeline.
    """
    from .career import classify_role, _event_covers, _is_doctoral

    risks: list[dict[str, Any]] = []
    for event in events:
        start_year = event.get("start_year")
        if start_year is None:
            continue
        for paper in papers:
            year = paper["published_year"]
            if year is None:
                continue
            if not _event_covers(
                {"start_year": start_year, "end_year": event.get("end_year")},
                int(year),
            ):
                continue
            stage = None
            if event.get("event_type") == "employment":
                stage, _ = classify_role(event.get("title"))
            elif (
                event.get("event_type") == "education"
                and event.get("end_year") is not None
                and _is_doctoral(event.get("title"))
            ):
                stage = "phd_student"
            if stage:
                risks.append(
                    {
                        "year": int(year),
                        "doi": paper["doi"],
                        "event_type": event.get("event_type"),
                        "title": event.get("title"),
                        "institution": event.get("institution"),
                        "start_year": start_year,
                        "end_year": event.get("end_year"),
                        "stage": stage,
                    }
                )
                break
    return risks


def assess_orcid_identity(
    conn,
    author_id: int,
    payload: dict[str, Any],
    orcid: str,
) -> dict[str, Any]:
    """Classify an ORCID-to-author link by the strength of its evidence.

    Tiers, strongest first:
      verified_doi          an ORCID work DOI matches one of the author's AER DOIs
      verified_title        an ORCID work title matches an AER paper title
      verified_institution  ORCID employment/education overlaps an AER institution
      field_economics       an economics field signal but no direct AER link
      unverified            no positive evidence, but no contradiction either
      rejected_name         the ORCID person name conflicts with the author
      rejected_field        the ORCID record is in a clearly different field
      rejected_career_risk  no positive evidence, yet an event would change a stage
    """
    author = conn.execute(
        "SELECT canonical_name FROM authors WHERE author_id=?", (author_id,)
    ).fetchone()
    papers = _author_papers(conn, author_id)
    events = parse_orcid_record(payload, orcid)
    person_names = _person_names(payload)
    author_name = author["canonical_name"] if author else ""
    details: dict[str, Any] = {
        "orcid": orcid,
        "author_id": author_id,
        "person_name": person_names[0] if person_names else None,
        "person_names": person_names,
        "paper_count": len(papers),
        "event_count": len(events),
    }
    if (
        person_names
        and author_name
        and not any(_name_compatible(author_name, name) for name in person_names)
    ):
        details["status"] = "rejected_name"
        details["confidence"] = None
        return details

    items = _orcid_work_items(payload)
    work_dois: set[str] = set()
    for item in items:
        work_dois.update(item["dois"])
    author_dois = {
        normalize_doi(row["doi"]).lower()
        for row in papers
        if row["doi"] and normalize_doi(row["doi"])
    }
    doi_overlap = sorted(work_dois & author_dois)
    title_overlap = [
        item["title"]
        for item in items
        if any(_titles_match(item["title"], row["title"] or "") for row in papers)
    ]
    author_tokens = _author_institution_tokens(conn, author_id)
    orcid_tokens = _orcid_institution_tokens(payload)
    institution_overlap = bool(author_tokens and orcid_tokens and author_tokens & orcid_tokens)
    field_economics, field_non_econ = _orcid_field_signals(items, events)
    risks = _career_risk(papers, events)
    details.update(
        {
            "doi_overlap": doi_overlap[:5],
            "title_overlap": title_overlap[:5],
            "institution_overlap": institution_overlap,
            "economics_field": field_economics,
            "non_economics_field": field_non_econ,
            "career_risk": risks[:5],
        }
    )
    if doi_overlap:
        details["status"] = "verified_doi"
        details["confidence"] = "high"
    elif title_overlap:
        details["status"] = "verified_title"
        details["confidence"] = "high"
    elif institution_overlap:
        details["status"] = "verified_institution"
        details["confidence"] = "medium"
    elif field_economics and not field_non_econ:
        details["status"] = "field_economics"
        details["confidence"] = "low"
    elif field_non_econ:
        details["status"] = "rejected_field"
        details["confidence"] = None
    elif risks:
        details["status"] = "rejected_career_risk"
        details["confidence"] = None
    else:
        details["status"] = "unverified"
        details["confidence"] = "low"
    return details


def _summary_event(summary: dict[str, Any], event_type: str, orcid: str) -> dict[str, Any] | None:
    institution = ((summary.get("organization") or {}).get("name")) or ""
    institution = clean_text(institution)
    if not institution:
        return None
    title = clean_text(summary.get("role-title") or summary.get("degree-name") or "")
    department = clean_text(summary.get("department-name") or "")
    start_year = _date_year(summary.get("start-date"))
    end_year = _date_year(summary.get("end-date"))
    # ORCID does not have a reliable "current education" flag. A degree with a
    # start year but no end year is not treated as an open-ended enrolment.
    is_current = (
        1
        if event_type == "employment" and start_year is not None and end_year is None
        else 0
    )
    if start_year and end_year:
        confidence = "high"
    elif start_year or end_year:
        confidence = "medium"
    else:
        confidence = "low"
    put_code = summary.get("put-code")
    snippet = json.dumps(
        {
            "role": title,
            "department": department,
            "institution": institution,
            "start": start_year,
            "end": end_year,
            "current": bool(is_current),
        },
        ensure_ascii=False,
    )
    return {
        "event_type": event_type,
        "title": title or ("Doctoral degree" if event_type == "education" else "Position"),
        "institution": institution,
        "department": department,
        "start_year": start_year,
        "end_year": end_year,
        "is_current": is_current,
        "source_url": f"https://orcid.org/{orcid}",
        "source_type": "orcid",
        "source_snippet": snippet,
        "event_key": _record_key(orcid, event_type, put_code or snippet),
        "confidence": confidence,
    }


def parse_orcid_record(payload: dict[str, Any], orcid: str) -> list[dict[str, Any]]:
    orcid = normalize_orcid(orcid).rsplit("/", 1)[-1]
    activities = payload.get("activities-summary") or {}
    events: list[dict[str, Any]] = []
    for section, event_type in (("employments", "employment"), ("educations", "education")):
        groups = (activities.get(section) or {}).get("affiliation-group") or []
        for group in groups:
            for item in group.get("summaries") or []:
                summary = item.get(f"{event_type}-summary")
                if not isinstance(summary, dict):
                    continue
                event = _summary_event(summary, event_type, orcid)
                if event:
                    events.append(event)
    return events


def _upsert_institution(conn, name: str, country: str | None = None) -> int | None:
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
        INSERT INTO institutions
            (display_name, normalized_name, country, country_code, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (name, normalized, country, country, db.utcnow()),
    )
    return int(cursor.lastrowid)


def upsert_orcid_events(
    conn,
    author_id: int,
    orcid: str,
    events: list[dict[str, Any]],
    *,
    confidence_cap: str | None = None,
) -> int:
    # Re-fetching an ORCID record is authoritative for that author; remove
    # stale events before inserting the current record.
    conn.execute(
        """
        DELETE FROM career_events
        WHERE source_type='orcid' AND author_id=? AND source_url=?
        """,
        (author_id, f"https://orcid.org/{_bare_orcid(orcid)}"),
    )
    inserted = 0
    for event in events:
        confidence = event["confidence"]
        if confidence_cap and _CONFIDENCE_ORDER.get(confidence, 0) > _CONFIDENCE_ORDER.get(
            confidence_cap, 0
        ):
            confidence = confidence_cap
        institution_id = _upsert_institution(conn, event["institution"])
        conn.execute(
            """
            INSERT INTO career_events
                (author_id, event_type, title, institution, institution_id,
                 start_year, end_year, is_current, source_url, source_type,
                 source_snippet, event_key, confidence, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'orcid', ?, ?, ?, ?)
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
                source_type='orcid',
                source_snippet=excluded.source_snippet,
                confidence=excluded.confidence
            """,
            (
                author_id,
                event["event_type"],
                event["title"],
                event["institution"],
                institution_id,
                event["start_year"],
                event["end_year"],
                event["is_current"],
                event["source_url"],
                event["source_snippet"],
                event["event_key"],
                confidence,
                db.utcnow(),
            ),
        )
        inserted += 1
    return inserted


def _set_author_orcid(
    conn,
    author_id: int,
    orcid: str | None,
    source: str,
    confidence: str | None,
    needs_review: int,
    review_status: str | None,
) -> None:
    """Update ORCID fields without clobbering non-ORCID review flags."""
    conn.execute(
        """
        UPDATE authors
        SET orcid=?,
            orcid_source=?,
            orcid_match_confidence=?,
            needs_review=CASE
                WHEN review_status IS NULL OR review_status LIKE 'orcid_%' THEN ?
                ELSE needs_review
            END,
            review_status=CASE
                WHEN review_status IS NULL OR review_status LIKE 'orcid_%' THEN ?
                ELSE review_status
            END,
            updated_at=?
        WHERE author_id=?
        """,
        (orcid, source, confidence, needs_review, review_status, db.utcnow(), author_id),
    )


def _record_orcid_validation(conn, author_id: int, event_type: str, details: dict[str, Any]) -> None:
    row = conn.execute(
        "SELECT stable_id FROM authors WHERE author_id=?", (author_id,)
    ).fetchone()
    if not row or not row["stable_id"]:
        return
    reason = json.dumps(details, ensure_ascii=False, sort_keys=True)
    exists = conn.execute(
        """
        SELECT 1 FROM author_identity_events
        WHERE stable_id=? AND event_type=? AND reason=?
        LIMIT 1
        """,
        (row["stable_id"], event_type, reason),
    ).fetchone()
    if exists:
        return
    conn.execute(
        """
        INSERT INTO author_identity_events
            (stable_id, event_type, author_id, reason, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (row["stable_id"], event_type, author_id, reason, db.utcnow()),
    )


def _clear_orcid_evidence(conn, author_id: int) -> None:
    conn.execute(
        "DELETE FROM career_events WHERE author_id=? AND source_type='orcid'",
        (author_id,),
    )
    conn.execute(
        """
        DELETE FROM career_assignments
        WHERE author_id=? AND evidence_type IN ('orcid_employment','orcid_education')
        """,
        (author_id,),
    )


def _apply_orcid_assessment(
    conn,
    orcid: str,
    payload: dict[str, Any],
    author_ids: list[int],
) -> tuple[str, int]:
    """Validate one ORCID record and apply the resulting evidence policy."""
    primary = author_ids[0]
    assessment = assess_orcid_identity(conn, primary, payload, orcid)
    status = assessment["status"]
    confidence = assessment["confidence"]
    if status in _ACCEPTED_STATUSES:
        confidence_cap = None
        if status == "verified_institution":
            confidence_cap = "medium"
        elif status == "field_economics":
            confidence_cap = "low"
        # Only one canonical author may hold an ORCID (unique index). The
        # primary author is the one with the most matched authorships.
        conn.execute(
            "UPDATE authors SET orcid=NULL WHERE author_id<>? AND orcid=?",
            (primary, orcid),
        )
        _clear_orcid_evidence(conn, primary)
        events = parse_orcid_record(payload, orcid)
        inserted = upsert_orcid_events(
            conn, primary, orcid, events, confidence_cap=confidence_cap
        )
        needs_review = 1 if status == "field_economics" else 0
        review_status = (
            "orcid_unverified_field" if status == "field_economics" else None
        )
        _set_author_orcid(
            conn,
            primary,
            orcid,
            status,
            confidence,
            needs_review,
            review_status,
        )
        for other_id in author_ids[1:]:
            _clear_orcid_evidence(conn, other_id)
            conn.execute(
                """
                UPDATE authors
                SET needs_review=1,
                    review_status=CASE
                        WHEN review_status IS NULL OR review_status LIKE 'orcid_%'
                        THEN 'orcid_conflict'
                        ELSE review_status
                    END,
                    updated_at=?
                WHERE author_id=?
                """,
                (db.utcnow(), other_id),
            )
        if status == "field_economics":
            _record_orcid_validation(conn, primary, "orcid_accepted_field", assessment)
        return status, inserted

    if status == "unverified":
        for author_id in author_ids:
            _clear_orcid_evidence(conn, author_id)
        conn.execute(
            "UPDATE authors SET orcid=NULL WHERE author_id<>? AND orcid=?",
            (primary, orcid),
        )
        _set_author_orcid(
            conn,
            primary,
            orcid,
            "orcid_unverified",
            "low",
            1,
            "orcid_unverified",
        )
        for other_id in author_ids[1:]:
            conn.execute(
                """
                UPDATE authors
                SET orcid=CASE WHEN orcid=? THEN NULL ELSE orcid END,
                    needs_review=1,
                    review_status=CASE
                        WHEN review_status IS NULL OR review_status LIKE 'orcid_%'
                        THEN 'orcid_conflict'
                        ELSE review_status
                    END,
                    updated_at=?
                WHERE author_id=?
                """,
                (orcid, db.utcnow(), other_id),
            )
        _record_orcid_validation(conn, primary, "orcid_unverified", assessment)
        return status, 0

    # Rejected: the ORCID link is withheld, but the authorship-level ORCID
    # remains as provenance for a future revalidation.
    review_status = {
        "rejected_name": "orcid_name_conflict",
        "rejected_field": "orcid_field_mismatch",
        "rejected_career_risk": "orcid_unverified_career_risk",
    }.get(status, "orcid_rejected")
    for author_id in author_ids:
        _clear_orcid_evidence(conn, author_id)
        _set_author_orcid(
            conn,
            author_id,
            None,
            f"rejected_{status.removeprefix('rejected_')}",
            None,
            1,
            review_status,
        )
    _record_orcid_validation(conn, primary, "orcid_rejected", assessment)
    return status, 0


def revalidate_orcid_records(conn) -> dict[str, int]:
    """Re-run ORCID identity validation from the local record cache.

    This is offline: every record was fetched by `fetch_orcid_records` and is
    stored under `data/raw/orcid/records`. The function is idempotent and is the
    supported way to apply a stricter evidence policy to existing data.
    """
    files = sorted(RECORDS_DIR.glob("*.json"))
    stats: dict[str, int] = {
        "records": len(files),
        "unmapped": 0,
        "events": 0,
        "verified_doi": 0,
        "verified_title": 0,
        "verified_institution": 0,
        "field_economics": 0,
        "unverified": 0,
        "rejected_name": 0,
        "rejected_field": 0,
        "rejected_career_risk": 0,
    }
    # A small number of authors have several ORCIDs. Assess every record first,
    # then apply only the strongest one per author; otherwise the last file in
    # lexicographic order could overwrite a verified link with a rejected one.
    candidates: dict[int, tuple[tuple[int, int, int, int], Path, str, list[int]]] = {}
    for path in files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            stats["unmapped"] += 1
            continue
        orcid = f"https://orcid.org/{path.stem}"
        author_ids = _author_ids_for_orcid(conn, orcid)
        if not author_ids:
            row = conn.execute(
                "SELECT author_id FROM authors WHERE orcid=? ORDER BY author_id",
                (orcid,),
            ).fetchone()
            if row:
                author_ids = [int(row["author_id"])]
        if not author_ids:
            stats["unmapped"] += 1
            continue
        assessment = assess_orcid_identity(conn, author_ids[0], payload, orcid)
        status = assessment["status"]
        stats[status] = stats.get(status, 0) + 1
        score = _assessment_score(assessment)
        primary = author_ids[0]
        current = candidates.get(primary)
        if current is None or score > current[0]:
            candidates[primary] = (score, path, orcid, author_ids)

    for index, (_score, path, orcid, author_ids) in enumerate(
        sorted(candidates.values(), key=lambda item: item[2]), start=1
    ):
        payload = json.loads(path.read_text(encoding="utf-8"))
        status, inserted = _apply_orcid_assessment(conn, orcid, payload, author_ids)
        stats["events"] += inserted
        if index % 100 == 0:
            conn.commit()
            log.info(
                "ORCID revalidation %s/%s (verified=%s field=%s unverified=%s rejected=%s)",
                index,
                len(candidates),
                stats["verified_doi"]
                + stats["verified_title"]
                + stats["verified_institution"],
                stats["field_economics"],
                stats["unverified"],
                stats["rejected_name"]
                + stats["rejected_field"]
                + stats["rejected_career_risk"],
            )
    conn.commit()
    log.info("ORCID revalidation complete: %s", stats)
    return stats


def _author_ids_for_orcid(conn, orcid: str) -> list[int]:
    rows = conn.execute(
        """
        SELECT author_id, COUNT(*) AS n
        FROM authorships
        WHERE openalex_orcid=? AND author_id IS NOT NULL
        GROUP BY author_id
        ORDER BY n DESC, author_id
        """,
        (orcid,),
    ).fetchall()
    return [int(row["author_id"]) for row in rows]


def _worker_client() -> httpx.Client:
    client = getattr(_THREAD_LOCAL, "client", None)
    if client is None:
        client = httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=60.0,
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


def _fetch_record(orcid: str, refresh: bool) -> tuple[str, dict[str, Any] | None, str]:
    bare = _bare_orcid(orcid)
    path = _orcid_path(bare)
    if path.exists() and not refresh:
        try:
            return orcid, json.loads(path.read_text(encoding="utf-8")), "cached"
        except Exception:
            pass
    client = _worker_client()
    delay = 2.0
    for attempt in range(1, 4):
        try:
            response = client.get(f"{ORCID_API}/{bare}/record")
            if response.status_code == 200:
                payload = response.json()
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                time.sleep(0.2)
                return orcid, payload, "fetched"
            if response.status_code == 404:
                return orcid, None, "not_found"
            if response.status_code in {403, 429, 500, 502, 503, 504}:
                time.sleep(delay)
                delay = min(delay * 2, 30.0)
                continue
            return orcid, None, f"http_{response.status_code}"
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            if attempt == 3:
                return orcid, None, str(exc)
            time.sleep(delay)
            delay = min(delay * 2, 30.0)
    return orcid, None, "failed"


def fetch_orcid_records(
    conn,
    *,
    limit: int | None = None,
    workers: int = 4,
    refresh: bool = False,
) -> dict[str, int]:
    RECORDS_DIR.mkdir(parents=True, exist_ok=True)
    orcids = [
        row["orcid"]
        for row in conn.execute(
            """
            SELECT DISTINCT orcid FROM authors WHERE orcid IS NOT NULL
            UNION
            SELECT DISTINCT openalex_orcid FROM authorships WHERE openalex_orcid IS NOT NULL
            ORDER BY 1
            """
        )
        if row["orcid"]
    ]
    orcids = [normalize_orcid(value) for value in orcids]
    orcids = sorted({value for value in orcids if value})
    if limit is not None:
        orcids = orcids[:limit]
    run_id = db.start_run(conn, "orcid_record", {"limit": limit, "workers": workers})
    stats = {
        "orcids": len(orcids),
        "fetched": 0,
        "cached": 0,
        "parsed": 0,
        "events": 0,
        "failures": 0,
        "verified_doi": 0,
        "verified_title": 0,
        "verified_institution": 0,
        "field_economics": 0,
        "unverified": 0,
        "rejected_name": 0,
        "rejected_field": 0,
        "rejected_career_risk": 0,
    }
    try:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            futures = {pool.submit(_fetch_record, orcid, refresh): orcid for orcid in orcids}
            for index, future in enumerate(as_completed(futures), start=1):
                orcid, payload, status = future.result()
                if status == "cached":
                    stats["cached"] += 1
                elif status == "fetched":
                    stats["fetched"] += 1
                else:
                    stats["failures"] += 1
                    log.warning("ORCID record %s: %s", orcid, status)
                    continue
                if not payload:
                    continue
                author_ids = _author_ids_for_orcid(conn, orcid)
                if not author_ids:
                    primary = conn.execute(
                        "SELECT author_id FROM authors WHERE orcid=?", (orcid,)
                    ).fetchone()
                    if primary:
                        author_ids = [int(primary["author_id"])]
                if not author_ids:
                    continue
                validation_status, inserted = _apply_orcid_assessment(
                    conn, orcid, payload, author_ids
                )
                stats[validation_status] = stats.get(validation_status, 0) + 1
                stats["events"] += inserted
                if inserted:
                    stats["parsed"] += 1
                    db.save_source_record(
                        conn, "orcid_record", _bare_orcid(orcid), run_id, payload
                    )
                if index % 50 == 0:
                    conn.commit()
                    log.info(
                        "ORCID %s/%s (fetched=%s cached=%s events=%s failures=%s)",
                        index,
                        len(orcids),
                        stats["fetched"],
                        stats["cached"],
                        stats["events"],
                        stats["failures"],
                    )
        conn.commit()
        db.finish_run(conn, run_id, "success", stats["parsed"])
        log.info("ORCID harvest complete: %s", stats)
        return stats
    except Exception as exc:
        conn.commit()
        db.finish_run(conn, run_id, "failed", stats["parsed"], str(exc))
        raise
    finally:
        _close_clients()

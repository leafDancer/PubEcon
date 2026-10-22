from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from typing import Any

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_EMAIL_RE = re.compile(r"\(?\s*e-?mail:?\s*[^)]*\)?", re.IGNORECASE)
_PAREN_RE = re.compile(r"\([^)]*\)")


def clean_text(value: Any) -> str:
    """Flatten Crossref/JATS strings into plain, single-line text."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        value = " ".join(str(v) for v in value if v is not None)
    text = str(value)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = text.replace("\xa0", " ")
    text = _WS_RE.sub(" ", text)
    return text.strip()


def normalize_doi(value: Any) -> str:
    if not value:
        return ""
    doi = str(value).strip()
    doi = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", doi, flags=re.IGNORECASE)
    return doi.strip().lower()


def normalize_orcid(value: Any) -> str:
    if not value:
        return ""
    match = re.search(r"(\d{4}-\d{4}-\d{4}-[\dXx]{4})", str(value))
    if not match:
        return ""
    return f"https://orcid.org/{match.group(1).upper()}"


def date_parts(item: dict[str, Any], *keys: str) -> tuple[int | None, int | None, int | None]:
    for key in keys:
        container = item.get(key)
        if not isinstance(container, dict):
            continue
        parts = container.get("date-parts") or []
        if not parts or not parts[0]:
            continue
        values = list(parts[0]) + [None, None, None]
        if values[0] is None:
            continue
        year = int(values[0])
        month = int(values[1]) if values[1] is not None else None
        day = int(values[2]) if values[2] is not None else None
        return year, month, day
    return None, None, None


def extract_date(item: dict[str, Any]) -> tuple[int | None, int | None, int | None]:
    return date_parts(item, "published", "issued", "created")


def expand_abbreviated_page(first: Any, last: Any) -> str | None:
    """Expand AEA-style abbreviated end pages: 1705-41 -> 1741.

    Only numeric ranges where the last page is shorter and numerically smaller
    than the first are expanded. Roman numerals, electronic pages, and genuine
    reversed ranges are left untouched.
    """
    if last is None:
        return None
    first_text = str(first or "").strip()
    last_text = str(last).strip()
    if not (first_text.isdigit() and last_text.isdigit()):
        return last_text or None
    if len(last_text) >= len(first_text):
        return last_text
    if int(last_text) >= int(first_text):
        return last_text
    candidate = first_text[: len(first_text) - len(last_text)] + last_text
    if int(candidate) >= int(first_text):
        return candidate
    return last_text


def split_pages(value: Any) -> tuple[str | None, str | None]:
    if not value:
        return None, None
    parts = re.split(r"\s*[-–—]\s*", str(value).strip())
    if len(parts) >= 2 and parts[0] and parts[1]:
        return parts[0], expand_abbreviated_page(parts[0], parts[1])
    return (parts[0] or None), None


# Characters that NFKD does not decompose into ASCII. Transliterate them
# explicitly instead of dropping them (the old code silently destroyed names
# such as Hortaçsu, Pęski, and Szalay).
_SPECIAL_TRANSLIT = str.maketrans(
    {
        "ł": "l",
        "Ł": "L",
        "ø": "o",
        "Ø": "O",
        "ß": "ss",
        "æ": "ae",
        "Æ": "AE",
        "œ": "oe",
        "Œ": "OE",
        "ð": "d",
        "Ð": "D",
        "þ": "th",
        "Þ": "Th",
        "ı": "i",
        "đ": "d",
        "Đ": "D",
        "ħ": "h",
        "Ŋ": "N",
        "ŋ": "n",
        "ŧ": "t",
    }
)


def transliterate(value: Any) -> str:
    """NFKD transliteration that preserves non-Latin scripts."""
    text = str(value or "").translate(_SPECIAL_TRANSLIT)
    text = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def normalize_name_part(value: Any) -> str:
    text = transliterate(value).lower()
    text = re.sub(r"[^\w]+", " ", text, flags=re.UNICODE)
    text = text.replace("_", " ")
    return _WS_RE.sub(" ", text).strip()


def name_key(given: Any, family: Any) -> str:
    return f"{normalize_name_part(family)}|{normalize_name_part(given)}"


_FAMILY_PARTICLES = {
    "van",
    "von",
    "de",
    "del",
    "della",
    "der",
    "den",
    "la",
    "le",
    "lo",
    "da",
    "di",
    "du",
    "dos",
    "das",
    "des",
    "ter",
    "ten",
    "dal",
    "dalla",
}


def _family_root_from_tokens(tokens: list[str]) -> str:
    if not tokens:
        return ""
    if len(tokens) >= 2 and len(tokens[-1]) <= 2:
        return "".join(tokens)
    return tokens[-1]


def _given_root_from_tokens(tokens: list[str]) -> str:
    if not tokens:
        return ""
    non_initial = [token for token in tokens if len(token) > 1]
    return non_initial[0] if non_initial else tokens[0]


def family_root(family: Any) -> str:
    """A stable family-name root that absorbs particles and spacing variants.

    ``Van Reenen`` and ``Reenen`` -> ``reenen``; ``Dal Bo`` and ``Dalbó`` ->
    ``dalbo``. This is intentionally aggressive and is paired with given-name
    and affiliation checks before any merge.
    """
    return _family_root_from_tokens(normalize_name_part(family).split())


def given_root(given: Any) -> str:
    """First real given name, ignoring leading/middle initials.

    ``J. Vernon`` -> ``vernon``; ``Parag A`` -> ``parag``; ``S`` -> ``s``.
    """
    return _given_root_from_tokens(normalize_name_part(given).split())


def middle_initials(given: Any) -> set[str]:
    """Middle initials after the first real given name.

    Leading initials (``J. Vernon``) are ignored; surname particles that
    Crossref placed in the given field are ignored as well.
    """
    tokens = normalize_name_part(given).split()
    first_real = next((index for index, token in enumerate(tokens) if len(token) > 1), None)
    if first_real is None:
        return set()
    initials: set[str] = set()
    for token in tokens[first_real + 1 :]:
        if token in _FAMILY_PARTICLES:
            continue
        initials.add(token[0])
    return initials


def name_match_key(given: Any, family: Any) -> str:
    given_tokens = normalize_name_part(given).split()
    family_tokens = normalize_name_part(family).split()
    # Crossref sometimes puts a surname particle in the given-name field:
    # given="Pedro Dal", family="Bó" should match given="Pedro",
    # family="Dal Bó".
    if len(given_tokens) > 1 and given_tokens[-1] in _FAMILY_PARTICLES:
        family_tokens = [given_tokens[-1]] + family_tokens
        given_tokens = given_tokens[:-1]
    # Crossref sometimes files a middle name as the first family token, e.g.
    # given="W", family="Michael Hanemann". When the given field is only
    # initials, move leading non-particle family tokens into the given field.
    if (
        given_tokens
        and all(len(token) == 1 for token in given_tokens)
        and len(family_tokens) > 1
    ):
        while len(family_tokens) > 1 and family_tokens[0] not in _FAMILY_PARTICLES:
            given_tokens.append(family_tokens.pop(0))
    family_part = _family_root_from_tokens(family_tokens)
    given_part = _given_root_from_tokens(given_tokens)
    if not family_part or not given_part:
        return ""
    return f"{family_part}|{given_part}"


def title_key(value: Any) -> str:
    """Punctuation- and quote-insensitive title key for deduplication."""
    text = clean_text(value)
    text = unicodedata.normalize("NFKC", text).lower()
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    text = re.sub(r"[^\w]+", " ", text, flags=re.UNICODE)
    text = text.replace("_", " ")
    return _WS_RE.sub(" ", text).strip()


def normalize_issue(value: Any) -> str:
    text = str(value or "").strip()
    if text.isdigit():
        return str(int(text))
    return text.lower().replace(" ", "")


_ROMAN_VALUES = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}
_ROMAN_RE = re.compile(r"^[ivxlcdm]+$", re.IGNORECASE)


def roman_to_int(value: str) -> int | None:
    text = str(value or "").strip().lower()
    if not _ROMAN_RE.match(text):
        return None
    total = 0
    previous = 0
    for char in reversed(text):
        current = _ROMAN_VALUES[char]
        if current < previous:
            total -= current
        else:
            total += current
        previous = current
    return total


def parse_page_number(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    return roman_to_int(text)


def page_range(page_first: Any, page_last: Any) -> tuple[int, int] | None:
    first = parse_page_number(page_first)
    last = parse_page_number(page_last)
    if first is None and last is None:
        return None
    if first is None:
        first = last
    if last is None:
        last = first
    if first is None or last is None:
        return None
    if last < first:
        first, last = last, first
    return first, last


def page_ranges_overlap(a: tuple[int, int] | None, b: tuple[int, int] | None) -> bool:
    if a is None or b is None:
        return False
    return max(a[0], b[0]) <= min(a[1], b[1])


def canonical_name(given: Any, family: Any) -> str:
    given_text = clean_text(given)
    family_text = clean_text(family)
    if given_text and family_text:
        return f"{given_text} {family_text}"
    return given_text or family_text


# The order matters: "Assistant Professor" must be tested before "Professor".
_RANK_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("assistant_professor", re.compile(r"\bassistant\s+professor\b", re.IGNORECASE)),
    ("associate_professor", re.compile(r"\bassociate\s+professor\b", re.IGNORECASE)),
    ("emeritus", re.compile(r"\bemerit(?:us|a)\b", re.IGNORECASE)),
    ("other_academic", re.compile(r"\b(?:visiting|adjunct|clinical|research)\s+professor\b", re.IGNORECASE)),
    ("full_professor", re.compile(r"\b(?:full\s+)?professor\b", re.IGNORECASE)),
    (
        "phd_student",
        re.compile(r"\b(?:ph\.?\s?d\.?|doctoral|doctorate)\s+(?:student|candidate)\b", re.IGNORECASE),
    ),
    (
        "masters_student",
        re.compile(r"\b(?:master'?s?|m\.?\s?a\.?|m\.?\s?sc\.?)\s+(?:student|candidate)\b", re.IGNORECASE),
    ),
    ("undergraduate", re.compile(r"\b(?:undergraduate|bachelor'?s?)\s+(?:student|candidate)?\b", re.IGNORECASE)),
    (
        "postdoc",
        re.compile(r"\b(?:post-?doc(?:toral)?|postdoctoral\s+(?:fellow|researcher|scholar))\b", re.IGNORECASE),
    ),
    (
        "lecturer_other_academic",
        re.compile(r"\b(?:senior\s+)?lecturer\b|\breader\b|\binstructor\b", re.IGNORECASE),
    ),
    (
        "research_fellow",
        re.compile(r"\b(?:research|senior\s+research)\s+(?:fellow|scientist|scholar)\b", re.IGNORECASE),
    ),
]

_NONACADEMIC_RE = re.compile(
    r"\b(federal reserve|world bank|international monetary fund|\bimf\b|bank of england|"
    r"european central bank|central bank|treasury|census bureau|bureau of labor statistics|"
    r"\boecd\b|government|ministry|consulting|google|microsoft|amazon|meta|goldman sachs|"
    r"mckinsey|world trade organization|\bwto\b)\b",
    re.IGNORECASE,
)
_ACADEMIC_RE = re.compile(r"\b(university|college|institute|school|academy)\b", re.IGNORECASE)

_INSTITUTION_KEYWORDS = re.compile(
    r"\b(university|college|institute|institution|school|academy|bank|board|bureau|"
    r"agency|foundation|center|centre|laboratory|observatory|nber|cepr|imf|oecd)\b",
    re.IGNORECASE,
)
_RANK_ONLY_RE = re.compile(
    r"^\s*(assistant|associate|full|visiting|adjunct|research)\s+professor\s*$",
    re.IGNORECASE,
)
_STREET_PREFIX_RE = re.compile(
    r"\b(avenida|avenue|av\.?|rua|rue|via|calle|street|st\.?|road|rd\.?)\s*$",
    re.IGNORECASE,
)
_UC_CAMPUS_RE = re.compile(
    r"University\s+of\s+California(?:\s*,\s*|\s+at\s+|\s*-\s*)"
    r"(Berkeley|Los Angeles|San Diego|Santa Barbara|Santa Cruz|Davis|Irvine|Riverside|Merced|San Francisco)\b",
    re.IGNORECASE,
)


def extract_rank(affiliation: str | None) -> tuple[str | None, str | None]:
    """Return (matched phrase, normalised category) from an affiliation string."""
    if not affiliation:
        return None, None
    text = clean_text(affiliation)
    for category, pattern in _RANK_RULES:
        match = pattern.search(text)
        if match:
            if _STREET_PREFIX_RE.search(text[: match.start()]):
                continue
            return match.group(0), category
    if _NONACADEMIC_RE.search(text) and not _ACADEMIC_RE.search(text):
        match = _NONACADEMIC_RE.search(text)
        return (match.group(0) if match else None), "non_academic"
    return None, None


def extract_institution_hint(affiliation: str | None) -> str | None:
    """A deliberately rough institution string for reporting/entity resolution.

    This is not an institution resolver. It picks the most institution-like
    comma-separated segment so the M1 report can show what the raw data looks
    like. M2/M3 replace it with a proper resolver.
    """
    if not affiliation:
        return None
    text = clean_text(affiliation)
    text = _UC_CAMPUS_RE.sub(lambda match: f"University of California {match.group(1)}", text)
    text = _EMAIL_RE.sub("", text)
    text = _PAREN_RE.sub("", text)
    segments = [segment.strip(" .") for segment in re.split(r"[;,]", text)]
    candidates = [
        segment
        for segment in segments
        if segment and not _RANK_ONLY_RE.match(segment) and _INSTITUTION_KEYWORDS.search(segment)
    ]
    if not candidates:
        return None
    for keyword in ("University", "College", "Institute", "School", "Bank", "Bureau", "Board", "Center", "Centre"):
        for candidate in candidates:
            if keyword.lower() in candidate.lower():
                return candidate
    return candidates[0]


def synthetic_key(title: str | None, year: int | None, page_first: str | None) -> str:
    raw = f"{title or ''}|{year or ''}|{page_first or ''}".encode("utf-8")
    return "crossref:" + hashlib.sha1(raw).hexdigest()[:16]

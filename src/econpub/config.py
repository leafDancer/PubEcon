from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
_REPO_ROOT = PACKAGE_DIR.parents[1]
# Editable checkouts keep data beside the repository. A wheel install has no
# repository, so use the working directory unless PUBECON_DATA_DIR is set.
PROJECT_ROOT = _REPO_ROOT if (_REPO_ROOT / "pyproject.toml").exists() else Path.cwd()
SRC_DIR = PACKAGE_DIR.parent

DATA_DIR = Path(
    os.environ.get(
        "PUBECON_DATA_DIR", os.environ.get("ECONPUB_DATA_DIR", PROJECT_ROOT / "data")
    )
).expanduser().resolve()
RAW_DIR = DATA_DIR / "raw"
CURATED_DIR = DATA_DIR / "curated"
REPORTS_DIR = DATA_DIR / "reports"
LOGS_DIR = DATA_DIR / "logs"
DB_PATH = CURATED_DIR / "econpub.db"
TOP5_DB = CURATED_DIR / "top5.db"
SCHEMA_PATH = PACKAGE_DIR / "schema.sql"


@dataclass(frozen=True)
class Journal:
    """A journal in the harvest registry.

    ``issn`` is the print ISSN used for the Crossref journal endpoint. Online
    ISSNs can be added later when a journal's Crossref deposit is split.
    """

    code: str
    name: str
    issn: str


JOURNALS: dict[str, Journal] = {
    "AER": Journal("AER", "American Economic Review", "0002-8282"),
    "QJE": Journal("QJE", "Quarterly Journal of Economics", "0033-5533"),
    "JPE": Journal("JPE", "Journal of Political Economy", "0022-3808"),
    "RES": Journal("RES", "Review of Economic Studies", "0034-6527"),
    "ECMA": Journal("ECMA", "Econometrica", "0012-9682"),
}
DEFAULT_JOURNAL = "AER"

# Backwards-compatible aliases for the AER-only pipeline. New code should use
# the journal registry so a journal never has to be hard-coded again.
JOURNAL_NAME = JOURNALS[DEFAULT_JOURNAL].name
JOURNAL_ISSN = JOURNALS[DEFAULT_JOURNAL].issn
CROSSREF_BASE = "https://api.crossref.org"
START_YEAR = 2000

# Crossref asks API users to identify a contact address. Override this with
# your own address when running a real harvest.
MAILTO = (
    os.environ.get("PUBECON_MAILTO")
    or os.environ.get("ECONPUB_MAILTO")
    or "pubecon-database@users.noreply.github.com"
)
USER_AGENT = f"PubEconDatabase/1.0 (mailto:{MAILTO})"

# Only fields needed for M1. Keeping the selection narrow makes pagination
# substantially faster; source_records still preserves the raw payload.
CROSSREF_SELECT = [
    "DOI",
    "title",
    "author",
    "issued",
    "published",
    "published-print",
    "published-online",
    "container-title",
    "subtitle",
    "ISSN",
    "publisher",
    "volume",
    "issue",
    "page",
    "abstract",
    "subject",
    "type",
    "URL",
    "is-referenced-by-count",
    "update-to",
    "relation",
    "link",
]

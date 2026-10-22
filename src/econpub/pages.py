from __future__ import annotations

import logging
import sqlite3

from .normalize import expand_abbreviated_page

log = logging.getLogger(__name__)


def normalize_page_ranges(conn: sqlite3.Connection) -> dict[str, int]:
    """Expand abbreviated end pages already stored in the database.

    Crossref and AEA both use AER's house style (``1705-41`` for pages
    1705-1741). The harvester expands new records; this pass repairs the
    existing corpus. Genuine reversed ranges are counted but not rewritten.
    """
    rows = conn.execute(
        """
        SELECT paper_id, page_first, page_last
        FROM papers
        WHERE page_first IS NOT NULL AND page_last IS NOT NULL
        """
    ).fetchall()
    changed = 0
    reversed_ranges = 0
    examples: list[tuple[str, str, str]] = []
    for row in rows:
        first = str(row["page_first"]).strip()
        last = str(row["page_last"]).strip()
        expanded = expand_abbreviated_page(first, last)
        if expanded and expanded != last:
            conn.execute(
                "UPDATE papers SET page_last=? WHERE paper_id=?",
                (expanded, row["paper_id"]),
            )
            changed += 1
            if len(examples) < 10:
                examples.append((first, last, expanded))
        if first.isdigit() and (expanded or "").isdigit() and int(expanded) < int(first):
            reversed_ranges += 1
    conn.commit()
    stats = {"changed": changed, "reversed_ranges": reversed_ranges}
    log.info("Page-range normalization: %s; examples=%s", stats, examples)
    return stats

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .config import REPORTS_DIR


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _table(headers: list[str], rows: list[tuple[Any, ...]] | list[list[Any]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(value) for value in row) + " |")
    return "\n".join(lines)


def generate_m6_report(conn, path: Path | None = None) -> tuple[Path, Path]:
    """Coverage-engineering report: CV crawl and historical-page yield."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    markdown_path = path or (REPORTS_DIR / "m6_coverage.md")
    metrics_path = markdown_path.with_suffix(".json")

    cv_summary = conn.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM author_cv_sources) AS sources,
            (SELECT COUNT(*) FROM author_cv_sources WHERE status='candidate') AS candidates,
            (SELECT COUNT(*) FROM author_cv_sources WHERE status='homepage_fetched') AS homepages,
            (SELECT COUNT(*) FROM author_cv_sources
                WHERE source_type IN ('cv_link','cv_document') AND content_hash IS NOT NULL) AS downloaded,
            (SELECT COUNT(*) FROM author_cv_sources WHERE status='parsed') AS parsed,
            (SELECT COUNT(*) FROM author_cv_sources WHERE status='failed') AS failed,
            (SELECT COUNT(*) FROM author_cv_sources WHERE status='name_mismatch') AS name_mismatch,
            (SELECT COUNT(*) FROM career_events WHERE source_type='cv') AS cv_events,
            (SELECT COUNT(*) FROM career_assignments WHERE evidence_type LIKE 'cv%') AS cv_assignments
        """
    ).fetchone()
    cv_authors = conn.execute(
        "SELECT COUNT(DISTINCT author_id) FROM career_events WHERE source_type='cv'"
    ).fetchone()[0]
    status_rows = conn.execute(
        "SELECT status, COUNT(*) AS n FROM author_cv_sources GROUP BY status ORDER BY n DESC"
    ).fetchall()
    type_rows = conn.execute(
        """
        SELECT source_type, status, COUNT(*) AS n
        FROM author_cv_sources GROUP BY 1, 2 ORDER BY n DESC
        """
    ).fetchall()
    domain_rows = conn.execute(
        """
        SELECT url, status FROM author_cv_sources
        WHERE source_type='cv_link' AND status IN ('parsed','name_mismatch','failed','fetched')
        """
    ).fetchall()
    domains: dict[str, dict[str, int]] = {}
    for row in domain_rows:
        host = (urlsplit(row["url"]).hostname or "unknown").lower()
        bucket = domains.setdefault(host, {"parsed": 0, "failed": 0, "other": 0})
        if row["status"] == "parsed":
            bucket["parsed"] += 1
        elif row["status"] in {"failed", "name_mismatch"}:
            bucket["failed"] += 1
        else:
            bucket["other"] += 1
    top_domains = sorted(
        domains.items(),
        key=lambda item: (item[1]["parsed"], -item[1]["failed"]),
        reverse=True,
    )[:15]

    wayback_summary = conn.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM author_wayback_snapshots) AS snapshots,
            (SELECT COUNT(*) FROM author_wayback_snapshots WHERE status='candidate') AS candidates,
            (SELECT COUNT(*) FROM author_wayback_snapshots WHERE status='fetched') AS fetched,
            (SELECT COUNT(*) FROM author_wayback_snapshots WHERE status='parsed') AS parsed,
            (SELECT COUNT(*) FROM author_wayback_snapshots WHERE status='failed') AS failed,
            (SELECT COUNT(*) FROM author_wayback_snapshots WHERE status='empty') AS empty,
            (SELECT COUNT(*) FROM career_events WHERE source_type='wayback') AS events,
            (SELECT COUNT(*) FROM career_assignments WHERE evidence_type LIKE 'wayback%') AS assignments
        """
    ).fetchone()
    wayback_status = conn.execute(
        """
        SELECT status, COUNT(*) AS n
        FROM author_wayback_snapshots GROUP BY status ORDER BY n DESC
        """
    ).fetchall()

    lines: list[str] = []
    lines.append("# M6 Coverage Report — AER 2000+")
    lines.append("")
    lines.append(f"Generated: {_utcnow()}")
    lines.append("")
    lines.append(
        "M6 measures the yield of the CV/homepage crawl and historical-page "
        "snapshots. It is a provenance report, not a claim that every public CV "
        "has been found."
    )
    lines.append("")
    lines.append("## CV crawl")
    lines.append("")
    lines.append(
        _table(
            ["Metric", "Value"],
            [
                ("CV/homepage sources", cv_summary["sources"]),
                ("  — candidates", cv_summary["candidates"]),
                ("  — homepages parsed", cv_summary["homepages"]),
                ("  — documents downloaded", cv_summary["downloaded"]),
                ("  — documents parsed", cv_summary["parsed"]),
                ("  — name mismatches", cv_summary["name_mismatch"]),
                ("  — failed", cv_summary["failed"]),
                ("Authors with CV events", cv_authors),
                ("CV career events", cv_summary["cv_events"]),
                ("CV career assignments", cv_summary["cv_assignments"]),
            ],
        )
    )
    lines.append("")
    lines.append(
        _table(
            ["Source status", "Sources"],
            [(row["status"], row["n"]) for row in status_rows],
        )
    )
    lines.append("")
    lines.append(
        _table(
            ["Source type", "Status", "Sources"],
            [(row["source_type"], row["status"], row["n"]) for row in type_rows],
        )
    )
    lines.append("")
    lines.append("## CV yield by domain")
    lines.append("")
    lines.append(
        _table(
            ["Domain", "Parsed", "Failed / mismatch", "Other"],
            [
                (host, counts["parsed"], counts["failed"], counts["other"])
                for host, counts in top_domains
            ],
        )
    )
    lines.append("")
    lines.append("## Historical pages (Wayback)")
    lines.append("")
    lines.append(
        _table(
            ["Metric", "Value"],
            [
                ("Archived snapshots", wayback_summary["snapshots"]),
                ("  — candidates", wayback_summary["candidates"]),
                ("  — fetched", wayback_summary["fetched"]),
                ("  — parsed", wayback_summary["parsed"]),
                ("  — failed", wayback_summary["failed"]),
                ("  — empty", wayback_summary["empty"]),
                ("Wayback career events", wayback_summary["events"]),
                ("Wayback career assignments", wayback_summary["assignments"]),
            ],
        )
    )
    lines.append("")
    if wayback_status:
        lines.append(
            _table(
                ["Snapshot status", "Snapshots"],
                [(row["status"], row["n"]) for row in wayback_status],
            )
        )
        lines.append("")
    lines.append("## Interpretation")
    lines.append("")
    lines.append(
        "- A parsed document may contain zero usable events; the parser is "
        "conservative. `candidate` rows are the resumable queue, not missing data."
    )
    lines.append(
        "- Failed and name-mismatch sources remain in the table for audit. They "
        "are not silently retried forever; `--retry-failed` requeues them."
    )
    lines.append(
        "- Wayback snapshots are tied to one paper year. They are used only when "
        "an academic rank appears near the author's name, and confidence is "
        "capped at medium."
    )
    lines.append(
        "- The Internet Archive was not reachable from the development network "
        "used for this run; see `docs/m6-coverage.md`."
    )
    lines.append("")

    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    metrics = {
        "generated_at": _utcnow(),
        "cv_summary": dict(cv_summary),
        "cv_authors_with_events": cv_authors,
        "cv_status": [dict(row) for row in status_rows],
        "cv_types": [dict(row) for row in type_rows],
        "cv_domains": [{"domain": host, **counts} for host, counts in top_domains],
        "wayback_summary": dict(wayback_summary),
        "wayback_status": [dict(row) for row in wayback_status],
    }
    metrics_path.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return markdown_path, metrics_path

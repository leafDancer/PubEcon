from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .config import JOURNALS, REPORTS_DIR

MANIFEST_NAME = "release_manifest"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _git_commit(root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


def _table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    names = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        )
    ]
    return {name: conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0] for name in names}


def _journal_counts(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT COALESCE(p.journal_code, 'AER') AS code,
               COUNT(*) AS articles,
               (SELECT COUNT(*) FROM authorships s WHERE s.paper_id IN (
                    SELECT paper_id FROM papers p2
                    WHERE p2.journal_code=COALESCE(p.journal_code, 'AER')
                      AND p2.content_type='article' AND p2.is_duplicate=0)) AS authorships,
               (SELECT COUNT(*) FROM career_assignments ca
                JOIN authorships s ON s.authorship_id=ca.authorship_id
                JOIN papers p3 ON p3.paper_id=s.paper_id
                WHERE p3.journal_code=COALESCE(p.journal_code, 'AER')
                  AND p3.content_type='article' AND p3.is_duplicate=0) AS assignments
        FROM papers p
        WHERE p.content_type='article' AND p.is_duplicate=0
        GROUP BY COALESCE(p.journal_code, 'AER')
        ORDER BY articles DESC, code
        """
    ).fetchall()
    return [
        {
            "code": row["code"],
            "name": JOURNALS[row["code"]].name if row["code"] in JOURNALS else row["code"],
            "articles": row["articles"],
            "authorships": row["authorships"],
            "assignments": row["assignments"],
        }
        for row in rows
    ]


def _headline_counts(conn: sqlite3.Connection) -> dict[str, int]:
    row = conn.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM papers) AS papers_total,
            (SELECT COUNT(*) FROM papers WHERE content_type='article' AND is_duplicate=0)
                AS research_articles,
            (SELECT COUNT(*) FROM authorships s JOIN papers p ON p.paper_id=s.paper_id
                WHERE p.content_type='article' AND p.is_duplicate=0) AS authorships,
            (SELECT COUNT(*) FROM authors a WHERE EXISTS (
                SELECT 1 FROM authorships s JOIN papers p ON p.paper_id=s.paper_id
                WHERE s.author_id=a.author_id AND p.content_type='article'
                  AND p.is_duplicate=0)) AS active_authors,
            (SELECT COUNT(*) FROM coauthorship_edges) AS coauthorship_edge_records,
            (SELECT COUNT(*) FROM (
                SELECT DISTINCT
                    CASE WHEN author_a_id < author_b_id THEN author_a_id ELSE author_b_id END,
                    CASE WHEN author_a_id < author_b_id THEN author_b_id ELSE author_a_id END
                FROM coauthorship_edges
            )) AS coauthor_ties,
            (SELECT COUNT(*) FROM career_assignments) AS career_assignments
        """
    ).fetchone()
    return dict(row)


def _raw_cache_inventory(root: Path) -> dict[str, Any]:
    if not root.exists():
        return {"path": str(root), "files": 0, "bytes": 0}
    files = 0
    total = 0
    for item in root.rglob("*"):
        if item.is_file():
            files += 1
            try:
                total += item.stat().st_size
            except OSError:
                pass
    return {"path": str(root), "files": files, "bytes": total}


def _report_inventory(directory: Path) -> list[dict[str, Any]]:
    if not directory.exists():
        return []
    items = []
    for item in sorted(directory.iterdir()):
        if item.is_file() and item.stem != MANIFEST_NAME and item.suffix in {".md", ".json"}:
            items.append(
                {
                    "name": item.name,
                    "bytes": item.stat().st_size,
                    "sha256": sha256_file(item),
                }
            )
    return items


def generate_release_manifest(
    db_path: Path | str,
    *,
    artifact: Path | str | None = None,
    output_dir: Path | str | None = None,
    root: Path | str | None = None,
) -> tuple[Path, Path]:
    """Write a JSON/Markdown manifest for a versioned dataset release.

    The database itself is not copied or uploaded. Publish it as a release
    asset, then publish this manifest so others can verify the exact bytes.
    """
    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")
    output_dir = Path(output_dir or REPORTS_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)
    root = Path(root or Path.cwd())

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        manifest: dict[str, Any] = {
            "product": "PubEcon",
            "version": __version__,
            "generated_at": utcnow(),
            "git_commit": _git_commit(root),
            "database": {
                "path": str(db_path),
                "bytes": db_path.stat().st_size,
                "sha256": sha256_file(db_path),
            },
            "artifact": None,
            "counts": _headline_counts(conn),
            "journals": _journal_counts(conn),
            "tables": _table_counts(conn),
            "raw_cache": _raw_cache_inventory(Path(root) / "data" / "raw"),
            "reports": _report_inventory(output_dir),
        }
    finally:
        conn.close()

    if artifact:
        artifact_path = Path(artifact)
        if not artifact_path.exists():
            raise FileNotFoundError(f"Artifact not found: {artifact_path}")
        manifest["artifact"] = {
            "path": str(artifact_path),
            "bytes": artifact_path.stat().st_size,
            "sha256": sha256_file(artifact_path),
        }

    metrics_path = output_dir / f"{MANIFEST_NAME}.json"
    markdown_path = output_dir / f"{MANIFEST_NAME}.md"
    metrics_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    database = manifest["database"]
    lines = [
        "# Release manifest",
        "",
        f"- **Product:** {manifest['product']}",
        f"- **Version:** {manifest['version']}",
        f"- **Generated:** {manifest['generated_at']}",
        f"- **Git commit:** {manifest['git_commit'] or '—'}",
        f"- **Database:** `{database['path']}`",
        f"- **Database bytes:** {database['bytes']:,}",
        f"- **Database SHA-256:** `{database['sha256']}`",
    ]
    if manifest["artifact"]:
        artifact = manifest["artifact"]
        lines.extend(
            [
                f"- **Release artifact:** `{artifact['path']}`",
                f"- **Artifact bytes:** {artifact['bytes']:,}",
                f"- **Artifact SHA-256:** `{artifact['sha256']}`",
            ]
        )
    counts = manifest["counts"]
    lines.extend(
        [
            "",
            "## Headline counts",
            "",
            "| Metric | Value |",
            "|---|---:|",
            f"| Crossref records | {counts['papers_total']:,} |",
            f"| Research articles | {counts['research_articles']:,} |",
            f"| Author slots | {counts['authorships']:,} |",
            f"| Active canonical authors | {counts['active_authors']:,} |",
            f"| Coauthor ties (unique pairs) | {counts['coauthor_ties']:,} |",
            f"| Coauthor edge records | {counts['coauthorship_edge_records']:,} |",
            f"| Career assignments | {counts['career_assignments']:,} |",
            "",
            "## Journals",
            "",
            "| Journal | Articles | Author slots | Career assignments |",
            "|---|---:|---:|---:|",
        ]
    )
    for row in manifest["journals"]:
        lines.append(
            f"| {row['code']} — {row['name']} | {row['articles']:,} | "
            f"{row['authorships']:,} | {row['assignments']:,} |"
        )
    raw = manifest["raw_cache"]
    lines.extend(
        [
            "",
            "## Reproducibility notes",
            "",
            f"- Raw source cache: `{raw['path']}` ({raw['files']:,} files, "
            f"{raw['bytes']:,} bytes). It is not included in this manifest hash; "
            "the cached Crossref/OpenAlex/ORCID payloads are the audit trail for a rebuild.",
            "- The database is the authoritative release artifact. Rebuilding from live APIs "
            "can produce a different snapshot even with the same code.",
            "- Publish the database as a release asset and keep this manifest with it; "
            "verify with `sha256sum` (Linux/macOS) or `Get-FileHash` (PowerShell).",
            "",
        ]
    )
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    return markdown_path, metrics_path

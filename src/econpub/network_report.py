from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import REPORTS_DIR
from .coverage import _table
from .network import JOURNAL_CODES, build_graph, compute_stats


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def generate_network_stats(
    conn,
    *,
    journals: list[str] | None = None,
    path: Path | None = None,
) -> tuple[Path, Path]:
    """Compute and cache exact graph statistics for the combined network."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    markdown_path = path or (REPORTS_DIR / "network_stats.md")
    metrics_path = markdown_path.with_suffix(".json")
    scopes: list[str | None] = [None]
    selected = journals if journals is not None else sorted(JOURNAL_CODES)
    scopes.extend(selected)

    results: list[dict[str, Any]] = []
    now = _utcnow()
    for scope in scopes:
        graph = build_graph(conn, scope)
        stats = compute_stats(graph)
        stats["scope"] = scope or "ALL"
        stats["generated_at"] = now
        results.append(stats)
        conn.execute(
            """
            INSERT INTO network_statistics
                (scope, nodes, edges, components, largest_component, average_degree,
                 average_path_length, diameter, average_clustering, pairs,
                 details_json, generated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(scope) DO UPDATE SET
                nodes=excluded.nodes,
                edges=excluded.edges,
                components=excluded.components,
                largest_component=excluded.largest_component,
                average_degree=excluded.average_degree,
                average_path_length=excluded.average_path_length,
                diameter=excluded.diameter,
                average_clustering=excluded.average_clustering,
                pairs=excluded.pairs,
                details_json=excluded.details_json,
                generated_at=excluded.generated_at
            """,
            (
                stats["scope"],
                stats["nodes"],
                stats["edges"],
                stats["components"],
                stats["largest_component"],
                stats["average_degree"],
                stats["average_path_length"],
                stats["diameter"],
                stats["average_clustering"],
                stats["pairs"],
                json.dumps(
                    {"component_sizes": stats.get("component_sizes", [])},
                    ensure_ascii=False,
                ),
                now,
            ),
        )
    conn.commit()
    metrics_path.write_text(
        json.dumps({"generated_at": now, "scopes": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = [
        "# Coauthor network statistics",
        "",
        f"Generated {now}.",
        "",
        "The graph is an unweighted, undirected coauthorship network of canonical "
        "authors. One edge means two authors shared at least one research article; "
        "multiple shared papers do not shorten the path. Average path length and "
        "diameter are computed over unordered pairs in the largest connected "
        "component. Authors outside that component are reported separately and are "
        "not treated as infinitely distant.",
        "",
        _table(
            [
                "Scope",
                "Authors",
                "Ties",
                "Components",
                "Largest",
                "Avg. path",
                "Diameter",
                "Clustering",
            ],
            [
                (
                    row["scope"],
                    row["nodes"],
                    row["edges"],
                    row["components"],
                    row["largest_component"],
                    f"{row['average_path_length']:.2f}"
                    if row["average_path_length"] is not None
                    else "—",
                    row["diameter"] if row["diameter"] is not None else "—",
                    f"{row['average_clustering']:.3f}"
                    if row["average_clustering"] is not None
                    else "—",
                )
                for row in results
            ],
        ),
        "",
        "## Reading the numbers",
        "",
        "- **Average path** is the mean number of coauthorship steps between two "
        "authors in the largest component, not between all 10,000+ authors.",
        "- **Diameter** is the longest shortest path in that component.",
        "- **Clustering** is the mean local clustering coefficient: how often two "
        "coauthors of an author also coauthor with each other.",
        "- A journal scope uses only papers in that journal, so an author can have a "
        "different component and path length in each journal.",
        "",
    ]
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    return markdown_path, metrics_path

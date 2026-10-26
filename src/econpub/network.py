from __future__ import annotations

import sqlite3
from collections import defaultdict, deque
from typing import Any

JOURNAL_CODES = {"AER", "QJE", "JPE", "RES", "ECMA"}


def build_graph(
    conn: sqlite3.Connection, journal: str | None = None
) -> dict[int, set[int]]:
    """Undirected coauthorship graph, one edge per coauthored paper pair.

    The graph is unweighted for path purposes: each coauthored paper is one
    step, regardless of how many papers two authors share. Paper-level
    evidence is attached separately when a path is returned.
    """
    if journal:
        rows = conn.execute(
            """
            SELECT DISTINCT s1.author_id, s2.author_id
            FROM authorships s1
            JOIN authorships s2
              ON s1.paper_id=s2.paper_id AND s1.author_id < s2.author_id
            JOIN papers p ON p.paper_id=s1.paper_id
            WHERE p.content_type='article' AND p.is_duplicate=0
              AND p.journal_code=?
            """,
            (journal,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT DISTINCT author_a_id, author_b_id FROM coauthorship_edges"
        ).fetchall()
    adjacency: dict[int, set[int]] = defaultdict(set)
    for left, right in rows:
        a, b = int(left), int(right)
        if a == b:
            continue
        adjacency[a].add(b)
        adjacency[b].add(a)
    return adjacency


def graph_counts(adjacency: dict[int, set[int]]) -> tuple[int, int]:
    nodes = len(adjacency)
    edges = sum(len(neighbors) for neighbors in adjacency.values()) // 2
    return nodes, edges


def shortest_path(
    adjacency: dict[int, set[int]],
    source: int,
    target: int,
    *,
    max_depth: int = 10,
) -> list[int] | None:
    """Deterministic unweighted shortest path, or None if none within depth."""
    if source == target:
        return [source]
    if source not in adjacency or target not in adjacency:
        return None
    parent: dict[int, int | None] = {source: None}
    depth = {source: 0}
    queue: deque[int] = deque([source])
    while queue:
        node = queue.popleft()
        if depth[node] >= max_depth:
            continue
        for neighbor in sorted(adjacency[node]):
            if neighbor in parent:
                continue
            parent[neighbor] = node
            depth[neighbor] = depth[node] + 1
            if neighbor == target:
                path = [target]
                while parent[path[-1]] is not None:
                    path.append(parent[path[-1]])  # type: ignore[arg-type]
                return list(reversed(path))
            queue.append(neighbor)
    return None


def edge_papers(
    conn: sqlite3.Connection,
    left: int,
    right: int,
    *,
    journal: str | None = None,
    limit: int = 3,
) -> list[dict[str, Any]]:
    clause = " AND p.journal_code=?" if journal else ""
    params: list[Any] = [left, right]
    if journal:
        params.append(journal)
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT p.doi, p.title, p.published_year, p.journal_code
        FROM authorships s1
        JOIN authorships s2
          ON s1.paper_id=s2.paper_id AND s1.author_id=? AND s2.author_id=?
        JOIN papers p ON p.paper_id=s1.paper_id
        WHERE p.content_type='article' AND p.is_duplicate=0 {clause}
        ORDER BY p.published_year DESC, p.doi
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [
        {
            "doi": row["doi"],
            "title": row["title"],
            "year": row["published_year"],
            "journal": row["journal_code"] or "AER",
            "url": f"https://doi.org/{row['doi']}",
        }
        for row in rows
    ]


def compute_stats(adjacency: dict[int, set[int]]) -> dict[str, Any]:
    """Exact connected-component and all-pairs statistics for a graph.

    Average path length and diameter are computed over unordered pairs in the
    largest connected component. Authors outside that component are reported
    separately and are not silently treated as infinitely distant.
    """
    nodes, edges = graph_counts(adjacency)
    if not nodes:
        return {
            "nodes": 0,
            "edges": 0,
            "components": 0,
            "largest_component": 0,
            "average_degree": 0.0,
            "average_path_length": None,
            "diameter": None,
            "average_clustering": None,
            "pairs": 0,
        }

    seen: set[int] = set()
    components: list[list[int]] = []
    for start in sorted(adjacency):
        if start in seen:
            continue
        component: list[int] = []
        queue = deque([start])
        seen.add(start)
        while queue:
            node = queue.popleft()
            component.append(node)
            for neighbor in adjacency[node]:
                if neighbor not in seen:
                    seen.add(neighbor)
                    queue.append(neighbor)
        components.append(component)
    components.sort(key=len, reverse=True)
    largest = components[0]
    largest_set = set(largest)

    total_distance = 0
    pairs = 0
    diameter = 0
    for source in largest:
        distance = {source: 0}
        queue = deque([source])
        while queue:
            node = queue.popleft()
            for neighbor in adjacency[node]:
                if neighbor not in distance:
                    distance[neighbor] = distance[node] + 1
                    queue.append(neighbor)
        for target, value in distance.items():
            if target in largest_set and target != source:
                total_distance += value
                pairs += 1
                diameter = max(diameter, value)
    # Each unordered pair was counted twice (both directions).
    pairs //= 2
    average_path = total_distance / (2 * pairs) if pairs else None

    clustering_values: list[float] = []
    for node, neighbors in adjacency.items():
        if len(neighbors) < 2:
            continue
        neighbor_list = sorted(neighbors)
        links = 0
        for index, left in enumerate(neighbor_list):
            for right in neighbor_list[index + 1 :]:
                if right in adjacency[left]:
                    links += 1
        possible = len(neighbor_list) * (len(neighbor_list) - 1) / 2
        clustering_values.append(links / possible)
    average_clustering = (
        sum(clustering_values) / len(clustering_values) if clustering_values else None
    )

    return {
        "nodes": nodes,
        "edges": edges,
        "components": len(components),
        "largest_component": len(largest),
        "component_sizes": [len(component) for component in components[:10]],
        "average_degree": round(2 * edges / nodes, 3) if nodes else 0.0,
        "average_path_length": round(average_path, 4) if average_path is not None else None,
        "diameter": diameter,
        "average_clustering": round(average_clustering, 4)
        if average_clustering is not None
        else None,
        "pairs": pairs,
    }

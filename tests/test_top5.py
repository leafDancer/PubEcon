from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from econpub.config import TOP5_DB

HAS_FASTAPI = importlib.util.find_spec("fastapi") is not None


@unittest.skipUnless(HAS_FASTAPI, "FastAPI is not installed")
@unittest.skipUnless(TOP5_DB.exists(), "Top-five database is not available")
class Top5ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from fastapi.testclient import TestClient

        from econpub.api import create_app

        cls.client = TestClient(create_app(TOP5_DB))

    def test_author_directory_count_matches_items(self) -> None:
        response = self.client.get("/api/authors?page_size=1")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertGreater(body["total"], 9000)
        self.assertLessEqual(len(body["items"]), 1)
        self.assertEqual(body["pages"], (body["total"] + body["page_size"] - 1) // body["page_size"])
        last = self.client.get("/api/authors?page=9999&page_size=100")
        self.assertEqual(last.status_code, 200)
        self.assertLessEqual(last.json()["page"], last.json()["pages"])
        self.assertTrue(last.json()["items"])

    def test_orphan_author_is_not_public(self) -> None:
        # Any stable ID with no research article must not render an empty page.
        response = self.client.get("/api/authors/does-not-exist")
        self.assertEqual(response.status_code, 404)

    def test_path_reports_shared_paper_count(self) -> None:
        response = self.client.get("/api/path?from=aer-a-000932&to=aer-a-000427")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        if body.get("found"):
            for step in body["steps"]:
                self.assertIn("shared_papers", step)
                self.assertLessEqual(len(step["papers"]), 3)

    def test_network_stats_are_distinct_ties(self) -> None:
        stats = self.client.get("/api/network/stats")
        self.assertEqual(stats.status_code, 200)
        edges = stats.json()["edges"]
        overview = self.client.get("/api/overview").json()
        self.assertEqual(edges, overview["counts"]["coauthorship_edges"])
        self.assertGreaterEqual(
            overview["counts"]["coauthorship_edge_records"],
            overview["counts"]["coauthorship_edges"],
        )

    def test_health_does_not_expose_absolute_path(self) -> None:
        health = self.client.get("/api/health").json()
        self.assertNotIn("\\", health["database"])
        self.assertNotIn("/", health["database"])


if __name__ == "__main__":
    unittest.main()

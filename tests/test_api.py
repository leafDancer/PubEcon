from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from econpub.config import DB_PATH

HAS_FASTAPI = importlib.util.find_spec("fastapi") is not None
HAS_DB = DB_PATH.exists()


@unittest.skipUnless(HAS_FASTAPI, "FastAPI is not installed")
@unittest.skipUnless(HAS_DB, "Curated database is not available")
class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from fastapi.testclient import TestClient

        from econpub.api import create_app

        cls.client = TestClient(create_app(DB_PATH))

    def test_health_and_overview(self) -> None:
        health = self.client.get("/api/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["status"], "ok")
        overview = self.client.get("/api/overview")
        self.assertEqual(overview.status_code, 200)
        body = overview.json()
        self.assertGreater(body["counts"]["papers"], 4000)
        self.assertLess(body["counts"]["pp_papers"], body["counts"]["papers"])
        self.assertTrue(body["years"])
        self.assertTrue(body["dataset"]["journals"])
        self.assertEqual(body["dataset"]["journals"][0]["code"], "AER")
        self.assertIn("career_coverage", body["dataset"]["journals"][0])
        self.assertTrue(body["recent_papers"])
        self.assertTrue(body["recent_papers"][0].get("authors"))

    def test_paper_list_and_detail(self) -> None:
        listing = self.client.get("/api/papers?page_size=2")
        self.assertEqual(listing.status_code, 200)
        body = listing.json()
        self.assertEqual(len(body["items"]), 2)
        self.assertGreater(body["total"], 4000)
        self.assertIn("authors", body["items"][0])
        self.assertEqual(body["items"][0]["journal"], "AER")

        filtered = self.client.get("/api/papers?journal=AER&page_size=2")
        self.assertEqual(filtered.status_code, 200)
        self.assertTrue(all(item["journal"] == "AER" for item in filtered.json()["items"]))
        self.assertEqual(self.client.get("/api/papers?journal=NOPE").status_code, 422)

        doi = body["items"][0]["doi"]
        detail = self.client.get(f"/api/papers/{doi}")
        self.assertEqual(detail.status_code, 200)
        paper = detail.json()
        self.assertEqual(paper["doi"], doi)
        self.assertIn("authors", paper)
        self.assertIn("provenance", paper)

    def test_author_list_and_detail(self) -> None:
        listing = self.client.get("/api/authors?q=Acemoglu")
        self.assertEqual(listing.status_code, 200)
        body = listing.json()
        self.assertGreaterEqual(body["total"], 1)
        author = body["items"][0]
        self.assertIn("papers", author)
        self.assertIn("coverage", author)

        aer_only = self.client.get("/api/authors?q=Acemoglu&journal=AER")
        self.assertEqual(aer_only.status_code, 200)
        self.assertGreaterEqual(aer_only.json()["total"], 1)
        qje_only = self.client.get("/api/authors?q=Acemoglu&journal=QJE")
        self.assertEqual(qje_only.status_code, 200)
        self.assertEqual(qje_only.json()["total"], 0)

        detail = self.client.get(f"/api/authors/{author['stable_id']}")
        self.assertEqual(detail.status_code, 200)
        payload = detail.json()
        self.assertEqual(payload["stable_id"], author["stable_id"])
        self.assertIn("career_events", payload)
        self.assertIn("paper_list", payload)
        self.assertIn("coauthors", payload)

    def test_network_is_bounded(self) -> None:
        network = self.client.get("/api/network?limit=20&min_papers=2")
        self.assertEqual(network.status_code, 200)
        body = network.json()
        self.assertLessEqual(len(body["nodes"]), 20)
        self.assertIn("meta", body)
        self.assertIn("edges", body)

        filtered = self.client.get("/api/network?limit=20&min_papers=2&journal=AER")
        self.assertEqual(filtered.status_code, 200)
        self.assertEqual(filtered.json()["meta"]["journal"], "AER")
        self.assertLessEqual(
            filtered.json()["meta"]["total_authors"], body["meta"]["total_authors"]
        )
        self.assertEqual(self.client.get("/api/network?journal=NOPE").status_code, 422)

        ego = self.client.get("/api/authors/aer-a-000929/network?limit=5")
        self.assertEqual(ego.status_code, 200)
        ego_body = ego.json()
        self.assertEqual(ego_body["mode"], "ego")
        self.assertTrue(any(node["is_center"] for node in ego_body["nodes"]))

    def test_not_found(self) -> None:
        response = self.client.get("/api/papers/10.1257/does-not-exist")
        self.assertEqual(response.status_code, 404)
        self.assertIn("error", response.json())


if __name__ == "__main__":
    unittest.main()

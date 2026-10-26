from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from econpub import db
from econpub.classify import classify_papers
from econpub.config import DEFAULT_JOURNAL, JOURNALS
from econpub.crossref import parse_item
from econpub.top5_report import generate_top5_report


class JournalRegistryTests(unittest.TestCase):
    def test_top_five_registry(self) -> None:
        self.assertEqual(
            set(JOURNALS),
            {"AER", "QJE", "JPE", "RES", "ECMA"},
        )
        self.assertEqual(JOURNALS[DEFAULT_JOURNAL].issn, "0002-8282")
        self.assertEqual(JOURNALS["QJE"].issn, "0033-5533")
        self.assertEqual(JOURNALS["JPE"].issn, "0022-3808")
        self.assertEqual(JOURNALS["RES"].issn, "0034-6527")
        self.assertEqual(JOURNALS["ECMA"].issn, "0012-9682")

    def test_parse_item_carries_journal(self) -> None:
        item = {
            "DOI": "10.1093/qje/qjad001",
            "title": ["A Test Article"],
            "type": "journal-article",
            "container-title": ["The Quarterly Journal of Economics"],
            "ISSN": ["0033-5533"],
            "author": [
                {"given": "Jane", "family": "Doe", "sequence": "first"},
            ],
        }
        paper, authors, _topics = parse_item(item, journal_code="QJE")
        self.assertEqual(paper["journal_code"], "QJE")
        self.assertEqual(authors[0]["family_name"], "Doe")

    def test_migration_backfills_aer(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "test.db"
            conn = db.connect(path)
            db.init_db(conn)
            conn.execute(
                """
                INSERT INTO papers (doi, created_at, updated_at)
                VALUES ('10.1257/legacy', '2026-01-01', '2026-01-01')
                """
            )
            conn.commit()
            db.migrate_db(conn)
            row = conn.execute(
                "SELECT journal_code FROM papers WHERE doi='10.1257/legacy'"
            ).fetchone()
            self.assertEqual(row["journal_code"], "AER")
            conn.close()


class JournalClassificationTests(unittest.TestCase):
    def test_qje_editorial_matter_is_not_an_article(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "test.db"
            conn = db.connect(path)
            db.init_db(conn)
            rows = [
                ("10.1093/qje/issue", "journal-issue", None, None),
                ("10.1093/qje/erratum", "journal-article", "Erratum", None),
                ("10.1093/qje/announcement", "journal-article", "Announcement", None),
                ("10.1093/qje/board", "journal-article", "Editorial Board", None),
                ("10.1093/qje/article", "journal-article", "A Real Article", "Jane Doe"),
                ("10.1093/qje/book-review", "journal-article", "Book Review: A Book", "Jane Doe"),
                (
                    "10.1093/qje/announcements-research",
                    "journal-article",
                    "Announcements of Support and Public Good Provision",
                    "Jane Doe",
                ),
            ]
            for doi, item_type, title, author in rows:
                cursor = conn.execute(
                    """
                    INSERT INTO papers (doi, journal_code, item_type, title, created_at, updated_at)
                    VALUES (?, 'QJE', ?, ?, '2026-01-01', '2026-01-01')
                    """,
                    (doi, item_type, title),
                )
                if author:
                    conn.execute(
                        """
                        INSERT INTO authorships (paper_id, author_order, full_name)
                        VALUES (?, 1, ?)
                        """,
                        (cursor.lastrowid, author),
                    )
            conn.commit()
            classify_papers(conn)
            types = {
                row["doi"]: row["content_type"]
                for row in conn.execute("SELECT doi, content_type FROM papers")
            }
            self.assertEqual(types["10.1093/qje/issue"], "issue_metadata")
            self.assertEqual(types["10.1093/qje/erratum"], "erratum")
            self.assertEqual(types["10.1093/qje/announcement"], "front_matter")
            self.assertEqual(types["10.1093/qje/board"], "front_matter")
            self.assertEqual(types["10.1093/qje/article"], "article")
            self.assertEqual(types["10.1093/qje/book-review"], "book_review")
            self.assertEqual(types["10.1093/qje/announcements-research"], "article")
            conn.close()

    def test_duplicate_detection_is_journal_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "test.db"
            conn = db.connect(path)
            db.init_db(conn)
            for journal, doi in (("AER", "10.1257/aer.same"), ("QJE", "10.1093/qje.same")):
                cursor = conn.execute(
                    """
                    INSERT INTO papers
                        (doi, journal_code, item_type, title, volume, issue,
                         page_first, page_last, published_year, created_at, updated_at)
                    VALUES (?, ?, 'journal-article', 'Same Title', '1', '1',
                            '1', '10', 2020, '2026-01-01', '2026-01-01')
                    """,
                    (doi, journal),
                )
                conn.execute(
                    "INSERT INTO authorships (paper_id, author_order, full_name) VALUES (?, 1, 'Jane Doe')",
                    (cursor.lastrowid,),
                )
            conn.commit()
            classify_papers(conn)
            rows = conn.execute(
                "SELECT doi, content_type, is_duplicate FROM papers ORDER BY doi"
            ).fetchall()
            self.assertEqual([row["content_type"] for row in rows], ["article", "article"])
            self.assertEqual([row["is_duplicate"] for row in rows], [0, 0])
            conn.close()

    def test_top5_report_lists_each_journal(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp:
            path = Path(temp) / "test.db"
            conn = db.connect(path)
            db.init_db(conn)
            for journal, doi in (("AER", "10.1257/aer.1"), ("QJE", "10.1093/qje.1")):
                cursor = conn.execute(
                    """
                    INSERT INTO papers (doi, journal_code, title, created_at, updated_at)
                    VALUES (?, ?, 'A Paper', '2026-01-01', '2026-01-01')
                    """,
                    (doi, journal),
                )
                conn.execute(
                    "INSERT INTO authorships (paper_id, author_order, full_name) VALUES (?, 1, 'Jane Doe')",
                    (cursor.lastrowid,),
                )
            conn.commit()
            markdown, metrics = generate_top5_report(conn, path=Path(temp) / "report.md")
            text = markdown.read_text(encoding="utf-8")
            self.assertIn("| QJE |", text)
            self.assertIn("| AER |", text)
            self.assertTrue(metrics.exists())
            conn.close()


if __name__ == "__main__":
    unittest.main()

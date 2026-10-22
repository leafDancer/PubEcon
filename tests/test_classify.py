from __future__ import annotations

import json
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from econpub import db
from econpub.classify import classify_papers, link_retractions_from_crossref


class ClassifyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        db.init_db(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def _paper(self, doi, title, year, volume, issue, first, last, month=3):
        cursor = self.conn.execute(
            """
            INSERT INTO papers (
                doi, title, volume, issue, page_first, page_last,
                published_year, published_month, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'now', 'now')
            """,
            (doi, title, volume, issue, first, last, year, month),
        )
        return int(cursor.lastrowid)

    def _author(self, paper_id, order, given, family):
        self.conn.execute(
            """
            INSERT INTO authorships (
                paper_id, author_order, given_name, family_name, full_name
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (paper_id, order, given, family, f"{given} {family}".strip()),
        )

    def _doi_row(self, doi):
        return self.conn.execute("SELECT * FROM papers WHERE doi=?", (doi,)).fetchone()

    def test_admin_and_retraction_classification(self) -> None:
        self._paper("10.1257/aer.20100001", "Foreword", 2010, "100", "1", "i", "i")
        self._paper(
            "10.1257/aer.20100002",
            "Retraction of “A Study”",
            2010,
            "100",
            "1",
            "1",
            "2",
        )
        retracted_id = self._paper(
            "10.1257/aer.20100003",
            "RETRACTED BY THE AUTHORS: A Study",
            2010,
            "100",
            "1",
            "3",
            "20",
        )
        normal_id = self._paper("10.1257/aer.20100004", "A Normal Paper", 2010, "100", "1", "21", "40")
        self._author(retracted_id, 1, "Jane", "Doe")
        self._author(normal_id, 1, "John", "Smith")

        classify_papers(self.conn)

        self.assertEqual(self._doi_row("10.1257/aer.20100001")["content_type"], "association_report")
        self.assertEqual(self._doi_row("10.1257/aer.20100002")["content_type"], "retraction_notice")
        retracted = self._doi_row("10.1257/aer.20100003")
        self.assertEqual(retracted["content_type"], "article")
        self.assertEqual(retracted["retraction_status"], "retracted")
        self.assertEqual(self._doi_row("10.1257/aer.20100004")["content_type"], "article")

    def test_crossref_update_to_links_retraction(self) -> None:
        original = self._paper("10.1257/aer.20210369", "A Study", 2023, "113", "7", "1", "20")
        notice = self._paper(
            "10.1257/aer.113.7.2053", "Retraction of A Study", 2023, "113", "7", "21", "22"
        )
        payload = {
            "DOI": "10.1257/aer.113.7.2053",
            "update-to": [
                {
                    "DOI": "10.1257/aer.20210369",
                    "type": "retraction",
                    "label": "Retraction",
                }
            ],
        }
        self.conn.execute(
            """
            INSERT INTO source_records (source, source_key, fetched_at, payload_json)
            VALUES ('crossref', '10.1257/aer.113.7.2053', 'now', ?)
            """,
            (json.dumps(payload),),
        )

        self.assertEqual(link_retractions_from_crossref(self.conn), 1)
        original_row = self._doi_row("10.1257/aer.20210369")
        notice_row = self._doi_row("10.1257/aer.113.7.2053")
        self.assertEqual(original_row["retraction_status"], "retracted")
        self.assertEqual(original_row["retracted_by_paper_id"], notice)
        self.assertEqual(notice_row["content_type"], "retraction_notice")
        self.assertEqual(notice_row["retracts_paper_id"], original)

    def test_dedup_exact_aux_and_container(self) -> None:
        # Exact research duplicate: same title, issue, pages, author.
        a1 = self._paper("10.1257/aer.20110001", "A Study", 2011, "101", "1", "100", "110")
        a2 = self._paper("10.1257/000282811000000001", "A Study", 2011, "101", "1", "100", "110")
        self._author(a1, 1, "John", "Smith")
        self._author(a2, 1, "John", "Smith")

        # Same title but different pages and authors: must not merge.
        b1 = self._paper("10.1257/aer.20120001", "Comment", 2012, "102", "1", "200", "210")
        b2 = self._paper("10.1257/aer.20120002", "Comment", 2012, "102", "1", "220", "230")
        self._author(b1, 1, "Alice", "Jones")
        self._author(b2, 1, "Bob", "Brown")

        # Different administrative titles, same page and author: merge.
        c1 = self._paper("10.1257/aer.20130001", "Foreword", 2013, "103", "1", "ix", "ix")
        c2 = self._paper(
            "10.1257/aer.20130002", "Editor's Introduction", 2013, "103", "1", "ix", "ix"
        )
        self._author(c1, 1, "George", "Akerlof")
        self._author(c2, 1, "George", "Akerlof")

        # Whole-issue Front Matter contains the Foreword: must not merge.
        d1 = self._paper("10.1257/aer.20140001", "Front Matter", 2014, "104", "1", "i", "xiv")
        d2 = self._paper("10.1257/aer.20140002", "Foreword", 2014, "104", "1", "xi", "xii")

        classify_papers(self.conn)

        a1_row = self._doi_row("10.1257/aer.20110001")
        a2_row = self._doi_row("10.1257/000282811000000001")
        self.assertEqual({a1_row["is_duplicate"], a2_row["is_duplicate"]}, {0, 1})
        duplicate_row = a1_row if a1_row["is_duplicate"] else a2_row
        canonical_row = a2_row if a1_row["is_duplicate"] else a1_row
        self.assertEqual(duplicate_row["duplicate_of_paper_id"], canonical_row["paper_id"])

        self.assertEqual(self._doi_row("10.1257/aer.20120001")["is_duplicate"], 0)
        self.assertEqual(self._doi_row("10.1257/aer.20120002")["is_duplicate"], 0)

        c1_row = self._doi_row("10.1257/aer.20130001")
        c2_row = self._doi_row("10.1257/aer.20130002")
        self.assertEqual({c1_row["is_duplicate"], c2_row["is_duplicate"]}, {0, 1})

        self.assertEqual(self._doi_row("10.1257/aer.20140001")["is_duplicate"], 0)
        self.assertEqual(self._doi_row("10.1257/aer.20140002")["is_duplicate"], 0)


if __name__ == "__main__":
    unittest.main()

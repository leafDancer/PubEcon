from __future__ import annotations

import json
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from econpub import db
from econpub.authors import resolve_all_authors
from econpub.career import infer_byline_career
from econpub.identity import assign_stable_ids, ensure_identity_ledger
from econpub.review import resolve_merge_candidates, resolve_multi_id_authors


class M3TestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        db.init_db(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def add_paper(self, doi: str, year: int, title: str = "Title") -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO papers (doi, title, content_type, published_year, created_at, updated_at)
            VALUES (?, ?, 'article', ?, 'now', 'now')
            """,
            (doi, title, year),
        )
        return int(cursor.lastrowid)

    def add_author(self, name: str, given: str | None = None, family: str | None = None) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO authors
                (canonical_name, given_name, family_name, name_key, match_key,
                 resolution_method, resolution_confidence, created_at, updated_at)
            VALUES (?, ?, ?, '', '', 'name_key', 'medium', 'now', 'now')
            """,
            (name, given, family),
        )
        return int(cursor.lastrowid)

    def add_authorship(
        self,
        paper_id: int,
        author_id: int | None,
        *,
        order: int = 1,
        given: str | None = None,
        family: str | None = None,
        full: str | None = None,
        affiliation: str | None = None,
        rank_category: str | None = None,
        rank_raw: str | None = None,
        openalex_author_id: str | None = None,
        openalex_author_name: str | None = None,
        openalex_institution_name: str | None = None,
    ) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO authorships
                (paper_id, author_id, author_order, given_name, family_name, full_name,
                 affiliation_raw, institution_hint, rank_category, rank_raw,
                 openalex_author_id, openalex_author_name, openalex_institution_name)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                paper_id,
                author_id,
                order,
                given,
                family,
                full,
                affiliation,
                affiliation,
                rank_category,
                rank_raw,
                openalex_author_id,
                openalex_author_name,
                openalex_institution_name,
            ),
        )
        return int(cursor.lastrowid)


class StableIdentityTests(M3TestBase):
    def test_stable_id_survives_rebuild(self) -> None:
        paper = self.add_paper("10.1257/aer.1", 2001)
        author = self.add_author("Alice Example", "Alice", "Example")
        self.add_authorship(paper, author, given="Alice", family="Example", full="Alice Example")
        ensure_identity_ledger(self.conn)
        stable_before = self.conn.execute(
            "SELECT stable_id FROM authors WHERE author_id=?", (author,)
        ).fetchone()["stable_id"]
        self.assertTrue(stable_before)

        # Simulate a rebuild: detach and replace the author row, then reconcile.
        self.conn.execute("UPDATE authorships SET author_id=NULL")
        self.conn.execute("DELETE FROM authors")
        rebuilt = self.add_author("Alice Example", "Alice", "Example")
        self.conn.execute("UPDATE authorships SET author_id=?", (rebuilt,))
        stats = assign_stable_ids(self.conn)
        stable_after = self.conn.execute(
            "SELECT stable_id FROM authors WHERE author_id=?", (rebuilt,)
        ).fetchone()["stable_id"]
        self.assertEqual(stable_after, stable_before)
        self.assertEqual(stats["assigned"], 0)


class ReviewTests(M3TestBase):
    def test_resolve_merge_candidate(self) -> None:
        left = self.add_author("Kevin M Murphy")
        right = self.add_author("Kevin J Murphy")
        self.conn.execute(
            """
            INSERT INTO author_merge_candidates
                (author_id_a, author_id_b, reason, evidence, status, created_at)
            VALUES (?, ?, 'conflicting middle initials', ?, 'pending', 'now')
            """,
            (
                left,
                right,
                json.dumps(
                    {
                        "left_openalex_id": "A1",
                        "right_openalex_id": "A2",
                        "verdict": "different",
                    }
                ),
            ),
        )
        stats = resolve_merge_candidates(self.conn)
        self.assertEqual(stats["resolved_split"], 1)
        row = self.conn.execute("SELECT status FROM author_merge_candidates").fetchone()
        self.assertEqual(row["status"], "resolved_split")

    def test_split_john_morgan(self) -> None:
        paper1 = self.add_paper("10.1257/aer.1", 2001)
        paper2 = self.add_paper("10.1257/aer.2", 2008)
        paper3 = self.add_paper("10.1257/aer.3", 2009)
        author = self.add_author("John Morgan", "John", "Morgan")
        self.add_authorship(
            paper1,
            author,
            given="John",
            family="Morgan",
            full="John Morgan",
            openalex_author_id="A_PRINCETON",
            openalex_author_name="John W. Morgan",
            openalex_institution_name="Princeton University",
        )
        self.add_authorship(
            paper2,
            author,
            given="John",
            family="Morgan",
            full="John Morgan",
            openalex_author_id="A_BERKELEY",
            openalex_author_name="John M. Morgan",
            openalex_institution_name="University of California, Berkeley",
        )
        self.add_authorship(
            paper3,
            author,
            given="John",
            family="Morgan",
            full="John Morgan",
            affiliation="University of California, Berkeley",
            openalex_author_id=None,
            openalex_institution_name="University of California, Berkeley",
        )
        self.conn.execute(
            """
            INSERT INTO author_openalex_evidence
                (author_id, openalex_id, paper_count, first_year, last_year, institutions,
                 is_consistent, created_at)
            VALUES (?, 'A_PRINCETON', 1, 2001, 2001, 'Princeton University', 0, 'now')
            """,
            (author,),
        )
        self.conn.execute(
            """
            INSERT INTO author_openalex_evidence
                (author_id, openalex_id, paper_count, first_year, last_year, institutions,
                 is_consistent, created_at)
            VALUES (?, 'A_BERKELEY', 2, 2008, 2009,
                    'University of California, Berkeley', 0, 'now')
            """,
            (author,),
        )
        ensure_identity_ledger(self.conn)
        stats = resolve_multi_id_authors(self.conn)
        self.assertEqual(stats["split_authors"], 1)
        self.assertEqual(stats["new_authors"], 1)
        authors = self.conn.execute(
            "SELECT author_id, canonical_name, stable_id FROM authors ORDER BY author_id"
        ).fetchall()
        self.assertEqual(len(authors), 2)
        self.assertEqual(
            {row["canonical_name"] for row in authors},
            {"John M. Morgan", "John W. Morgan"},
        )
        stable_ids = {row["stable_id"] for row in authors}
        self.assertEqual(len(stable_ids), 2)
        rules = self.conn.execute("SELECT COUNT(*) FROM author_separation_rules").fetchone()[0]
        self.assertGreaterEqual(rules, 1)

        # A full author-table rebuild must honour the separation rules and
        # preserve both stable IDs.
        stable_before = {
            row["stable_id"]
            for row in self.conn.execute("SELECT stable_id FROM authors")
        }
        resolve_all_authors(self.conn)
        rebuilt = [
            dict(row)
            for row in self.conn.execute("SELECT canonical_name, stable_id FROM authors")
        ]
        self.assertEqual(len(rebuilt), 2)
        self.assertEqual({row["stable_id"] for row in rebuilt}, stable_before)


class CareerTests(M3TestBase):
    def test_byline_career(self) -> None:
        paper1 = self.add_paper("10.1257/aer.1", 2001)
        paper2 = self.add_paper("10.1257/aer.2", 2002)
        paper3 = self.add_paper("10.1257/aer.3", 2003)
        author = self.add_author("Alice Example")
        self.add_authorship(
            paper1,
            author,
            rank_category="assistant_professor",
            rank_raw="Assistant Professor",
        )
        self.add_authorship(
            paper2,
            author,
            affiliation="PhD student, Department of Economics, MIT",
        )
        self.add_authorship(paper3, author, affiliation="Department of Economics, MIT")
        stats = infer_byline_career(self.conn)
        self.assertEqual(stats["assigned"], 2)
        rows = self.conn.execute(
            "SELECT stage, evidence_type, confidence FROM career_assignments ORDER BY stage"
        ).fetchall()
        self.assertEqual(
            [(row["stage"], row["evidence_type"], row["confidence"]) for row in rows],
            [
                ("assistant_professor", "byline_rank", "high"),
                ("phd_student", "byline_affiliation", "medium"),
            ],
        )


if __name__ == "__main__":
    unittest.main()

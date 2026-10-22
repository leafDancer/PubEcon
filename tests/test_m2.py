from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from econpub import db
from econpub.aea import (
    apply_issue_calendar_rows,
    clean_truncated_aea_abstracts,
    fix_issue_months,
    parse_article_page,
    parse_issue_list,
)
from econpub.openalex import (
    _name_match,
    apply_author_links,
    clean_openalex_abstracts,
    is_boilerplate_abstract,
    match_authorships,
    merge_openalex_supported_authors,
    parse_work,
    reconstruct_abstract,
)
from econpub.pages import normalize_page_ranges

AEA_HTML = """<!doctype html>
<html><head>
<meta name="citation_title" content="Peers at Work">
<meta name="citation_doi" content="10.1257/aer.99.1.112">
<meta name="citation_journal_title" content="American Economic Review">
<meta name="citation_publication_date" content="2009/03">
<meta name="citation_volume" content="99">
<meta name="citation_issue" content="1">
<meta name="citation_firstpage" content="112">
<meta name="citation_lastpage" content="45">
<meta name="citation_author" content="Mas, Alexandre">
<meta name="citation_author" content="Moretti, Enrico">
<meta name="citation_author_institution" content="Princeton University">
<meta name="citation_author_institution" content="University of California, Berkeley">
<meta name="description" content="Peers at Work by Alexandre Mas and Enrico Moretti. Published in volume 99, issue 1, pages 112-45 of American Economic Review, March 2009, Abstract: We study peer effects.">
</head><body>
<section class="article-information abstract">
<h4>Abstract</h4>
We study peer effects in the workplace.
</section>
<section class='article-information jel-classification'>
<h4>JEL Classification</h4>
<ul class='jel-codes'>
<li><strong class='code'>J24</strong> Human Capital; Skills; Occupational Choice</li>
<li><strong class='code'>L81</strong> Retail and Wholesale Trade; e-Commerce</li>
</ul>
</section>
</body></html>
"""


class AEAParserTests(unittest.TestCase):
    def test_parse_article_page(self) -> None:
        parsed = parse_article_page(AEA_HTML, "10.1257/aer.99.1.112")
        self.assertEqual(parsed["doi"], "10.1257/aer.99.1.112")
        self.assertEqual(parsed["publication_year"], 2009)
        self.assertEqual(parsed["publication_month"], 3)
        self.assertEqual(parsed["publication_date"], "2009-03")
        self.assertEqual(parsed["volume"], "99")
        self.assertEqual(parsed["issue"], "1")
        self.assertEqual(parsed["first_page"], "112")
        self.assertEqual(parsed["last_page"], "45")
        self.assertEqual(parsed["abstract"], "We study peer effects in the workplace.")
        self.assertEqual(
            [entry["code"] for entry in parsed["jel"]], ["J24", "L81"]
        )
        self.assertIn("Princeton University", parsed["author_institutions"])


class IssueCalendarTests(unittest.TestCase):
    HTML = """
    <a href='/issues/155'>March 2000 (Vol. 90, No. 1)</a>
    <a href='/issues/154'>May 2000 (Vol. 90, No. 2)</a>
    <a href='/issues/153'>June 2000 (Vol. 90, No. 3)</a>
    """

    def test_parse_issue_list(self) -> None:
        rows = parse_issue_list(self.HTML)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["volume"], "90")
        self.assertEqual(rows[0]["issue"], "1")
        self.assertEqual(rows[0]["month"], 3)

    def test_combined_issue_range(self) -> None:
        rows = parse_issue_list(
            "<a href='/issues/503'>April 2018 (Vol. 108, No. 4-5)</a>"
        )
        self.assertEqual({row["issue"] for row in rows}, {"4-5", "4", "5"})
        self.assertTrue(all(row["month"] == 4 for row in rows))

    def test_apply_rows(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        db.init_db(conn)
        conn.execute(
            """
            INSERT INTO papers (doi, title, content_type, volume, issue,
                                published_year, published_month, published_date,
                                date_source, created_at, updated_at)
            VALUES ('10.1257/aer.1', 'Title', 'article', '90', '2', 2000, 4, '2000-04',
                    'crossref', 'now', 'now')
            """
        )
        stats = apply_issue_calendar_rows(conn, parse_issue_list(self.HTML))
        self.assertEqual(stats["updated"], 1)
        row = conn.execute(
            "SELECT published_month, published_date, date_source FROM papers"
        ).fetchone()
        self.assertEqual(row["published_month"], 5)
        self.assertEqual(row["published_date"], "2000-05")
        self.assertEqual(row["date_source"], "aea_issue_calendar")
        conn.close()


class IssueMonthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        db.init_db(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def _paper(self, doi, year, volume, issue, month, content_type="article"):
        cursor = self.conn.execute(
            """
            INSERT INTO papers (
                doi, title, content_type, volume, issue,
                published_year, published_month, published_date,
                date_source, created_at, updated_at
            ) VALUES (?, 'Title', ?, ?, ?, ?, ?, ?, 'crossref', 'now', 'now')
            """,
            (doi, content_type, volume, issue, year, month, f"{year:04d}-{month:02d}"),
        )
        return int(cursor.lastrowid)

    def test_issue_metadata_and_calendar_fallbacks(self) -> None:
        self._paper("10.1257/aer.2004.94.issue-4", 2004, "94", "4", 9, "issue_metadata")
        self._paper("10.1257/aer.2004.94.issue-5", 2004, "94", "5", 12, "issue_metadata")
        self._paper("10.1257/aer.2004.1", 2004, "94", "4", 9)  # already correct
        self._paper("10.1257/aer.2004.2", 2004, "94", "5", 11)  # metadata fixes to 12
        self._paper("10.1257/aer.2008.1", 2008, "98", "2", 4)  # calendar fixes to 5

        stats = fix_issue_months(self.conn)
        self.assertEqual(stats["corrected_issue_metadata"], 1)
        self.assertEqual(stats["corrected_calendar"], 1)

        row = self.conn.execute(
            "SELECT published_month, date_source, date_confidence FROM papers WHERE doi='10.1257/aer.2004.2'"
        ).fetchone()
        self.assertEqual(row["published_month"], 12)
        self.assertEqual(row["date_source"], "crossref_issue_metadata")
        self.assertEqual(row["date_confidence"], "high")

        row = self.conn.execute(
            "SELECT published_month, date_source FROM papers WHERE doi='10.1257/aer.2008.1'"
        ).fetchone()
        self.assertEqual(row["published_month"], 5)
        self.assertEqual(row["date_source"], "aer_issue_calendar")


SAMPLE_WORK = {
    "id": "https://openalex.org/W123456789",
    "doi": "https://doi.org/10.1257/aer.20120555",
    "title": "CoVaR",
    "publication_date": "2016-07-01",
    "publication_year": 2016,
    "cited_by_count": 2388,
    "type": "article",
    "primary_location": {"source": {"id": "https://openalex.org/S23254222", "display_name": "American Economic Review"}},
    "authorships": [
        {
            "author": {
                "id": "https://openalex.org/A5079166372",
                "display_name": "Tobias Adrian",
                "orcid": "https://orcid.org/0000-0001-9379-9592",
            },
            "author_position": "first",
            "is_corresponding": True,
            "institutions": [
                {
                    "id": "https://openalex.org/I43638361",
                    "display_name": "Federal Reserve Bank of New York",
                    "country_code": "US",
                    "ror": "https://ror.org/01abc",
                    "type": "government",
                }
            ],
            "raw_affiliation_strings": ["Federal Reserve Bank of New York"],
        }
    ],
    "topics": [
        {
            "id": "https://openalex.org/T10127",
            "display_name": "Banking stability, regulation, efficiency",
            "score": 0.8,
        }
    ],
    "primary_topic": {"id": "https://openalex.org/T10127"},
    "abstract_inverted_index": {"CoVaR": [0], "measures": [1], "risk": [2]},
    "biblio": {"volume": "106", "issue": "7"},
}


class OpenAlexParsingTests(unittest.TestCase):
    def test_reconstruct_abstract(self) -> None:
        self.assertEqual(
            reconstruct_abstract({"We": [0], "study": [1], "peers": [2]}),
            "We study peers",
        )
        self.assertIsNone(reconstruct_abstract(None))

    def test_parse_work(self) -> None:
        parsed = parse_work(SAMPLE_WORK)
        self.assertEqual(parsed["openalex_id"], "W123456789")
        self.assertEqual(parsed["doi"], "10.1257/aer.20120555")
        self.assertEqual(parsed["cited_by_count"], 2388)
        self.assertEqual(parsed["source_id"], "S23254222")
        self.assertEqual(parsed["abstract"], "CoVaR measures risk")
        self.assertEqual(parsed["authorships"][0]["openalex_author_id"], "A5079166372")
        self.assertEqual(
            parsed["authorships"][0]["institutions"][0]["openalex_id"], "I43638361"
        )
        self.assertEqual(parsed["topics"][0]["is_primary"], 1)

    def test_name_matching_variants(self) -> None:
        cases = [
            ({"full_name": "Markus Brunnermeier", "given_name": "Markus", "family_name": "Brunnermeier"}, "Markus Konrad Brunnermeier"),
            ({"full_name": "Pedro Dal Bó", "given_name": "Pedro", "family_name": "Dal Bó"}, "Pedro Dal Bo"),
            ({"full_name": "V. V Chari", "given_name": "V. V", "family_name": "Chari"}, "Varadarajan V. Chari"),
        ]
        for row, oa_name in cases:
            compatible, _ = _name_match(row, oa_name)
            self.assertTrue(compatible, msg=f"{row['full_name']} vs {oa_name}")

    def test_position_matching(self) -> None:
        ours = [
            {"full_name": "Tobias Adrian", "given_name": "Tobias", "family_name": "Adrian"},
            {"full_name": "Markus Brunnermeier", "given_name": "Markus", "family_name": "Brunnermeier"},
        ]
        oa = [
            {"author_name": "Tobias Adrian"},
            {"author_name": "Markus Konrad Brunnermeier"},
        ]
        matches = match_authorships(ours, oa)
        self.assertEqual(len(matches), 2)
        self.assertEqual(matches[0][2], "position_name")


class AbstractCleanupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        db.init_db(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def test_boilerplate_detection(self) -> None:
        self.assertTrue(
            is_boilerplate_abstract(
                "A Reply by X. Published in volume 108, issue 10, pages 3114-15 "
                "of American Economic Review, October 2018"
            )
        )
        self.assertFalse(is_boilerplate_abstract("We study peer effects in the workplace."))

    def test_cleanup_prefers_aea(self) -> None:
        self.conn.execute(
            """
            INSERT INTO papers (doi, title, content_type, abstract, abstract_available,
                                abstract_source, abstract_openalex, abstract_aea,
                                created_at, updated_at)
            VALUES ('10.1257/aer.1', 'Title', 'article', 'bad', 1, 'openalex',
                    'Published in volume 108 of American Economic Review', 'Good AEA abstract',
                    'now', 'now')
            """
        )
        self.conn.execute(
            """
            INSERT INTO papers (doi, title, content_type, abstract, abstract_available,
                                abstract_source, abstract_openalex,
                                created_at, updated_at)
            VALUES ('10.1257/aer.2', 'Title', 'article', 'bad', 1, 'openalex',
                    'Published in volume 108 of American Economic Review',
                    'now', 'now')
            """
        )
        stats = clean_openalex_abstracts(self.conn)
        self.assertEqual(stats["recovered_from_aea"], 1)
        self.assertEqual(stats["cleared"], 1)
        first = self.conn.execute(
            "SELECT abstract, abstract_source FROM papers WHERE doi='10.1257/aer.1'"
        ).fetchone()
        self.assertEqual(first["abstract"], "Good AEA abstract")
        self.assertEqual(first["abstract_source"], "aea")
        second = self.conn.execute(
            "SELECT abstract, abstract_available FROM papers WHERE doi='10.1257/aer.2'"
        ).fetchone()
        self.assertIsNone(second["abstract"])
        self.assertEqual(second["abstract_available"], 0)


class AEAAbstractCleanupTests(unittest.TestCase):
    def test_truncated_abstracts(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        db.init_db(conn)
        conn.execute(
            """
            INSERT INTO papers (doi, title, content_type, abstract, abstract_available,
                                abstract_source, abstract_openalex, created_at, updated_at)
            VALUES ('10.1257/aer.1', 'Title', 'article', 'Truncated...', 1, 'aea', NULL,
                    'now', 'now')
            """
        )
        conn.execute(
            """
            INSERT INTO papers (doi, title, content_type, abstract, abstract_available,
                                abstract_source, abstract_openalex, created_at, updated_at)
            VALUES ('10.1257/aer.2', 'Title', 'article', 'Truncated...', 1, 'aea',
                    'Full OpenAlex abstract', 'now', 'now')
            """
        )
        stats = clean_truncated_aea_abstracts(conn)
        self.assertEqual(stats["cleared"], 1)
        self.assertEqual(stats["replaced_from_openalex"], 1)
        first = conn.execute(
            "SELECT abstract, abstract_available FROM papers WHERE doi='10.1257/aer.1'"
        ).fetchone()
        self.assertIsNone(first["abstract"])
        self.assertEqual(first["abstract_available"], 0)
        second = conn.execute(
            "SELECT abstract, abstract_source FROM papers WHERE doi='10.1257/aer.2'"
        ).fetchone()
        self.assertEqual(second["abstract"], "Full OpenAlex abstract")
        self.assertEqual(second["abstract_source"], "openalex")
        conn.close()


class PageRangeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        db.init_db(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def _paper(self, doi, first, last):
        self.conn.execute(
            """
            INSERT INTO papers (doi, title, content_type, page_first, page_last,
                                published_year, created_at, updated_at)
            VALUES (?, 'Title', 'article', ?, ?, 2009, 'now', 'now')
            """,
            (doi, first, last),
        )

    def test_expand_and_validate(self) -> None:
        self._paper("10.1257/aer.1", "1705", "41")
        self._paper("10.1257/aer.2", "123", "122")
        stats = normalize_page_ranges(self.conn)
        self.assertEqual(stats["changed"], 1)
        self.assertEqual(stats["reversed_ranges"], 1)
        row = self.conn.execute(
            "SELECT page_last FROM papers WHERE doi='10.1257/aer.1'"
        ).fetchone()
        self.assertEqual(row["page_last"], "1741")


class AuthorLinkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        db.init_db(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def _author(self, name):
        cursor = self.conn.execute(
            """
            INSERT INTO authors (canonical_name, name_key, match_key, resolution_method,
                                 resolution_confidence, created_at, updated_at)
            VALUES (?, '', '', 'name_key', 'medium', 'now', 'now')
            """,
            (name,),
        )
        return int(cursor.lastrowid)

    def _paper(self, doi, year, author_ids):
        cursor = self.conn.execute(
            """
            INSERT INTO papers (doi, title, content_type, published_year, created_at, updated_at)
            VALUES (?, 'Title', 'article', ?, 'now', 'now')
            """,
            (doi, year),
        )
        paper_id = int(cursor.lastrowid)
        for order, author_id in enumerate(author_ids, start=1):
            self.conn.execute(
                """
                INSERT INTO authorships (paper_id, author_id, author_order, full_name, openalex_author_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (paper_id, author_id, order, f"Author {author_id}", "A999"),
            )
        return paper_id

    def test_shared_openalex_id_creates_candidate(self) -> None:
        left = self._author("John A Smith")
        right = self._author("John Smith")
        self._paper("10.1257/aer.1", 2001, [left])
        self._paper("10.1257/aer.2", 2005, [right])

        stats = apply_author_links(self.conn)
        self.assertEqual(stats["shared_openalex_ids"], 1)
        self.assertEqual(stats["new_merge_candidates"], 1)
        candidate = self.conn.execute(
            "SELECT reason, evidence FROM author_merge_candidates"
        ).fetchone()
        self.assertIn("OpenAlex", candidate["reason"])
        self.assertIn("A999", candidate["evidence"])

    def test_openalex_supported_merge(self) -> None:
        left = self._author("Steven D Levitt")
        right = self._author("S Levitt")
        self._paper("10.1257/aer.1", 2001, [left])
        self._paper("10.1257/aer.2", 2002, [right])

        apply_author_links(self.conn)
        stats = merge_openalex_supported_authors(self.conn)
        self.assertEqual(stats["merged"], 1)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM authors").fetchone()[0], 1
        )
        author_ids = {
            row["author_id"]
            for row in self.conn.execute("SELECT author_id FROM authorships")
        }
        self.assertEqual(len(author_ids), 1)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM author_merge_candidates").fetchone()[0],
            0,
        )
        ledger = dict(
            self.conn.execute(
                "SELECT status, COUNT(*) FROM author_identity_ledger GROUP BY status"
            ).fetchall()
        )
        self.assertEqual(ledger.get("active"), 1)
        self.assertEqual(ledger.get("merged"), 1)
        event_types = {
            row[0]
            for row in self.conn.execute(
                "SELECT DISTINCT event_type FROM author_identity_events"
            )
        }
        self.assertIn("merged", event_types)


if __name__ == "__main__":
    unittest.main()

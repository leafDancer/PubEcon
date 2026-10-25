from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from econpub import db
from econpub.career import assign_cv_careers, assign_orcid_careers
from econpub.cv import extract_cv_events
from econpub.orcid import (
    _apply_orcid_assessment,
    _assessment_score,
    _name_compatible,
    _person_names,
    assess_orcid_identity,
    parse_orcid_record,
    upsert_orcid_events,
)

ORCID_PAYLOAD = {
    "activities-summary": {
        "employments": {
            "affiliation-group": [
                {
                    "summaries": [
                        {
                            "employment-summary": {
                                "put-code": 1,
                                "role-title": "Assistant Professor",
                                "department-name": "Economics",
                                "organization": {"name": "Massachusetts Institute of Technology"},
                                "start-date": {"year": {"value": "2015"}, "month": None, "day": None},
                                "end-date": {"year": {"value": "2019"}, "month": None, "day": None},
                            }
                        }
                    ]
                }
            ]
        },
        "educations": {
            "affiliation-group": [
                {
                    "summaries": [
                        {
                            "education-summary": {
                                "put-code": 2,
                                "role-title": "PhD",
                                "department-name": "Economics",
                                "organization": {"name": "Harvard University"},
                                "start-date": {"year": {"value": "2010"}, "month": None, "day": None},
                                "end-date": {"year": {"value": "2015"}, "month": None, "day": None},
                            }
                        }
                    ]
                }
            ]
        },
    }
}


class ORCIDParsingTests(unittest.TestCase):
    def test_parse_record(self) -> None:
        events = parse_orcid_record(ORCID_PAYLOAD, "0000-0000-0000-0001")
        self.assertEqual(len(events), 2)
        employment = next(event for event in events if event["event_type"] == "employment")
        education = next(event for event in events if event["event_type"] == "education")
        self.assertEqual(employment["title"], "Assistant Professor")
        self.assertEqual(employment["start_year"], 2015)
        self.assertEqual(employment["end_year"], 2019)
        self.assertEqual(employment["confidence"], "high")
        self.assertEqual(education["title"], "PhD")
        self.assertEqual(education["start_year"], 2010)
        self.assertNotEqual(employment["event_key"], education["event_key"])

    def test_name_compatibility(self) -> None:
        self.assertTrue(_name_compatible("Daron Acemoglu", "Daron Acemoglu"))
        self.assertTrue(_name_compatible("John W. Morgan", "John Morgan"))
        self.assertTrue(_name_compatible("Daron Acemoglu", "K. Daron Acemoglu"))
        self.assertTrue(_name_compatible("William Darity", "William Darity Jr"))
        self.assertTrue(_name_compatible("Bill Dupor", "William Dupor"))
        self.assertTrue(_name_compatible("Simon Gächter", "Simon Gaechter"))
        self.assertTrue(_name_compatible("Doug Staiger", "Douglas Staiger"))
        self.assertFalse(_name_compatible("John Smith", "Jane Smith"))
        self.assertFalse(_name_compatible("B. Douglas Bernheim", "Bekkah Bernheim"))

    def test_person_name_variants(self) -> None:
        payload = {
            "person": {
                "name": {
                    "given-names": {"value": "K."},
                    "family-name": {"value": "Acemoglu"},
                    "credit-name": {"value": "K. Daron Acemoglu"},
                },
                "other-names": {
                    "other-name": [{"value": "Daron Acemoglu"}]
                },
            }
        }
        names = _person_names(payload)
        self.assertIn("K. Acemoglu", names)
        self.assertIn("K. Daron Acemoglu", names)
        self.assertIn("Daron Acemoglu", names)


class CareerAssignmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        db.init_db(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def _paper(self, doi, year):
        return int(
            self.conn.execute(
                """
                INSERT INTO papers (doi, title, content_type, published_year, created_at, updated_at)
                VALUES (?, 'Title', 'article', ?, 'now', 'now')
                """,
                (doi, year),
            ).lastrowid
        )

    def _author(self, name):
        return int(
            self.conn.execute(
                """
                INSERT INTO authors (canonical_name, name_key, match_key,
                                    resolution_method, resolution_confidence,
                                    created_at, updated_at)
                VALUES (?, '', '', 'name_key', 'medium', 'now', 'now')
                """,
                (name,),
            ).lastrowid
        )

    def _authorship(self, paper_id, author_id):
        return int(
            self.conn.execute(
                """
                INSERT INTO authorships (paper_id, author_id, author_order, full_name)
                VALUES (?, ?, 1, 'Author')
                """,
                (paper_id, author_id),
            ).lastrowid
        )

    def _event(self, author_id, event_type, title, start, end, source_type):
        return int(
            self.conn.execute(
                """
                INSERT INTO career_events
                    (author_id, event_type, title, institution, start_year, end_year,
                     is_current, source_url, source_type, confidence, created_at)
                VALUES (?, ?, ?, 'University', ?, ?, 0, 'https://example.org', ?, 'high', 'now')
                """,
                (author_id, event_type, title, start, end, source_type),
            ).lastrowid
        )

    def test_orcid_employment_and_education(self) -> None:
        author = self._author("Alice Example")
        paper = self._paper("10.1257/aer.1", 2016)
        self._authorship(paper, author)
        self._event(author, "employment", "Assistant Professor", 2015, 2019, "orcid")
        education_paper = self._paper("10.1257/aer.2", 2013)
        self._authorship(education_paper, author)
        self._event(author, "education", "PhD", 2010, 2015, "orcid")

        stats = assign_orcid_careers(self.conn)
        self.assertEqual(stats["assigned"], 2)
        rows = self.conn.execute(
            "SELECT stage, evidence_type FROM career_assignments ORDER BY stage"
        ).fetchall()
        self.assertEqual(
            [(row["stage"], row["evidence_type"]) for row in rows],
            [
                ("assistant_professor", "orcid_employment"),
                ("phd_student", "orcid_education"),
            ],
        )

    def test_cv_assignment_does_not_override_orcid(self) -> None:
        author = self._author("Alice Example")
        paper = self._paper("10.1257/aer.1", 2016)
        self._authorship(paper, author)
        self._event(author, "employment", "Assistant Professor", 2015, 2019, "orcid")
        self._event(author, "employment", "Associate Professor", 2015, 2019, "cv")
        assign_orcid_careers(self.conn)
        assign_cv_careers(self.conn)
        row = self.conn.execute("SELECT stage, evidence_type FROM career_assignments").fetchone()
        self.assertEqual(row["stage"], "assistant_professor")
        self.assertEqual(row["evidence_type"], "orcid_employment")


def _orcid_payload(*, employments=(), educations=(), works=()):
    def affiliation(event_type, rows):
        summaries = []
        for row in rows:
            summary = {
                "put-code": row.get("put_code", 1),
                "role-title": row.get("title"),
                "department-name": row.get("department"),
                "organization": {"name": row.get("institution")},
                "start-date": {"year": {"value": str(row["start"])}} if row.get("start") else None,
                "end-date": {"year": {"value": str(row["end"])}} if row.get("end") else None,
            }
            summaries.append({f"{event_type}-summary": summary})
        return {"affiliation-group": [{"summaries": summaries}]} if summaries else {}

    work_groups = []
    for work in works:
        external_ids = []
        if work.get("doi"):
            external_ids.append(
                {"external-id-type": "doi", "external-id-value": work["doi"]}
            )
        work_groups.append(
            {
                "work-summary": [
                    {
                        "title": {"title": {"value": work.get("title", "")}},
                        "journal-title": {"value": work.get("journal", "")},
                        "external-ids": {"external-id": external_ids},
                    }
                ]
            }
        )
    return {
        "person": {
            "name": {
                "given-names": {"value": "Alice"},
                "family-name": {"value": "Example"},
            }
        },
        "activities-summary": {
            "employments": affiliation("employment", employments),
            "educations": affiliation("education", educations),
            "works": {"group": work_groups},
        },
    }


class ORCIDIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        db.init_db(self.conn)
        self.author_id = int(
            self.conn.execute(
                """
                INSERT INTO authors (canonical_name, name_key, match_key,
                                    resolution_method, resolution_confidence,
                                    created_at, updated_at)
                VALUES ('Alice Example', '', 'example|alice', 'name_key', 'medium',
                        'now', 'now')
                """
            ).lastrowid
        )
        self.paper_id = int(
            self.conn.execute(
                """
                INSERT INTO papers (doi, title, content_type, published_year,
                                    created_at, updated_at)
                VALUES ('10.1257/aer.1', 'A Test Paper', 'article', 2015, 'now', 'now')
                """
            ).lastrowid
        )
        self.conn.execute(
            """
            INSERT INTO authorships (paper_id, author_id, author_order, full_name)
            VALUES (?, ?, 1, 'Alice Example')
            """,
            (self.paper_id, self.author_id),
        )

    def tearDown(self) -> None:
        self.conn.close()

    def test_doi_match_is_verified_high(self) -> None:
        payload = _orcid_payload(
            works=[{"title": "A Test Paper", "doi": "10.1257/aer.1"}]
        )
        result = assess_orcid_identity(
            self.conn, self.author_id, payload, "0000-0000-0000-0001"
        )
        self.assertEqual(result["status"], "verified_doi")
        self.assertEqual(result["confidence"], "high")

    def test_title_match_is_verified_high(self) -> None:
        payload = _orcid_payload(works=[{"title": "A Test Paper"}])
        result = assess_orcid_identity(
            self.conn, self.author_id, payload, "0000-0000-0000-0002"
        )
        self.assertEqual(result["status"], "verified_title")
        self.assertEqual(result["confidence"], "high")

    def test_institution_overlap_is_verified_medium(self) -> None:
        self.conn.execute(
            "UPDATE authorships SET institution_hint='Massachusetts Institute of Technology'"
        )
        payload = _orcid_payload(
            employments=[
                {
                    "title": "Assistant Professor",
                    "department": "Economics",
                    "institution": "MIT",
                    "start": 2010,
                    "end": 2018,
                }
            ]
        )
        result = assess_orcid_identity(
            self.conn, self.author_id, payload, "0000-0000-0000-0003"
        )
        self.assertEqual(result["status"], "verified_institution")
        self.assertEqual(result["confidence"], "medium")

    def test_economics_affiliation_is_low_confidence(self) -> None:
        payload = _orcid_payload(
            employments=[
                {
                    "title": "Assistant Professor",
                    "department": "Department of Economics",
                    "institution": "Example University",
                    "start": 2010,
                    "end": 2018,
                }
            ]
        )
        result = assess_orcid_identity(
            self.conn, self.author_id, payload, "0000-0000-0000-0004"
        )
        self.assertEqual(result["status"], "field_economics")
        self.assertEqual(result["confidence"], "low")

    def test_non_economics_field_is_rejected(self) -> None:
        payload = _orcid_payload(
            employments=[
                {
                    "title": "Clinical Professor",
                    "department": "Neurology",
                    "institution": "Example Hospital",
                    "start": 2010,
                    "end": 2018,
                }
            ],
            works=[{"title": "Cardiology outcomes", "journal": "Heart"}],
        )
        result = assess_orcid_identity(
            self.conn, self.author_id, payload, "0000-0000-0000-0005"
        )
        self.assertEqual(result["status"], "rejected_field")

    def test_career_risk_without_identity_evidence_is_rejected(self) -> None:
        payload = _orcid_payload(
            employments=[
                {
                    "title": "Assistant Professor",
                    "department": "Computer Applications",
                    "institution": "Example College",
                    "start": 2012,
                    "end": 2020,
                }
            ]
        )
        result = assess_orcid_identity(
            self.conn, self.author_id, payload, "0000-0000-0000-0006"
        )
        self.assertEqual(result["status"], "rejected_career_risk")
        status, inserted = _apply_orcid_assessment(
            self.conn,
            "https://orcid.org/0000-0000-0000-0006",
            payload,
            [self.author_id],
        )
        self.assertEqual(status, "rejected_career_risk")
        self.assertEqual(inserted, 0)
        author = self.conn.execute(
            "SELECT orcid, review_status FROM authors WHERE author_id=?",
            (self.author_id,),
        ).fetchone()
        self.assertIsNone(author["orcid"])
        self.assertEqual(author["review_status"], "orcid_unverified_career_risk")
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM career_events WHERE author_id=?",
                (self.author_id,),
            ).fetchone()[0],
            0,
        )

    def test_unverified_without_risk_keeps_orcid_but_withholds_events(self) -> None:
        payload = _orcid_payload(
            employments=[
                {
                    "title": "Research Fellow",
                    "department": "",
                    "institution": "Example Institute",
                    "start": 2020,
                    "end": None,
                }
            ]
        )
        status, inserted = _apply_orcid_assessment(
            self.conn,
            "https://orcid.org/0000-0000-0000-0007",
            payload,
            [self.author_id],
        )
        self.assertEqual(status, "unverified")
        self.assertEqual(inserted, 0)
        author = self.conn.execute(
            "SELECT orcid, orcid_source, review_status FROM authors WHERE author_id=?",
            (self.author_id,),
        ).fetchone()
        self.assertEqual(author["orcid"], "https://orcid.org/0000-0000-0000-0007")
        self.assertEqual(author["orcid_source"], "orcid_unverified")
        self.assertEqual(author["review_status"], "orcid_unverified")
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM career_events WHERE author_id=?",
                (self.author_id,),
            ).fetchone()[0],
            0,
        )

    def test_assessment_score_prefers_verified_links(self) -> None:
        verified = {
            "status": "verified_doi",
            "doi_overlap": ["10.1257/aer.1"],
            "title_overlap": [],
            "event_count": 3,
        }
        unverified = {
            "status": "unverified",
            "doi_overlap": [],
            "title_overlap": [],
            "event_count": 5,
        }
        rejected = {
            "status": "rejected_name",
            "doi_overlap": [],
            "title_overlap": [],
            "event_count": 6,
        }
        self.assertGreater(_assessment_score(verified), _assessment_score(unverified))
        self.assertGreater(_assessment_score(unverified), _assessment_score(rejected))

    def test_confidence_cap(self) -> None:
        events = parse_orcid_record(
            _orcid_payload(
                employments=[
                    {
                        "title": "Associate Professor",
                        "department": "Economics",
                        "institution": "Example University",
                        "start": 2010,
                        "end": 2020,
                    }
                ]
            ),
            "0000-0000-0000-0008",
        )
        upsert_orcid_events(
            self.conn,
            self.author_id,
            "0000-0000-0000-0008",
            events,
            confidence_cap="low",
        )
        row = self.conn.execute(
            "SELECT confidence FROM career_events WHERE author_id=?",
            (self.author_id,),
        ).fetchone()
        self.assertEqual(row["confidence"], "low")


class CVExtractionTests(unittest.TestCase):
    def test_sections_and_dates(self) -> None:
        text = """
        EDUCATION
        Ph.D. in Economics, Harvard University, 2010
        M.A. in Economics, University of York, 2005

        EMPLOYMENT
        Assistant Professor, Massachusetts Institute of Technology, 2010-2015
        Associate Professor, Massachusetts Institute of Technology, 2015-Present

        PUBLICATIONS
        A Paper, American Economic Review, 2018
        """
        events = extract_cv_events(
            text,
            ["Harvard University", "University of York", "Massachusetts Institute of Technology"],
        )
        self.assertEqual(len(events), 4)
        employment = [event for event in events if event["event_type"] == "employment"]
        self.assertEqual(len(employment), 2)
        self.assertEqual(employment[0]["start_year"], 2010)
        self.assertEqual(employment[0]["end_year"], 2015)
        self.assertEqual(employment[1]["start_year"], 2015)
        self.assertIsNone(employment[1]["end_year"])
        self.assertEqual(employment[1]["is_current"], 1)
        education = [event for event in events if event["event_type"] == "education"]
        self.assertEqual(len(education), 2)
        self.assertEqual(education[0]["start_year"], 2010)


if __name__ == "__main__":
    unittest.main()

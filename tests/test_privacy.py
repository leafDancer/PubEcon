from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from econpub.openalex import _backfill_same_person, _given_initials_compatible
from econpub.privacy import (
    sanitize_career_events,
    strip_personal_info,
    structured_snippet,
)


class PrivacyTests(unittest.TestCase):
    def test_personal_details_are_cut_but_years_survive(self) -> None:
        raw = (
            "BA in Economics, the University of Tokyo, 2002"
            "Personal InformationDate of birth: January 1, 1990"
            "Nationality: Japan"
        )
        cleaned = strip_personal_info(raw)
        self.assertEqual(cleaned, "BA in Economics, the University of Tokyo, 2002")
        self.assertEqual(strip_personal_info("2010-2015"), "2010-2015")

    def test_email_is_removed(self) -> None:
        cleaned = strip_personal_info(
            "Department of Economics, Example University, E-mail: person@example.edu"
        )
        self.assertEqual(cleaned, "Department of Economics, Example University")

    def test_affiliation_mode_keeps_address_text(self) -> None:
        value = "Department of Economics, 271 19th Avenue South, Minneapolis, MN 55455"
        self.assertEqual(
            strip_personal_info(value, cut_personal_markers=False), value
        )

    def test_structured_snippet_has_no_raw_line(self) -> None:
        snippet = structured_snippet(
            "education",
            "BA in Economics, 2002Personal InformationDate of birth: 1990",
            "The University of Tokyo",
            None,
            None,
            0,
        )
        self.assertNotIn("birth", snippet.lower())
        self.assertIn("The University of Tokyo", snippet)

    def test_sanitize_career_events_repairs_legacy_rows(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            CREATE TABLE career_events (
                event_id INTEGER PRIMARY KEY,
                event_type TEXT,
                title TEXT,
                institution TEXT,
                start_year INTEGER,
                end_year INTEGER,
                is_current INTEGER,
                source_type TEXT,
                source_snippet TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO career_events VALUES (1,'education',?,?,NULL,NULL,0,'cv',?)",
            (
                "BA, 2002Personal InformationDate of birth: 1990",
                "Tokyo",
                "raw CV line with birth date",
            ),
        )
        stats = sanitize_career_events(conn)
        row = conn.execute("SELECT * FROM career_events").fetchone()
        self.assertEqual(stats["changed"], 1)
        self.assertEqual(row["title"], "BA, 2002")
        self.assertNotIn("birth", (row["source_snippet"] or "").lower())


class BackfillNameTests(unittest.TestCase):
    def test_initial_abbreviations_match(self) -> None:
        self.assertTrue(_given_initials_compatible("N. Gregory", "N. G."))
        self.assertTrue(_given_initials_compatible("M. Utku", "M. U."))

    def test_corrupted_spacing_matches_clean_name(self) -> None:
        self.assertTrue(_backfill_same_person("J Eremy T. F Ox", "Jeremy T. Fox"))

    def test_different_people_do_not_match(self) -> None:
        self.assertFalse(_backfill_same_person("John Smith", "Jane Smith"))


if __name__ == "__main__":
    unittest.main()

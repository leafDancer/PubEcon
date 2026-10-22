from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from econpub.normalize import (
    canonical_name,
    clean_text,
    extract_date,
    extract_institution_hint,
    extract_rank,
    name_key,
    name_match_key,
    normalize_doi,
    normalize_issue,
    normalize_orcid,
    page_range,
    page_ranges_overlap,
    split_pages,
    synthetic_key,
    title_key,
    transliterate,
)


class NormalizeTests(unittest.TestCase):
    def test_clean_text_strips_jats_and_entities(self) -> None:
        self.assertEqual(
            clean_text("<jats:p>Hello &amp; <i>world</i></jats:p>"),
            "Hello & world",
        )

    def test_clean_text_handles_lists(self) -> None:
        self.assertEqual(clean_text(["A Title", "A Subtitle"]), "A Title A Subtitle")

    def test_normalize_doi(self) -> None:
        self.assertEqual(normalize_doi("https://doi.org/10.1257/AER.20120555"), "10.1257/aer.20120555")
        self.assertEqual(normalize_doi("doi: 10.1257/aer.20120555"), "10.1257/aer.20120555")
        self.assertEqual(normalize_doi(None), "")

    def test_normalize_orcid(self) -> None:
        self.assertEqual(
            normalize_orcid("https://orcid.org/0000-0001-9379-9592"),
            "https://orcid.org/0000-0001-9379-9592",
        )
        self.assertEqual(normalize_orcid("0000-0001-9379-959x"), "https://orcid.org/0000-0001-9379-959X")
        self.assertEqual(normalize_orcid("not-an-orcid"), "")

    def test_extract_date_prefers_published(self) -> None:
        item = {
            "published": {"date-parts": [[2016, 7]]},
            "issued": {"date-parts": [[2015]]},
        }
        self.assertEqual(extract_date(item), (2016, 7, None))

    def test_extract_date_falls_back_to_issued(self) -> None:
        item = {"issued": {"date-parts": [[2001, 12, 1]]}}
        self.assertEqual(extract_date(item), (2001, 12, 1))

    def test_split_pages(self) -> None:
        self.assertEqual(split_pages("1369-1401"), ("1369", "1401"))
        self.assertEqual(split_pages("3802–3836"), ("3802", "3836"))
        self.assertEqual(split_pages("e1-e10"), ("e1", "e10"))
        self.assertEqual(split_pages("42"), ("42", None))
        self.assertEqual(split_pages("1705-41"), ("1705", "1741"))
        self.assertEqual(split_pages("112-45"), ("112", "145"))
        self.assertEqual(split_pages("280-294"), ("280", "294"))

    def test_extract_rank(self) -> None:
        self.assertEqual(
            extract_rank("Assistant Professor of Economics, Princeton University"),
            ("Assistant Professor", "assistant_professor"),
        )
        self.assertEqual(
            extract_rank("Associate Professor, MIT"),
            ("Associate Professor", "associate_professor"),
        )
        self.assertEqual(
            extract_rank("Professor of Economics, Harvard University"),
            ("Professor", "full_professor"),
        )
        self.assertEqual(
            extract_rank("Ph.D. Student, Department of Economics"),
            ("Ph.D. Student", "phd_student"),
        )
        self.assertEqual(
            extract_rank("Postdoctoral Fellow, Stanford University"),
            ("Postdoctoral", "postdoc"),
        )
        self.assertEqual(
            extract_rank("Lecturer in Economics, University of Bristol"),
            ("Lecturer", "lecturer_other_academic"),
        )

    def test_extract_rank_non_academic(self) -> None:
        self.assertEqual(
            extract_rank("Federal Reserve Bank of New York"),
            ("Federal Reserve", "non_academic"),
        )
        self.assertEqual(extract_rank("Department of Economics, Harvard University"), (None, None))

    def test_extract_institution_hint(self) -> None:
        self.assertEqual(
            extract_institution_hint(
                "Assistant Professor of Economics, Princeton University (email: x@y.edu)"
            ),
            "Princeton University",
        )
        self.assertEqual(
            extract_institution_hint(
                "Department of Economics, 414 Uris Hall, Cornell University, Ithaca, NY 14853."
            ),
            "Cornell University",
        )
        self.assertEqual(
            extract_institution_hint("Federal Reserve Bank of New York, Research and Statistics Group"),
            "Federal Reserve Bank of New York",
        )
        self.assertEqual(extract_institution_hint("NBER"), "NBER")

    def test_names(self) -> None:
        self.assertEqual(name_key("Daron", "Acemoglu"), "acemoglu|daron")
        self.assertEqual(canonical_name("Daron", "Acemoglu"), "Daron Acemoglu")
        self.assertEqual(canonical_name("", "Acemoglu"), "Acemoglu")

    def test_synthetic_key_is_deterministic(self) -> None:
        first = synthetic_key("A Title", 2010, "1")
        second = synthetic_key("A Title", 2010, "1")
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("crossref:"))

    def test_transliteration_preserves_names(self) -> None:
        self.assertEqual(transliterate("Hortaçsu Pęski Szalay"), "Hortacsu Peski Szalay")
        self.assertEqual(transliterate("Łukasz Østergaard"), "Lukasz Ostergaard")

    def test_name_match_key_variants(self) -> None:
        self.assertEqual(name_match_key("Parag A", "Pathak"), "pathak|parag")
        self.assertEqual(name_match_key("Parag", "Pathak"), "pathak|parag")
        self.assertEqual(name_match_key("J. Vernon", "Henderson"), "henderson|vernon")
        self.assertEqual(name_match_key("Vernon", "Henderson"), "henderson|vernon")
        self.assertEqual(name_match_key("S", "Levitt"), "levitt|s")
        self.assertEqual(name_match_key("John", "Van Reenen"), "reenen|john")
        self.assertEqual(name_match_key("Pedro", "Dal Bo"), "dalbo|pedro")
        self.assertEqual(name_match_key("Pedro", "Dalbó"), "dalbo|pedro")
        self.assertEqual(name_match_key("Pedro Dal", "Bó"), "dalbo|pedro")
        self.assertEqual(name_match_key("Eric Van den", "Steen"), "steen|eric")

    def test_title_key_normalises_quotes_and_punctuation(self) -> None:
        left = title_key("Market Share Dynamics and the “Persistence” of Leadership Debate")
        right = title_key('Market Share Dynamics and the "Persistence" of Leadership Debate')
        self.assertEqual(left, right)
        self.assertEqual(title_key("  A   Title — With: Punctuation!  "), "a title with punctuation")

    def test_issue_and_page_normalisation(self) -> None:
        self.assertEqual(normalize_issue("03"), "3")
        self.assertEqual(normalize_issue(" 4 "), "4")
        self.assertEqual(page_range("i", "vi"), (1, 6))
        self.assertEqual(page_range("534", "537"), (534, 537))
        self.assertTrue(page_ranges_overlap((534, 538), (534, 537)))
        self.assertFalse(page_ranges_overlap((618, 619), (620, 621)))

    def test_street_name_is_not_a_rank(self) -> None:
        self.assertEqual(
            extract_rank("Avenida Professor Luciano Gualberto, 908, São Paulo"),
            (None, None),
        )

    def test_uc_campus_is_retained(self) -> None:
        self.assertEqual(
            extract_institution_hint(
                "Department of Economics, University of California, Berkeley, CA 94720"
            ),
            "University of California Berkeley",
        )


class AuthorMatchingTests(unittest.TestCase):
    def test_institution_tokens_expand_mit(self) -> None:
        from econpub.authors import _institution_tokens

        tokens = _institution_tokens("MIT", "Department of Economics, MIT")
        self.assertIn("massachusetts", tokens)
        self.assertIn("technology", tokens)

    def test_known_namesake_is_not_compatible(self) -> None:
        from econpub.authors import _compatible

        left = {
            "paper_id": 1,
            "suffix": "",
            "orcid": "",
            "normalized_full": "robert l clark",
            "middle_initials": {"l"},
            "institution_tokens": {"north", "carolina", "state"},
            "year": 2000,
        }
        right = {
            "paper_id": 2,
            "suffix": "",
            "orcid": "",
            "normalized_full": "robert clark",
            "middle_initials": set(),
            "institution_tokens": {"hec", "montreal", "queen"},
            "year": 2003,
        }
        self.assertFalse(_compatible(left, right))

    def test_conflicting_middle_initials_do_not_merge(self) -> None:
        from econpub.authors import _compatible

        left = {
            "paper_id": 1,
            "suffix": "",
            "orcid": "",
            "normalized_full": "kevin m murphy",
            "middle_initials": {"m"},
            "institution_tokens": {"chicago"},
            "year": 2000,
        }
        right = {
            "paper_id": 2,
            "suffix": "",
            "orcid": "",
            "normalized_full": "kevin j murphy",
            "middle_initials": {"j"},
            "institution_tokens": {"southern", "california"},
            "year": 2004,
        }
        self.assertFalse(_compatible(left, right))

    def test_middle_name_filed_as_family(self) -> None:
        self.assertEqual(
            name_match_key("W", "Michael Hanemann"),
            name_match_key("W. Michael", "Hanemann"),
        )

    def test_middle_initial_variants_merge(self) -> None:
        from econpub.authors import _components

        left = {
            "authorship_id": 1,
            "paper_id": 1,
            "author_order": 1,
            "given": "Parag A",
            "family": "Pathak",
            "full": "Parag A Pathak",
            "normalized_full": "parag a pathak",
            "middle_initials": {"a"},
            "affiliation": "",
            "hint": "MIT",
            "institution_tokens": {"massachusetts", "technology"},
            "orcid": "",
            "suffix": "",
            "match_key": "pathak|parag",
            "year": 2010,
        }
        right = {
            **left,
            "authorship_id": 2,
            "paper_id": 2,
            "full": "Parag Pathak",
            "normalized_full": "parag pathak",
            "middle_initials": set(),
            "year": 2015,
        }
        components = _components([left, right])
        self.assertEqual(len(components), 1)


if __name__ == "__main__":
    unittest.main()

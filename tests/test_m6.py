from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from econpub.wayback import _pick_snapshots, _stage_near_name


class WaybackTests(unittest.TestCase):
    def test_stage_near_name(self) -> None:
        text = """
        Jane Doe
        Assistant Professor
        Department of Economics, Example University
        """
        match = _stage_near_name(text, "Jane Doe")
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match[0], "assistant_professor")
        self.assertEqual(match[1], "high")

    def test_generic_professor_is_low(self) -> None:
        text = "Jane Doe is a Professor in the Department of Economics."
        match = _stage_near_name(text, "Jane Doe")
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match[0], "full_professor")
        self.assertEqual(match[1], "low")

    def test_student_signal(self) -> None:
        text = "Jane Doe is a Ph.D. candidate at Example University."
        match = _stage_near_name(text, "Jane Doe")
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match[0], "phd_student")
        self.assertEqual(match[1], "high")

    def test_pick_snapshots_by_year(self) -> None:
        snapshots = [
            {"timestamp": "20100101000000", "original": "https://example.org/a"},
            {"timestamp": "20150101000000", "original": "https://example.org/b"},
            {"timestamp": "20200101000000", "original": "https://example.org/c"},
        ]
        picked = _pick_snapshots(snapshots, [2011, 2019])
        self.assertEqual([year for year, _ in picked], [2011, 2019])
        self.assertEqual(picked[0][1]["timestamp"], "20100101000000")
        self.assertEqual(picked[1][1]["timestamp"], "20200101000000")

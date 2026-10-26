from __future__ import annotations

import hashlib
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from econpub import db
from econpub.release import generate_release_manifest


class ReleaseManifestTests(unittest.TestCase):
    def test_manifest_does_not_mutate_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "top5.db"
            conn = db.connect(database)
            db.init_db(conn)
            conn.close()
            before = hashlib.sha256(database.read_bytes()).hexdigest()
            generate_release_manifest(database, output_dir=root / "reports", root=root)
            after = hashlib.sha256(database.read_bytes()).hexdigest()
            self.assertEqual(before, after)
            self.assertTrue((root / "reports" / "release_manifest.json").exists())


if __name__ == "__main__":
    unittest.main()

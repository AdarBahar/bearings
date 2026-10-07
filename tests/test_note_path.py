"""Tests for locating a project's note, flat or grouped under a parent project.
Run with:  python3 -m unittest discover tests"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from bearings_sweep import note_path, note_updated  # noqa: E402


class TestNotePath(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel, text="---\nupdated: 2026-10-07\n---\n"):
        p = self.vault / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p

    def test_flat_note(self):
        p = self.write("app/app.md")
        self.assertEqual(note_path(self.vault, "app"), p)
        self.assertEqual(note_updated(self.vault, "app"), "2026-10-07")

    def test_grouped_note(self):
        p = self.write("system/app/app.md")
        self.assertEqual(note_path(self.vault, "app"), p)
        self.assertEqual(note_updated(self.vault, "app"), "2026-10-07")

    def test_flat_wins_over_grouped(self):
        flat = self.write("app/app.md")
        self.write("system/app/app.md")
        self.assertEqual(note_path(self.vault, "app"), flat)

    def test_missing_note(self):
        self.assertEqual(note_path(self.vault, "app"), self.vault / "app" / "app.md")
        self.assertIsNone(note_updated(self.vault, "app"))


if __name__ == "__main__":
    unittest.main()

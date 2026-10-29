"""Tests for the remote script quoting, the state write, the sweep lock,
and the lint hook type check.
Run with:  python3 -m unittest discover tests"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import bearings_lint  # noqa: E402
import bearings_sweep  # noqa: E402


class TestRemoteScript(unittest.TestCase):
    def test_command_substitution_stays_literal(self):
        marker = Path(tempfile.mkdtemp()) / "pwned"
        machine = {"dirs": [f"/nonexistent/$(touch {marker})"]}
        subprocess.run(["bash", "-c", bearings_sweep.remote_script(machine)])
        self.assertFalse(marker.exists())

    def test_directory_with_space_is_listed(self):
        base = Path(tempfile.mkdtemp()) / "my projects"
        (base / "app").mkdir(parents=True)
        out = subprocess.run(["bash", "-c", bearings_sweep.remote_script({"dirs": [str(base)]})],
                             capture_output=True, text=True).stdout
        self.assertIn("app|", out)


class TestStateAndLock(unittest.TestCase):
    def setUp(self):
        d = Path(tempfile.mkdtemp())
        patches = [mock.patch.object(bearings_sweep, "BEARINGS_DIR", d),
                   mock.patch.object(bearings_sweep, "STATE_FILE", d / "state.json")]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.dir = d

    def test_save_state_leaves_no_temp_file(self):
        bearings_sweep.save_state({"a": 1})
        self.assertEqual(bearings_sweep.load_state(), {"a": 1})
        self.assertEqual([p.name for p in self.dir.glob("*.tmp")], [])

    def test_second_lock_is_refused(self):
        first = bearings_sweep.acquire_lock()
        self.assertIsNotNone(first)
        self.assertIsNone(bearings_sweep.acquire_lock())
        first.close()
        again = bearings_sweep.acquire_lock()
        self.assertIsNotNone(again)
        again.close()


class TestIsLinted(unittest.TestCase):
    def test_typed_note_is_linted(self):
        self.assertTrue(bearings_lint.is_linted("---\ntype: project\n---\nbody"))

    def test_untyped_and_plain_notes_are_not(self):
        self.assertFalse(bearings_lint.is_linted("---\ntitle: x\n---\n"))
        self.assertFalse(bearings_lint.is_linted("no frontmatter"))


if __name__ == "__main__":
    unittest.main()

"""Tests for the time-aware stale check.
Run with:  python3 -m unittest discover tests"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import bearings_sweep  # noqa: E402
from bearings_sweep import is_stale  # noqa: E402


class TestIsStaleWithTimes(unittest.TestCase):
    def test_same_day_change_after_the_refresh_is_stale(self):
        self.assertTrue(is_stale("2026-10-30T15:00", "2026-10-30T10:00"))

    def test_same_day_change_before_the_refresh_is_not_stale(self):
        self.assertFalse(is_stale("2026-10-30T09:00", "2026-10-30T10:00"))

    def test_change_inside_the_tolerance_is_not_stale(self):
        self.assertFalse(is_stale("2026-10-30T10:01", "2026-10-30T10:00"))
        self.assertTrue(is_stale("2026-10-30T10:03", "2026-10-30T10:00"))

    def test_date_only_values_keep_the_date_rule(self):
        self.assertFalse(is_stale("2026-10-30T15:00", "2026-10-30"))
        self.assertTrue(is_stale("2026-10-31T01:00", "2026-10-30"))
        self.assertTrue(is_stale("2026-10-30", ""))

    def test_bad_time_falls_back_to_the_date_rule(self):
        self.assertFalse(is_stale("2026-10-30T15:00", "2026-10-30Tnope!"))


class TestStampSources(unittest.TestCase):
    def test_git_project_stamp_has_a_time(self):
        d = Path(tempfile.mkdtemp()) / "app"
        d.mkdir()
        subprocess.run(["git", "init", "-q", str(d)], check=True)
        subprocess.run(["git", "-C", str(d), "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-q", "--allow-empty", "-m", "x"], check=True)
        (_, stamp, is_git, _), = bearings_sweep.local_projects([str(d.parent)])
        self.assertTrue(is_git)
        self.assertRegex(stamp, r"^\d{4}-\d\d-\d\dT\d\d:\d\d$")

    def test_folder_stamp_has_a_time(self):
        d = Path(tempfile.mkdtemp()) / "plain"
        d.mkdir()
        (d / "a.txt").write_text("x")
        (_, stamp, is_git, _), = bearings_sweep.local_projects([str(d.parent)])
        self.assertFalse(is_git)
        self.assertRegex(stamp, r"^\d{4}-\d\d-\d\dT\d\d:\d\d$")

    def test_remote_script_asks_for_times(self):
        with mock.patch.object(bearings_sweep, "run") as run:
            run.return_value = mock.Mock(returncode=0, stdout="")
            bearings_sweep.remote_projects({"ssh": "h", "dirs": ["/x"]})
        script = run.call_args[0][0][-1]
        self.assertIn("%cd --date=format-local", script)
        self.assertIn("%TH:%TM", script)


if __name__ == "__main__":
    unittest.main()

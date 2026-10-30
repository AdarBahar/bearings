"""Tests for the time-aware stale check.
Run with:  python3 -m unittest discover tests"""

import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
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
        self.assertIn("--format=%ct", script)
        self.assertIn("%T@", script)


class TestRemoteTimeZone(unittest.TestCase):
    """A remote host in UTC reports epoch seconds; the stamp is in local time."""

    def setUp(self):
        old = os.environ.get("TZ")
        os.environ["TZ"] = "Asia/Jerusalem"
        time.tzset()
        def restore():
            if old is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = old
            time.tzset()
        self.addCleanup(restore)

    def remote(self, stdout):
        with mock.patch.object(bearings_sweep, "run") as run:
            run.return_value = mock.Mock(returncode=0, stdout=stdout)
            return bearings_sweep.remote_projects({"ssh": "h", "dirs": ["/x"]})

    def test_utc_epoch_becomes_local_time(self):
        epoch = int(datetime(2026, 10, 30, 8, 0, tzinfo=timezone.utc).timestamp())
        (_, stamp, _, _), = self.remote(f"app|{epoch}|git|/x/app\n")
        self.assertEqual(stamp, "2026-10-30T10:00")

    def test_change_before_a_later_local_refresh_is_not_stale(self):
        # 09:00 UTC = 11:00 in Jerusalem; the note was refreshed at 11:00.
        epoch = int(datetime(2026, 10, 30, 9, 0, tzinfo=timezone.utc).timestamp())
        (_, stamp, _, _), = self.remote(f"app|{epoch}|git|/x/app\n")
        self.assertFalse(is_stale(stamp, "2026-10-30T11:00"))
        # 10:00 UTC = 12:00 local: a real change after the refresh.
        epoch = int(datetime(2026, 10, 30, 10, 0, tzinfo=timezone.utc).timestamp())
        (_, stamp, _, _), = self.remote(f"app|{epoch}|git|/x/app\n")
        self.assertTrue(is_stale(stamp, "2026-10-30T11:00"))

    def test_find_float_epoch_and_bad_lines(self):
        out = self.remote("a|1761818400.1234567890|dir|/x/a\nb||dir|/x/b\nc|junk|git|/x/c\n")
        self.assertEqual([o[0] for o in out], ["a"])


if __name__ == "__main__":
    unittest.main()

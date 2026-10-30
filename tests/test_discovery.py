"""Tests for the early filter and the pruned folder walk in project discovery.
Run with:  python3 -m unittest discover tests"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import bearings_sweep  # noqa: E402


def gnu_find():
    try:
        out = subprocess.run(["find", "--version"], capture_output=True, text=True).stdout
    except OSError:
        return False
    return "GNU" in out


class TestLocalFilter(unittest.TestCase):
    def test_excluded_folder_is_not_scanned(self):
        base = Path(tempfile.mkdtemp())
        for n in ("keep", "skip"):
            (base / n).mkdir()
            (base / n / "a.txt").write_text("x")
        with mock.patch.object(bearings_sweep, "newest_mtime_local",
                               return_value="2026-10-30T10:00") as scan:
            out = bearings_sweep.local_projects([str(base)], lambda name, is_git: name != "skip")
        self.assertEqual([o[0] for o in out], ["keep"])
        self.assertEqual([c.args[0].name for c in scan.call_args_list], ["keep"])

    def test_git_log_is_skipped_for_excluded_repo(self):
        base = Path(tempfile.mkdtemp())
        (base / "skip" / ".git").mkdir(parents=True)
        with mock.patch.object(bearings_sweep, "run") as run:
            out = bearings_sweep.local_projects([str(base)], lambda name, is_git: False)
        self.assertEqual(out, [])
        run.assert_not_called()


class TestRemoteFilter(unittest.TestCase):
    machine = {"ssh": "h", "dirs": ["/code"]}

    def test_only_wanted_folders_reach_the_scan(self):
        listing = "git|/code/keep/\ndir|/code/skip/\ndir|/code/plain/\n"
        scan = "keep|1761818400|git|/code/keep/\n"
        with mock.patch.object(bearings_sweep, "run") as run:
            run.side_effect = [mock.Mock(returncode=0, stdout=listing),
                               mock.Mock(returncode=0, stdout=scan)]
            seen = []
            def wanted(name, is_git):
                seen.append((name, is_git))
                return name == "keep"
            out = bearings_sweep.remote_projects(self.machine, wanted)
        self.assertEqual(seen, [("keep", True), ("skip", False), ("plain", False)])
        self.assertEqual([o[0] for o in out], ["keep"])
        script = run.call_args_list[1][0][0][-1]
        self.assertIn("/code/keep/", script)
        self.assertNotIn("skip", script)
        self.assertNotIn("plain", script)

    def test_no_wanted_folder_means_no_scan_call(self):
        with mock.patch.object(bearings_sweep, "run") as run:
            run.return_value = mock.Mock(returncode=0, stdout="dir|/code/a/\n")
            self.assertEqual(bearings_sweep.remote_projects(self.machine, lambda n, g: False), [])
        self.assertEqual(run.call_count, 1)

    def test_unreachable_host_returns_none(self):
        with mock.patch.object(bearings_sweep, "run") as run:
            run.return_value = mock.Mock(returncode=255, stdout="")
            self.assertIsNone(bearings_sweep.remote_projects(self.machine, lambda n, g: True))

    def test_without_wanted_one_call_scans_all(self):
        with mock.patch.object(bearings_sweep, "run") as run:
            run.return_value = mock.Mock(returncode=0, stdout="")
            bearings_sweep.remote_projects(self.machine)
        self.assertEqual(run.call_count, 1)
        self.assertIn("/code/*/", run.call_args[0][0][-1])

    def test_script_prunes_instead_of_filtering(self):
        script = bearings_sweep.remote_script(self.machine)
        self.assertIn("-prune", script)
        self.assertNotIn("-not -path", script)

    def test_path_with_shell_syntax_stays_literal(self):
        marker = Path(tempfile.mkdtemp()) / "pwned"
        script = bearings_sweep.remote_script(self.machine, [f"/nonexistent/$(touch {marker})/"])
        subprocess.run(["bash", "-c", script])
        self.assertFalse(marker.exists())


@unittest.skipUnless(gnu_find(), "needs GNU find (-printf)")
class TestPrunedFindBehavior(unittest.TestCase):
    def scan(self, base):
        script = bearings_sweep.remote_script({"dirs": [str(base)]})
        out = subprocess.run(["bash", "-c", script], capture_output=True, text=True).stdout
        return {line.split("|")[0]: line.split("|")[1] for line in out.splitlines()}

    def test_pruned_folders_do_not_set_the_stamp(self):
        base = Path(tempfile.mkdtemp())
        proj = base / "proj"
        for rel, mtime in (("a.txt", 1000), ("node_modules/n.txt", 5000),
                           ("sub/data/d.txt", 6000), ("x.log", 7000), ("sub/b.txt", 2000)):
            f = proj / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("x")
            os.utime(f, (mtime, mtime))
        self.assertEqual(float(self.scan(base)["proj"]), 2000.0)

    def test_project_named_like_a_pruned_folder_is_scanned(self):
        base = Path(tempfile.mkdtemp())
        (base / "data").mkdir()
        f = base / "data" / "a.txt"
        f.write_text("x")
        os.utime(f, (3000, 3000))
        self.assertEqual(float(self.scan(base)["data"]), 3000.0)


if __name__ == "__main__":
    unittest.main()

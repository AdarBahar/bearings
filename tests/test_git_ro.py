"""Tests for the read-only git wrapper used by headless runs.
Run with:  python3 -m unittest discover tests"""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GIT_RO = ROOT / "scripts" / "git_ro.py"


class TestGitRo(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)

    def tearDown(self):
        shutil.rmtree(self.repo)

    def run_ro(self, *args):
        return subprocess.run([sys.executable, str(GIT_RO), *args],
                              cwd=self.repo, capture_output=True, text=True)

    def test_status_is_allowed(self):
        self.assertEqual(self.run_ro("status").returncode, 0)

    def test_tag_list_is_allowed(self):
        self.assertEqual(self.run_ro("tag", "--list").returncode, 0)

    def test_unknown_subcommand_is_blocked(self):
        for sub in ["show", "grep", "diff", "push", "config"]:
            r = self.run_ro(sub)
            self.assertEqual(r.returncode, 1, sub)
            self.assertIn("not allowed", r.stderr)

    def test_log_output_flag_is_blocked(self):
        for flag in ["--output=/tmp/x", "--output", "--output-directory=/tmp"]:
            r = self.run_ro("log", flag)
            self.assertEqual(r.returncode, 1, flag)
            self.assertIn("not allowed", r.stderr)

    def test_ref_creation_is_blocked(self):
        for sub in ["tag", "branch"]:
            r = self.run_ro(sub, "v1")
            self.assertEqual(r.returncode, 1, sub)
            self.assertIn("creates a ref", r.stderr)

    def test_remote_mutation_is_blocked(self):
        for args in [("remote", "add", "x", "url"), ("remote", "set-url", "x", "url"),
                     ("remote", "remove", "x"), ("branch", "-D", "x"),
                     ("tag", "-d", "x")]:
            r = self.run_ro(*args)
            self.assertEqual(r.returncode, 1, args)

    def test_no_args_prints_usage(self):
        r = self.run_ro()
        self.assertEqual(r.returncode, 1)
        self.assertIn("usage", r.stderr)


if __name__ == "__main__":
    unittest.main()

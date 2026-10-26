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
        subprocess.run(["git", "-C", str(self.repo), "-c", "user.email=t@t",
                        "-c", "user.name=t", "commit", "-q", "--allow-empty",
                        "-m", "first"], check=True)

    def tearDown(self):
        shutil.rmtree(self.repo)

    def run_ro(self, *args):
        return subprocess.run([sys.executable, str(GIT_RO), *args],
                              cwd=self.repo, capture_output=True, text=True)

    def tags(self):
        r = subprocess.run(["git", "-C", str(self.repo), "tag", "--list"],
                           capture_output=True, text=True)
        return r.stdout.split()

    def test_read_only_forms_are_allowed(self):
        for args in [("tag", "--list"), ("branch", "-a"),
                     ("log", "--format=%h", "-3"), ("log", "--since=2020-01-01"),
                     ("log", "--pretty=oneline"), ("rev-parse", "--show-toplevel"),
                     ("ls-files",), ("ls-files", "-m"),
                     ("remote", "-v"), ("shortlog", "-s", "-n")]:
            r = self.run_ro(*args)
            self.assertEqual(r.returncode, 0, (args, r.stderr))

    def test_unknown_subcommand_is_blocked(self):
        # `status` can run a clean filter on racily-clean files, so it is
        # not offered.
        for sub in ["show", "grep", "diff", "push", "config", "cat-file",
                    "status"]:
            r = self.run_ro(sub)
            self.assertEqual(r.returncode, 1, sub)
            self.assertIn("not allowed", r.stderr)

    def test_unknown_flags_are_blocked(self):
        # Allowlist semantics: a flag that is not listed never runs — this
        # covers --output, abbreviations of it, and mutating flags.
        for args in [("log", "--output=/tmp/x"), ("log", "--outp=/tmp/x"),
                     ("log", "--output"), ("log", "--ext-diff"),
                     ("branch", "-D", "x"), ("branch", "--set-upstream-to=x"),
                     ("branch", "-u", "x"), ("branch", "--edit-description"),
                     ("tag", "-d", "x"), ("tag", "-a", "x"), ("tag", "-f", "x"),
                     ("tag", "-F", "/tmp/x"), ("describe", "--dirty"),
                     ("log", "--stat"), ("log", "-p"), ("log", "--ext-diff")]:
            r = self.run_ro(*args)
            self.assertEqual(r.returncode, 1, args)
            self.assertIn("not allowed", r.stderr)

    def test_tag_positional_lists_and_creates_nothing(self):
        r = self.run_ro("tag", "v1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.tags(), [])

    def test_remote_mutation_is_blocked(self):
        for args in [("remote", "add", "x", "url"),
                     ("remote", "set-url", "x", "url"),
                     ("remote", "remove", "x"), ("remote", "rename", "x", "y")]:
            r = self.run_ro(*args)
            self.assertEqual(r.returncode, 1, args)
            self.assertIn("not allowed", r.stderr)

    def test_signature_placeholders_are_blocked(self):
        # %G placeholders verify signatures, and that runs a gpg program.
        for args in [("log", "--format=%G?"), ("log", "--pretty=%h %GG")]:
            r = self.run_ro(*args)
            self.assertEqual(r.returncode, 1, args)
            self.assertIn("%G", r.stderr)

    def test_pretty_alias_is_blocked(self):
        # pretty.<alias> in the repo config can expand to %G placeholders.
        subprocess.run(["git", "-C", str(self.repo), "config",
                        "pretty.evil", "%GG"], check=True)
        r = self.run_ro("log", "--pretty=evil")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("alias not allowed", r.stderr)

    def test_repo_config_cannot_name_the_pager_or_hooks(self):
        # The wrapper overrides each program-running key on the command
        # line, which outranks the repo configuration.
        subprocess.run(["git", "-C", str(self.repo), "config",
                        "core.pager", "touch pager-ran"], check=True)
        r = self.run_ro("log", "--format=%h")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse((self.repo / "pager-ran").exists())

    def test_no_args_prints_usage(self):
        r = self.run_ro()
        self.assertEqual(r.returncode, 1)
        self.assertIn("usage", r.stderr)


if __name__ == "__main__":
    unittest.main()

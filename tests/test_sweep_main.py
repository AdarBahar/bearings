"""Integration tests for the canary and model wiring in the sweep's main().
Run with:  python3 -m unittest discover tests"""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import bearings_sweep  # noqa: E402

CONFIG = """---
cadence: daily
refresh_mode: auto
create_new: ask
model: claude-haiku-5-5
machines:
  - "mac | local | {projects}"
---
"""

DASHBOARD = """# Dash
<!-- bearings:pending -->
- [x] app @mac (changed 2026-01-01)
<!-- /bearings:pending -->
"""


class TestMainWiring(unittest.TestCase):
    """One approved new project; no note exists, so a sweep wants to
    create it. The canary decides whether the run starts."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.vault = self.tmp / "vault"
        self.vault.mkdir()
        projects = self.tmp / "code"
        proj = projects / "app"
        proj.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(proj)], check=True)
        subprocess.run(["git", "-C", str(proj), "-c", "user.email=t@t",
                        "-c", "user.name=t", "commit", "-q", "--allow-empty",
                        "-m", "first"], check=True)
        (self.vault / "_Config.md").write_text(CONFIG.format(projects=projects))
        (self.vault / "_Dashboard.md").write_text(DASHBOARD)
        bdir = self.tmp / ".bearings"
        bdir.mkdir()
        env_file = bdir / "bearings.env"
        env_file.write_text(f"BEARINGS_VAULT_DIR={self.vault}\n"
                            f"BEARINGS_HOME={ROOT}\n")
        self.patches = [
            mock.patch.object(bearings_sweep, "BEARINGS_DIR", bdir),
            mock.patch.object(bearings_sweep, "ENV_FILE", env_file),
            mock.patch.object(bearings_sweep, "STATE_FILE", bdir / "state.json"),
            mock.patch.object(sys, "argv", ["bearings_sweep.py", "--force"]),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.tmp)

    def dash(self):
        return (self.vault / "_Dashboard.md").read_text()

    def test_failed_canary_skips_runs_and_keeps_the_approval(self):
        with mock.patch.object(bearings_sweep, "skills_canary",
                               return_value=(False, 0.0, 0, 0)) as canary, \
             mock.patch.object(bearings_sweep, "run_claude") as run_claude:
            self.assertEqual(bearings_sweep.main(), 0)
        run_claude.assert_not_called()
        canary.assert_called_once()
        # The canary runs on the configured model.
        self.assertEqual(canary.call_args[0][1], "claude-haiku-5-5")
        self.assertIn("canary FAILED", self.dash())
        # The approval survives as a checked box for the next sweep.
        self.assertIn("- [x] app @mac", self.dash())

    def test_passing_canary_creates_the_note_with_the_model(self):
        with mock.patch.object(bearings_sweep, "skills_canary",
                               return_value=(True, 0.01, 10, 2)), \
             mock.patch.object(bearings_sweep, "run_claude",
                               return_value=(True, 0.05, 100, 20)) as run_claude:
            self.assertEqual(bearings_sweep.main(), 0)
        run_claude.assert_called_once()
        # run_claude(env, vault, machine, path, warnings, model)
        self.assertEqual(run_claude.call_args[0][5], "claude-haiku-5-5")
        self.assertIn("created app", self.dash())

    def test_report_only_never_calls_the_canary(self):
        with mock.patch.object(sys, "argv",
                               ["bearings_sweep.py", "--force", "--report"]), \
             mock.patch.object(bearings_sweep, "skills_canary") as canary, \
             mock.patch.object(bearings_sweep, "run_claude") as run_claude:
            self.assertEqual(bearings_sweep.main(), 0)
        canary.assert_not_called()
        run_claude.assert_not_called()


if __name__ == "__main__":
    unittest.main()

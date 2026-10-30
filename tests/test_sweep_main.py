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
                               return_value=(False, 0.0, 0, 0, {})) as canary, \
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
        canary_models = {"claude-haiku-5-5": {"cost": 0.01, "in": 10, "out": 2}}
        run_models = {"claude-haiku-5-5": {"cost": 0.05, "in": 100, "out": 20}}
        with mock.patch.object(bearings_sweep, "skills_canary",
                               return_value=(True, 0.01, 10, 2, canary_models)), \
             mock.patch.object(bearings_sweep, "run_claude",
                               return_value=(True, 0.05, 100, 20, run_models)) as run_claude:
            self.assertEqual(bearings_sweep.main(), 0)
        run_claude.assert_called_once()
        # run_claude(env, vault, machine, path, warnings, model)
        self.assertEqual(run_claude.call_args[0][5], "claude-haiku-5-5")
        self.assertIn("created app", self.dash())
        # The Costs section counts the canary and the create, per model.
        self.assertIn("**Today:** 2 runs · $0.06", self.dash())
        self.assertIn("| claude-haiku-5-5 | 2 | $0.06 |", self.dash())

    def test_budget_stop_skips_all_runs_and_keeps_the_approval(self):
        import json
        from datetime import date
        (self.vault / "_Config.md").write_text(
            (self.vault / "_Config.md").read_text().replace(
                "model: claude-haiku-5-5",
                "model: claude-haiku-5-5\nbudget_stop_usd: 5"))
        month = date.today().strftime("%Y-%m")
        (self.tmp / ".bearings" / "state.json").write_text(json.dumps(
            {"months": {month: {"runs": 1, "cost": 6.0,
                                "t_in": 10, "t_out": 1}}}))
        with mock.patch.object(bearings_sweep, "skills_canary") as canary, \
             mock.patch.object(bearings_sweep, "run_claude") as run_claude:
            self.assertEqual(bearings_sweep.main(), 0)
        canary.assert_not_called()
        run_claude.assert_not_called()
        self.assertIn("budget stop", self.dash())
        self.assertIn("- [x] app @mac", self.dash())
        self.assertIn("stop at $5", self.dash())

    def test_report_only_never_calls_the_canary(self):
        with mock.patch.object(sys, "argv",
                               ["bearings_sweep.py", "--force", "--report"]), \
             mock.patch.object(bearings_sweep, "skills_canary") as canary, \
             mock.patch.object(bearings_sweep, "run_claude") as run_claude:
            self.assertEqual(bearings_sweep.main(), 0)
        canary.assert_not_called()
        run_claude.assert_not_called()
        # A report run keeps the checked approval and does not mark the day done.
        self.assertIn("- [x] app @mac", self.dash())
        self.assertNotIn("last_run", bearings_sweep.load_state())

    def test_report_alone_ignores_the_schedule_gates(self):
        import json
        from datetime import date
        cfg = self.vault / "_Config.md"
        cfg.write_text(cfg.read_text().replace("cadence: daily", "cadence: manual"))
        (self.tmp / ".bearings" / "state.json").write_text(
            json.dumps({"last_run": date.today().isoformat()}))
        with mock.patch.object(sys, "argv", ["bearings_sweep.py", "--report"]), \
             mock.patch.object(bearings_sweep, "skills_canary") as canary, \
             mock.patch.object(bearings_sweep, "run_claude") as run_claude:
            self.assertEqual(bearings_sweep.main(), 0)
        canary.assert_not_called()
        run_claude.assert_not_called()
        self.assertIn("Actions: none (report-only)", self.dash())
        self.assertEqual(bearings_sweep.load_state()["last_run"],
                         date.today().isoformat())

    def test_replace_section_keeps_backslashes_literal(self):
        start, end = bearings_sweep.MARK["pending"]
        text = f"{start}\nold\n{end}\n"
        out = bearings_sweep.replace_section(text, "pending", r"- app\q \1 \b")
        self.assertIn(r"- app\q \1 \b", out)

    def test_charge_survives_a_dashboard_write_failure(self):
        import json
        from datetime import date
        (self.vault / "_Config.md").write_text(
            (self.vault / "_Config.md").read_text().replace(
                "create_new: ask", "create_new: auto"))
        with mock.patch.object(bearings_sweep, "skills_canary",
                               return_value=(True, 0.5, 10, 2, {})), \
             mock.patch.object(bearings_sweep, "run_claude",
                               return_value=(True, 1.0, 100, 20,
                                             {"m": {"cost": 1.0, "in": 100, "out": 20}})), \
             mock.patch.object(bearings_sweep, "replace_section",
                               side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                bearings_sweep.main()
        month = date.today().strftime("%Y-%m")
        mo = json.loads((self.tmp / ".bearings" / "state.json").read_text())["months"][month]
        self.assertAlmostEqual(mo["cost"], 1.5)
        self.assertEqual(mo["t_in"], 110)
        runs = json.loads((self.tmp / ".bearings" / "state.json").read_text())["runs"]
        self.assertAlmostEqual(sum(r["cost"] for r in runs), 1.0)


if __name__ == "__main__":
    unittest.main()

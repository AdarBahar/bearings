"""Tests for the model setting, the skill lock and the bare-mode canary.
Run with:  python3 -m unittest discover tests"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import bearings_sweep  # noqa: E402
from bearings_sweep import load_config, parse_frontmatter, skills_canary  # noqa: E402

CONFIG = """---
cadence: daily
refresh_mode: auto
create_new: ask
{model_line}
machines:
  - "mac | local | ~/Code"
---
"""


def fake_result(stdout="{}", returncode=0):
    return SimpleNamespace(stdout=stdout, returncode=returncode)


class TestModelSetting(unittest.TestCase):
    def load(self, model_line):
        vault = Path(tempfile.mkdtemp())
        try:
            (vault / "_Config.md").write_text(CONFIG.format(model_line=model_line))
            cfg, errors = load_config(vault)
            self.assertEqual(errors, [])
            return cfg
        finally:
            shutil.rmtree(vault)

    def test_model_is_parsed_and_defaults_to_empty(self):
        self.assertEqual(self.load("model: claude-haiku-5-5")["model"],
                         "claude-haiku-5-5")
        self.assertEqual(self.load("model:")["model"], "")

    def test_run_claude_passes_the_model_flag(self):
        repo = Path(tempfile.mkdtemp())
        machine = {"name": "mac", "ssh": None}
        calls = []

        def recorder(cmd, **kw):
            calls.append(cmd)
            return fake_result()

        try:
            with mock.patch.object(bearings_sweep, "run", recorder):
                bearings_sweep.run_claude({}, repo, machine, str(repo), [],
                                          "claude-haiku-5-5")
                bearings_sweep.run_claude({}, repo, machine, str(repo), [])
            self.assertIn("--model", calls[0])
            self.assertIn("claude-haiku-5-5", calls[0])
            self.assertNotIn("--model", calls[1])
        finally:
            shutil.rmtree(repo)


class TestSkillLock(unittest.TestCase):
    def test_bearings_doc_is_locked_to_human_invocation(self):
        fm = parse_frontmatter(
            (ROOT / "skills" / "bearings-doc" / "SKILL.md").read_text())
        self.assertEqual(fm.get("disable-model-invocation"), "true")


class TestSkillsCanary(unittest.TestCase):
    def canary(self, stdout, returncode=0):
        with mock.patch.object(bearings_sweep, "run",
                               return_value=fake_result(stdout, returncode)):
            return skills_canary({})

    def test_canary_invokes_the_skill_instead_of_asking_about_it(self):
        # disable-model-invocation hides the skill from the model's own
        # view, so an availability question can answer NO on a healthy
        # install. Invoking /bearings-doc --canary works under the lock.
        calls = []

        def recorder(cmd, **kw):
            calls.append(cmd)
            return fake_result(json.dumps({"result": "BEARINGS-DOC-LOADED"}))

        with mock.patch.object(bearings_sweep, "run", recorder):
            ok, *_ = skills_canary({})
            skills_canary({}, "claude-haiku-5-5")
        self.assertTrue(ok)
        self.assertIn("/bearings-doc --canary", calls[0])
        self.assertNotIn("--model", calls[0])
        self.assertIn("--model", calls[1])

    def test_token_passes_and_cost_is_reported(self):
        out = json.dumps({"result": "BEARINGS-DOC-LOADED",
                          "total_cost_usd": 0.01,
                          "usage": {"input_tokens": 100, "output_tokens": 5}})
        ok, cost, t_in, t_out = self.canary(out)
        self.assertTrue(ok)
        self.assertEqual((cost, t_in, t_out), (0.01, 100, 5))

    def test_other_reply_fails(self):
        ok, *_ = self.canary(json.dumps(
            {"result": "I do not know that command."}))
        self.assertFalse(ok)

    def test_error_and_garbage_fail_closed(self):
        ok, *_ = self.canary(json.dumps({"result": "BEARINGS-DOC-LOADED"}),
                             returncode=1)
        self.assertFalse(ok)
        ok, *_ = self.canary("not json")
        self.assertFalse(ok)

    def test_timeout_fails_closed_instead_of_aborting(self):
        import subprocess
        exc = subprocess.TimeoutExpired(cmd="claude", timeout=300)
        with mock.patch.object(bearings_sweep, "run", side_effect=exc):
            ok, cost, t_in, t_out = skills_canary({})
        self.assertEqual((ok, cost, t_in, t_out), (False, 0, 0, 0))

    def test_skill_canary_instruction_exists(self):
        text = (ROOT / "skills" / "bearings-doc" / "SKILL.md").read_text()
        self.assertIn("BEARINGS-DOC-LOADED", text)
        self.assertIn("--canary", text)


if __name__ == "__main__":
    unittest.main()

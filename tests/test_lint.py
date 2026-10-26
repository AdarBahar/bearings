"""Tests for the note linter and the lint hook.
Run with:  python3 -m unittest discover tests"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from bearings_lint import collect_names, lint_file, lint_vault, template_parity  # noqa: E402

GOOD_PROJECT = """---
type: project
project: app
summary: A test project.
status: active
deploy_scope: lan
deployments:
  - "[[app@lan]]"
updated: 2026-10-25T10:00
---

# app

> A test project.

## Resume here

<!-- manual:start -->
%% my own notes with PROJECT_NAME and [[nowhere]] — the linter must skip this %%
<!-- manual:end -->

## Quick start

```bash
[[ -d x ]] && echo PROJECT_NAME   # code is skipped too
```

## Links

- Deployment: [[app@lan]]
- Machine: [[mac|the mac]]
"""

GOOD_DEPLOYMENT = """---
type: deployment
project: "[[app]]"
env: lan
status: running
host: "[[mac]]"
updated: 2026-10-25T10:00
---

# app @ lan
"""

GOOD_MACHINE = """---
type: machine
machine: mac
summary: The laptop.
status: active
kind: laptop
updated: 2026-10-25T10:00
---

# mac
"""


class LintVaultCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.vault = self.tmp / "vault"
        (self.vault / "app").mkdir(parents=True)
        (self.vault / "mac").mkdir()
        self.write("app/app.md", GOOD_PROJECT)
        self.write("app/app@lan.md", GOOD_DEPLOYMENT)
        self.write("mac/mac.md", GOOD_MACHINE)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def write(self, rel, text):
        p = self.vault / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p

    def lint(self, rel):
        return lint_file(self.vault / rel, self.vault, collect_names(self.vault))


class TestLintFile(LintVaultCase):
    def test_good_vault_is_clean(self):
        self.assertEqual(lint_vault(self.vault), [])

    def test_untyped_note_is_skipped(self):
        self.write("app/changelog.md", "# changelog\n\nPROJECT_NAME [[nowhere]]\n")
        self.assertEqual(self.lint("app/changelog.md"), [])

    def test_missing_required_property(self):
        self.write("app/app.md", GOOD_PROJECT.replace("summary: A test project.\n", ""))
        self.assertIn("missing required property: summary", self.lint("app/app.md"))

    def test_bad_updated_date(self):
        self.write("app/app.md", GOOD_PROJECT.replace("2026-10-25T10:00", "YYYY-MM-DDTHH:MM"))
        problems = self.lint("app/app.md")
        self.assertTrue(any(p.startswith("updated is not a date") for p in problems))

    def test_bad_env_value(self):
        self.write("app/app@lan.md", GOOD_DEPLOYMENT.replace("env: lan", "env: production"))
        problems = self.lint("app/app@lan.md")
        self.assertTrue(any(p.startswith("env:") for p in problems))

    def test_unquoted_host(self):
        self.write("app/app@lan.md", GOOD_DEPLOYMENT.replace('host: "[[mac]]"', "host: mac"))
        problems = self.lint("app/app@lan.md")
        self.assertTrue(any("host must be a quoted link" in p for p in problems))

    def test_unresolved_link(self):
        self.write("app/app.md", GOOD_PROJECT + "\nSee [[missing-note]].\n")
        self.assertIn("link does not resolve: [[missing-note]]", self.lint("app/app.md"))

    def test_link_with_alias_and_heading_resolves(self):
        self.write("app/app.md", GOOD_PROJECT + "\nSee [[mac#Access|the mac]].\n")
        self.assertEqual(self.lint("app/app.md"), [])

    def test_placeholder_outside_manual_section(self):
        self.write("app/app.md", GOOD_PROJECT + "\nClone: OWNER/REPO\n")
        self.assertIn("template placeholder left in the note: OWNER/REPO",
                      self.lint("app/app.md"))

    def test_template_hint_outside_manual_section(self):
        hint = re.search(r"%%.*?%%", (ROOT / "templates" / "project.md").read_text(),
                         re.DOTALL).group(0)
        self.write("app/app.md", GOOD_PROJECT + "\n" + hint + "\n")
        self.assertIn("template hint (%% … %%) left in the note", self.lint("app/app.md"))

    def test_own_comment_is_not_a_hint(self):
        self.write("app/app.md", GOOD_PROJECT + "\n%% my own standing comment %%\n")
        self.assertEqual(self.lint("app/app.md"), [])

    def test_manual_section_and_code_are_skipped(self):
        # GOOD_PROJECT holds PROJECT_NAME, %% and [[nowhere]] in the manual
        # section and in a code fence. The clean-vault test already proves
        # the linter skips them; this test pins the stale-fence case.
        self.write("app/app.md", GOOD_PROJECT + "\nInline `PROJECT_NAME` stays code.\n")
        self.assertEqual(self.lint("app/app.md"), [])


class TestTemplateParity(LintVaultCase):
    def test_differing_template_is_reported(self):
        tdir = self.vault / "_templates"
        tdir.mkdir()
        for name in ["project.md", "deployment.md"]:
            shutil.copy(ROOT / "templates" / name, tdir / name)
        (tdir / "project.md").write_text("changed\n")
        os.environ["BEARINGS_HOME"] = str(ROOT)
        try:
            problems = template_parity(self.vault)
        finally:
            del os.environ["BEARINGS_HOME"]
        self.assertEqual([p for p, _ in problems], ["_templates/project.md"])


class TestLintHook(LintVaultCase):
    def run_hook(self, file_path):
        payload = json.dumps({"tool_name": "Write",
                              "tool_input": {"file_path": str(file_path)}})
        env = {**os.environ, "BEARINGS_VAULT_DIR": str(self.vault)}
        return subprocess.run([sys.executable, str(ROOT / "scripts" / "lint_hook.py")],
                              input=payload, capture_output=True, text=True, env=env)

    def test_bad_note_exits_2_with_problems_on_stderr(self):
        bad = self.write("app/app@lan.md",
                         GOOD_DEPLOYMENT.replace('host: "[[mac]]"', "host: mac"))
        r = self.run_hook(bad)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("host must be a quoted link", r.stderr)

    def test_good_note_exits_0(self):
        r = self.run_hook(self.vault / "app" / "app.md")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_file_outside_vault_exits_0(self):
        outside = self.tmp / "other.md"
        outside.write_text(GOOD_DEPLOYMENT.replace('host: "[[mac]]"', "host: mac"))
        r = self.run_hook(outside)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_garbage_stdin_exits_0(self):
        env = {**os.environ, "BEARINGS_VAULT_DIR": str(self.vault)}
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "lint_hook.py")],
                           input="not json", capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)


class TestDenyRules(unittest.TestCase):
    def rules(self):
        from bearings_sweep import deny_tools
        return deny_tools(Path("/repo"), Path("/vault"))

    def test_env_example_stays_readable(self):
        rules = self.rules()
        self.assertNotIn(".env.example", rules)
        self.assertIn("Read(**/.env)", rules)
        self.assertIn("Edit(**/.env)", rules)

    def test_run_cannot_change_its_own_guardrails(self):
        from bearings_sweep import BEARINGS_DIR
        rules = self.rules()
        self.assertIn("Edit(//repo/**)", rules)
        self.assertIn("Write(//repo/**)", rules)
        self.assertIn(f"Edit(//{str(BEARINGS_DIR).lstrip('/')}/**)", rules)

    def test_run_cannot_escalate_its_own_permissions(self):
        rules = self.rules()
        for f in ["_Config.md", "_Dashboard.md", "_templates/**"]:
            self.assertIn(f"Edit(//vault/{f})", rules)
            self.assertIn(f"Write(//vault/{f})", rules)

    def test_git_subcommands_have_no_file_reading_forms(self):
        from git_ro import SUBCOMMANDS
        for sub in ["show", "grep", "diff", "cat-file", "-c", "-C", "config"]:
            self.assertNotIn(sub, SUBCOMMANDS)


if __name__ == "__main__":
    unittest.main()

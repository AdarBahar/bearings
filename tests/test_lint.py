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

    def test_dot_git_is_write_denied(self):
        rules = self.rules()
        self.assertIn("Edit(**/.git/**)", rules)
        self.assertIn("Write(**/.git/**)", rules)


class TestGuardFiles(unittest.TestCase):
    def setUp(self):
        self.vault = Path(tempfile.mkdtemp())
        (self.vault / "_Config.md").write_text("config v1\n")
        (self.vault / "_Dashboard.md").write_text("dash v1\n")
        (self.vault / "_templates").mkdir()
        (self.vault / "_templates" / "project.md").write_text("template v1\n")

    def tearDown(self):
        shutil.rmtree(self.vault)

    def test_restore_undoes_every_change(self):
        from bearings_sweep import guard_restore, guard_snapshot
        snap = guard_snapshot(self.vault)
        (self.vault / "_Config.md").write_text("refresh_mode: auto\n")
        (self.vault / "_Dashboard.md").unlink()
        (self.vault / "_templates" / "project.md").write_text("tampered\n")
        (self.vault / "_templates" / "evil.md").write_text("new\n")
        restored = guard_restore(self.vault, snap)
        self.assertEqual(len(restored), 4, restored)
        self.assertEqual((self.vault / "_Config.md").read_text(), "config v1\n")
        self.assertEqual((self.vault / "_Dashboard.md").read_text(), "dash v1\n")
        self.assertEqual((self.vault / "_templates" / "project.md").read_text(),
                         "template v1\n")
        self.assertFalse((self.vault / "_templates" / "evil.md").exists())

    def test_untouched_vault_restores_nothing(self):
        from bearings_sweep import guard_restore, guard_snapshot
        self.assertEqual(guard_restore(self.vault, guard_snapshot(self.vault)), [])


class TestRepoGuard(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)

    def tearDown(self):
        shutil.rmtree(self.repo)

    def test_restore_undoes_config_and_hook_changes(self):
        from bearings_sweep import repo_guard_restore, repo_guard_snapshot
        snap = repo_guard_snapshot(self.repo)
        config = self.repo / ".git" / "config"
        original = config.read_bytes()
        config.write_text(original.decode() + "[core]\n\tfsmonitor = payload\n")
        hook = self.repo / ".git" / "hooks" / "pre-commit"
        hook.write_text("#!/bin/sh\npayload\n")
        info = self.repo / ".git" / "info"
        info.mkdir(exist_ok=True)
        attrs = info / "attributes"
        attrs.write_text("* filter=payload\n")
        worktree = self.repo / ".git" / "config.worktree"
        worktree.write_text("[core]\n\tfsmonitor = payload\n")
        restored = repo_guard_restore(self.repo, snap)
        self.assertEqual(len(restored), 4, restored)
        self.assertEqual(config.read_bytes(), original)
        self.assertFalse(hook.exists())
        self.assertFalse(attrs.exists())
        self.assertFalse(worktree.exists())

    def test_restore_replaces_a_planted_symlink(self):
        from bearings_sweep import repo_guard_restore, repo_guard_snapshot
        snap = repo_guard_snapshot(self.repo)
        config = self.repo / ".git" / "config"
        original = config.read_bytes()
        target = self.repo / "elsewhere"
        target.write_text("outside\n")
        config.unlink()
        config.symlink_to(target)
        repo_guard_restore(self.repo, snap)
        self.assertFalse(config.is_symlink())
        self.assertEqual(config.read_bytes(), original)
        # The restore wrote the file itself, never through the link.
        self.assertEqual(target.read_text(), "outside\n")

    def test_folder_without_git_is_skipped(self):
        from bearings_sweep import repo_guard_restore, repo_guard_snapshot
        plain = self.repo / "plain"
        plain.mkdir()
        self.assertEqual(repo_guard_snapshot(plain), {})
        self.assertEqual(repo_guard_restore(plain, {}), [])


if __name__ == "__main__":
    unittest.main()

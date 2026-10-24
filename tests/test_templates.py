"""Tests for the note templates and the staleness compare.
Run with:  python3 -m unittest discover tests"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from bearings_sweep import is_stale, parse_frontmatter  # noqa: E402

TEMPLATES = ROOT / "templates"


class TestTemplates(unittest.TestCase):
    def test_note_templates_have_type_and_updated(self):
        for name, kind in [("project", "project"), ("deployment", "deployment"),
                           ("archive", "archive"), ("machine", "machine"),
                           ("group", "group")]:
            data = parse_frontmatter((TEMPLATES / f"{name}.md").read_text())
            self.assertIsNotNone(data, name)
            self.assertEqual(data["type"], kind, name)
            self.assertIn("updated", data, name)

    def test_deployment_template_fields(self):
        data = parse_frontmatter((TEMPLATES / "deployment.md").read_text())
        for key in ["project", "env", "status", "host", "urls", "app_path",
                    "run_as", "runtime", "process", "port", "database",
                    "deploy_method", "verified", "verified_how"]:
            self.assertIn(key, data)

    def test_deployment_links_are_quoted_wikilinks(self):
        # The Base views compare project and host with this.file.asLink().
        text = (TEMPLATES / "deployment.md").read_text()
        self.assertIn('project: "[[PROJECT_NAME]]"', text)
        self.assertIn('host: "[[MACHINE]]"', text)

    def test_deployment_hints_list_platform_values(self):
        # Store listings, GitHub hosts and servers that are not yours need these values.
        text = (TEMPLATES / "deployment.md").read_text()
        self.assertIn("| store | testing", text)
        self.assertIn("| github-actions", text)
        self.assertIn('"[[Testing]]"', text)

    def test_base_has_folder_placeholder(self):
        text = (TEMPLATES / "_Deployments.base").read_text()
        self.assertIn("__BEARINGS_FOLDER__", text)
        self.assertIn("name: Linked to this note", text)


class TestIsStale(unittest.TestCase):
    def test_date_only(self):
        self.assertTrue(is_stale("2026-10-24", "2026-10-23"))
        self.assertFalse(is_stale("2026-10-23", "2026-10-23"))

    def test_date_with_time(self):
        self.assertTrue(is_stale("2026-10-24", "2026-10-23T14:05"))
        self.assertFalse(is_stale("2026-10-23", "2026-10-23T14:05"))
        self.assertFalse(is_stale("2026-10-22", "2026-10-23T09:00"))


if __name__ == "__main__":
    unittest.main()

"""Tests for the dependency-free frontmatter parser that drives all Bearings
configuration. Run with:  python3 -m unittest discover tests"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from bearings_sweep import parse_frontmatter, parse_value  # noqa: E402


def fm(body):
    return parse_frontmatter(f"---\n{body}\n---\n")


class TestParseFrontmatter(unittest.TestCase):
    def test_empty_inline_lists(self):
        result = fm("cadence: weekly-monday\nexclude: []\naliases: []")
        self.assertEqual(result["exclude"], [])
        self.assertEqual(result["aliases"], [])
        self.assertEqual(result["cadence"], "weekly-monday")

    def test_inline_list_with_items(self):
        result = fm('include: ["*", "project-*"]\nexclude: [tmp-*]')
        self.assertEqual(result["include"], ["*", "project-*"])
        self.assertEqual(result["exclude"], ["tmp-*"])

    def test_multiline_list(self):
        result = fm('include:\n  - "*"\n  - "project-*"')
        self.assertEqual(result["include"], ["*", "project-*"])

    def test_empty_value(self):
        result = fm("exclude:")
        self.assertEqual(result["exclude"], [])

    def test_scalars(self):
        result = fm('refresh_mode: auto\nbudget_alert_usd: 10\nname: "quoted value"')
        self.assertEqual(result["refresh_mode"], "auto")
        self.assertEqual(result["budget_alert_usd"], "10")
        self.assertEqual(result["name"], "quoted value")

    def test_inline_comments_stripped(self):
        result = fm("cadence: daily  # runs every day\nexclude: []  # nothing excluded")
        self.assertEqual(result["cadence"], "daily")
        self.assertEqual(result["exclude"], [])

    def test_machines_block_list(self):
        result = fm('machines:\n  - "mac | local | ~/Code"\n  - "laptop | ssh=linux | ~/Code"')
        self.assertEqual(result["machines"],
                         ["mac | local | ~/Code", "laptop | ssh=linux | ~/Code"])

    def test_no_frontmatter(self):
        self.assertIsNone(parse_frontmatter("# just a heading\n"))


class TestParseValue(unittest.TestCase):
    def test_empty_flow_list(self):
        self.assertEqual(parse_value(" []"), [])

    def test_flow_list_mixed_quoting(self):
        self.assertEqual(parse_value(' ["a", b, \'c\']'), ["a", "b", "c"])

    def test_plain_and_empty(self):
        self.assertEqual(parse_value(" hello"), "hello")
        self.assertEqual(parse_value(""), [])


if __name__ == "__main__":
    unittest.main()

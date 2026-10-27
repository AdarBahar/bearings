"""Tests for the budget stop settings and the email notification.
Run with:  python3 -m unittest discover tests"""

import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import bearings_sweep  # noqa: E402
from bearings_sweep import (build_notification, load_config,  # noqa: E402
                            notify_sweep, should_notify, smtp_settings)

TODAY = date(2026, 10, 27)

CONFIG = """---
cadence: manual
machines:
  - "mac | local | ~/Code"
budget_stop_usd: {stop}
notify: {notify}
notify_email: {email}
---
"""

SMTP_ENV = {"BEARINGS_SMTP_HOST": "smtp.example.com",
            "BEARINGS_SMTP_USER": "me@example.com",
            "BEARINGS_SMTP_PASS": "app-password"}


def config(stop="0", notify="off", email=""):
    tmp = Path(tempfile.mkdtemp())
    (tmp / "_Config.md").write_text(
        CONFIG.format(stop=stop, notify=notify, email=email))
    return load_config(tmp)


class TestConfig(unittest.TestCase):
    def test_budget_stop_and_notify_parse(self):
        cfg, errors = config(stop="12.5", notify="on-action", email="a@b.c")
        self.assertEqual(errors, [])
        self.assertEqual(cfg["budget_stop_usd"], 12.5)
        self.assertEqual(cfg["notify"], "on-action")
        self.assertEqual(cfg["notify_email"], "a@b.c")

    def test_bad_values_fall_back_with_errors(self):
        cfg, errors = config(stop="lots", notify="sometimes")
        self.assertEqual(cfg["budget_stop_usd"], 0)
        self.assertEqual(cfg["notify"], "off")
        self.assertTrue(any("budget_stop_usd" in e for e in errors))
        self.assertTrue(any("notify" in e for e in errors))


class TestSmtpSettings(unittest.TestCase):
    def test_complete_settings_with_defaults(self):
        s = smtp_settings(SMTP_ENV)
        self.assertEqual(s["port"], 587)
        self.assertEqual(s["from"], "me@example.com")

    def test_missing_values_give_none(self):
        self.assertIsNone(smtp_settings({}))
        self.assertIsNone(smtp_settings(
            {k: v for k, v in SMTP_ENV.items() if k != "BEARINGS_SMTP_PASS"}))

    def test_port_and_from_overrides(self):
        s = smtp_settings({**SMTP_ENV, "BEARINGS_SMTP_PORT": "465",
                           "BEARINGS_SMTP_FROM": "bot@example.com"})
        self.assertEqual(s["port"], 465)
        self.assertEqual(s["from"], "bot@example.com")


class TestShouldNotify(unittest.TestCase):
    def test_policies(self):
        self.assertFalse(should_notify("off", ["refreshed x"], True))
        self.assertTrue(should_notify("always", [], False))
        self.assertTrue(should_notify("on-action", ["refreshed x"], False))
        self.assertTrue(should_notify("on-action", [], True))
        self.assertFalse(should_notify("on-action", [], False))

    def test_paid_work_without_actions_notifies(self):
        # A failed canary spends money but adds no action line.
        self.assertTrue(should_notify("on-action", [], False, cost=0.01))
        self.assertFalse(should_notify("on-action", [], False, cost=0.0))


class TestBuildNotification(unittest.TestCase):
    def test_normal_sweep_email(self):
        subject, body = build_notification(
            TODAY, "**2026-10-27** — 0 new", "**2026-10**: 1 runs · $0.40",
            [], False, 0, ["refreshed app"])
        self.assertIn("1 action(s)", subject)
        self.assertNotIn("FAILED", subject)
        self.assertIn("$0.40", body)
        self.assertIn("_Dashboard.md", body)

    def test_budget_stop_email_says_what_to_do(self):
        subject, body = build_notification(
            TODAY, "last", "month", ["budget stop — ..."], True, 10.0, [])
        self.assertIn("budget stop reached", subject)
        self.assertIn("budget_stop_usd ($10.00)", body)
        self.assertIn("Raise or remove budget_stop_usd", body)
        self.assertIn("Warnings:", body)

    def test_failed_action_shows_in_the_subject(self):
        subject, _ = build_notification(
            TODAY, "last", "month", [], False, 0, ["refresh FAILED app"])
        self.assertIn("FAILED", subject)

    def test_failed_canary_shows_in_the_subject(self):
        subject, body = build_notification(
            TODAY, "last", "month",
            ["canary FAILED — headless runs do not load the skill"],
            False, 0, [])
        self.assertIn("canary FAILED", subject)
        self.assertIn("canary FAILED", body)


class TestNotifySweep(unittest.TestCase):
    def cfg(self, notify="on-action", email="a@b.c"):
        return {"notify": notify, "notify_email": email, "budget_stop_usd": 0}

    def test_off_sends_nothing(self):
        with mock.patch.object(bearings_sweep, "send_email") as send:
            notify_sweep(SMTP_ENV, self.cfg(notify="off"), [], TODAY,
                         "last", "month", False, ["refreshed app"])
        send.assert_not_called()

    def test_missing_email_warns(self):
        warnings = []
        with mock.patch.object(bearings_sweep, "send_email") as send:
            notify_sweep(SMTP_ENV, self.cfg(email=""), warnings, TODAY,
                         "last", "month", False, ["refreshed app"])
        send.assert_not_called()
        self.assertTrue(any("notify_email is empty" in w for w in warnings))

    def test_missing_smtp_settings_warn(self):
        warnings = []
        with mock.patch.object(bearings_sweep, "send_email") as send:
            notify_sweep({}, self.cfg(), warnings, TODAY,
                         "last", "month", False, ["refreshed app"])
        send.assert_not_called()
        self.assertTrue(any("SMTP settings are missing" in w for w in warnings))

    def test_sends_and_a_failure_becomes_a_warning(self):
        warnings = []
        with mock.patch.object(bearings_sweep, "send_email") as send:
            notify_sweep(SMTP_ENV, self.cfg(), warnings, TODAY,
                         "last", "month", False, ["refreshed app"])
        send.assert_called_once()
        self.assertEqual(send.call_args[0][1], "a@b.c")
        self.assertEqual(warnings, [])
        with mock.patch.object(bearings_sweep, "send_email",
                               side_effect=OSError("no route")):
            notify_sweep(SMTP_ENV, self.cfg(), warnings, TODAY,
                         "last", "month", False, ["refreshed app"])
        self.assertTrue(any("notification email failed" in w for w in warnings))

    def test_no_action_no_email_under_on_action(self):
        with mock.patch.object(bearings_sweep, "send_email") as send:
            notify_sweep(SMTP_ENV, self.cfg(), [], TODAY,
                         "last", "month", False, [])
        send.assert_not_called()

    def test_paid_canary_failure_sends_an_email(self):
        with mock.patch.object(bearings_sweep, "send_email") as send:
            notify_sweep(SMTP_ENV, self.cfg(),
                         ["canary FAILED — bare mode?"], TODAY,
                         "last", "month", False, [], cost=0.01)
        send.assert_called_once()
        self.assertIn("canary FAILED", send.call_args[0][2])


if __name__ == "__main__":
    unittest.main()

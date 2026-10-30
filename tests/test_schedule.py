"""Tests for the cron fallback in install-schedule.sh, with a fake crontab.
Run with:  python3 -m unittest discover tests"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "install-schedule.sh"

FAKE_CRONTAB = """#!/bin/bash
store="$FAKE_DIR/crontab.txt"
if [ "$1" = "-l" ]; then
  if [ -f "$store" ]; then cat "$store"; else echo "no crontab for user" >&2; exit 1; fi
elif [ "$1" = "-r" ]; then rm -f "$store"
else cat > "$store"; fi
"""


class TestCronFallback(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        bindir = self.tmp / "bin"
        bindir.mkdir()
        (bindir / "uname").write_text("#!/bin/sh\necho Linux\n")
        (bindir / "crontab").write_text(FAKE_CRONTAB)
        for f in bindir.iterdir():
            f.chmod(0o755)
        self.store = self.tmp / "crontab.txt"
        self.env = {"PATH": f"{bindir}:/usr/bin:/bin", "HOME": str(self.tmp),
                    "FAKE_DIR": str(self.tmp)}

    def run_script(self, *args):
        return subprocess.run(["bash", str(SCRIPT), *args], env=self.env,
                              capture_output=True, text=True)

    def test_first_install_without_a_crontab(self):
        r = self.run_script("08:30")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.store.read_text().count("# bearings-sweep"), 1)

    def test_reinstall_keeps_other_entries_and_one_bearings_line(self):
        self.store.write_text("0 1 * * * other-job\n")
        self.assertEqual(self.run_script().returncode, 0)
        self.assertEqual(self.run_script("10:15").returncode, 0)
        text = self.store.read_text()
        self.assertIn("0 1 * * * other-job", text)
        self.assertEqual(text.count("# bearings-sweep"), 1)
        self.assertIn("15 10 * * *", text)

    def test_reinstall_when_only_the_old_entry_exists(self):
        self.store.write_text("0 9 * * * old # bearings-sweep\n")
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.store.read_text().count("# bearings-sweep"), 1)

    def test_uninstall_keeps_other_entries(self):
        self.store.write_text("0 1 * * * other-job\n0 9 * * * old # bearings-sweep\n")
        r = self.run_script("--uninstall")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.store.read_text(), "0 1 * * * other-job\n")

    def test_uninstall_with_only_the_old_entry(self):
        self.store.write_text("0 9 * * * old # bearings-sweep\n")
        r = self.run_script("--uninstall")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("schedule removed", r.stdout)
        self.assertFalse(self.store.exists())

    def test_a_real_listing_error_stops_the_script(self):
        (self.tmp / "bin" / "crontab").write_text(
            '#!/bin/bash\n[ "$1" = "-l" ] && { echo "permission denied" >&2; exit 1; }\ncat > "$FAKE_DIR/crontab.txt"\n')
        r = self.run_script()
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(self.store.exists())


if __name__ == "__main__":
    unittest.main()

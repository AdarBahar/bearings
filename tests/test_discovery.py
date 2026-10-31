"""Tests for the early filter and the pruned folder walk in project discovery.
Run with:  python3 -m unittest discover tests"""

import os
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


def gnu_find():
    try:
        out = subprocess.run(["find", "--version"], capture_output=True, text=True).stdout
    except OSError:
        return False
    return "GNU" in out


class TestLocalFilter(unittest.TestCase):
    def test_excluded_folder_is_not_scanned(self):
        base = Path(tempfile.mkdtemp())
        for n in ("keep", "skip"):
            (base / n).mkdir()
            (base / n / "a.txt").write_text("x")
        with mock.patch.object(bearings_sweep, "newest_mtime_local",
                               return_value="2026-10-30T10:00") as scan:
            out = bearings_sweep.local_projects([str(base)], lambda name, is_git: name != "skip")
        self.assertEqual([o[0] for o in out], ["keep"])
        self.assertEqual([c.args[0].name for c in scan.call_args_list], ["keep"])

    def test_git_log_is_skipped_for_excluded_repo(self):
        base = Path(tempfile.mkdtemp())
        (base / "skip" / ".git").mkdir(parents=True)
        with mock.patch.object(bearings_sweep, "run") as run:
            out = bearings_sweep.local_projects([str(base)], lambda name, is_git: False)
        self.assertEqual(out, [])
        run.assert_not_called()


class TestGitfile(unittest.TestCase):
    def test_worktree_without_note_is_found_under_default_include(self):
        base = Path(tempfile.mkdtemp())
        wt = base / "wt"
        wt.mkdir()
        (wt / ".git").write_text("gitdir: /elsewhere/.git/worktrees/wt\n")
        (base / "plain").mkdir()
        (base / "bogus").mkdir()
        (base / "bogus" / ".git").write_text("not a gitfile\n")
        seen = {}
        def wanted(name, is_git):
            seen[name] = is_git
            return False
        bearings_sweep.local_projects([str(base)], wanted)
        self.assertEqual(seen, {"wt": True, "plain": False, "bogus": False})
        cfg = {"include": ["*"], "exclude": []}
        self.assertTrue(bearings_sweep.allowed(cfg, "m", "wt", True, False))

    def test_a_fifo_named_git_does_not_block(self):
        base = Path(tempfile.mkdtemp())
        (base / "evil").mkdir()
        os.mkfifo(base / "evil" / ".git")
        d = base / "evil"
        self.assertFalse(bearings_sweep.is_git_folder(d))

    def test_remote_scripts_test_for_a_gitfile(self):
        m = {"ssh": "h", "dirs": ["/code"]}
        self.assertIn("gitdir:", bearings_sweep.remote_list_script(m))
        self.assertIn("gitdir:", bearings_sweep.remote_script(m))

    @unittest.skipUnless(shutil.which("sh"), "needs sh")
    def test_remote_list_script_classifies_a_worktree(self):
        base = Path(tempfile.mkdtemp())
        (base / "wt").mkdir()
        (base / "wt" / ".git").write_text("gitdir: /x\n")
        (base / "plain").mkdir()
        out = subprocess.run(["sh", "-c", bearings_sweep.remote_list_script(
            {"ssh": "h", "dirs": [str(base)]})], capture_output=True, text=True).stdout
        self.assertIn(f"git|{base}/wt/", out)
        self.assertIn(f"dir|{base}/plain/", out)


class TestRemoteHome(unittest.TestCase):
    def test_ssh_machine_keeps_the_tilde(self):
        errors = []
        ms = bearings_sweep.parse_machines(
            ["mac | local | ~/Code", "box | ssh=linux | ~/Code"], errors)
        self.assertEqual(ms[0]["dirs"], [os.path.expanduser("~/Code")])
        self.assertEqual(ms[1]["dirs"], ["~/Code"])

    def test_remote_home_resolves_on_the_remote_shell(self):
        base = Path(tempfile.mkdtemp())
        (base / "Code" / "a b").mkdir(parents=True)
        word = bearings_sweep.remote_dirs({"dirs": ["~/Code"]})
        self.assertTrue(word.startswith('"$HOME"/'))
        out = subprocess.run(["sh", "-c", f"for d in {word}; do echo \"$d\"; done"],
                             env={"HOME": str(base), "PATH": os.environ["PATH"]},
                             capture_output=True, text=True).stdout
        self.assertEqual(out.strip(), f"{base}/Code/a b/")

    def test_shell_substitution_in_a_name_stays_literal(self):
        marker = Path(tempfile.mkdtemp()) / "ran"
        word = bearings_sweep.remote_word(f"~/$(touch {marker})")
        subprocess.run(["sh", "-c", f"echo {word}"], capture_output=True,
                       env={"HOME": "/tmp", "PATH": os.environ["PATH"]})
        self.assertFalse(marker.exists())


class TestDiscoveryTimeout(unittest.TestCase):
    machine = {"ssh": "h", "dirs": ["/code"]}

    def test_ssh_timeout_in_the_listing_phase_means_unreachable(self):
        with mock.patch.object(bearings_sweep, "run",
                               side_effect=subprocess.TimeoutExpired("ssh", 1)):
            self.assertIsNone(bearings_sweep.remote_projects(self.machine, lambda n, g: True))

    def test_ssh_timeout_in_the_scan_phase_means_unreachable(self):
        with mock.patch.object(bearings_sweep, "run") as run:
            run.side_effect = [mock.Mock(returncode=0, stdout="git|/code/a/\n"),
                               subprocess.TimeoutExpired("ssh", 1)]
            self.assertIsNone(bearings_sweep.remote_projects(self.machine, lambda n, g: True))

    def test_ssh_call_has_a_timeout(self):
        with mock.patch.object(bearings_sweep, "run") as run:
            run.return_value = mock.Mock(returncode=0, stdout="")
            bearings_sweep.remote_projects(self.machine)
        self.assertEqual(run.call_args.kwargs["timeout"], bearings_sweep.DISCOVERY_TIMEOUT)

    def test_local_git_timeout_skips_only_that_project(self):
        base = Path(tempfile.mkdtemp())
        (base / "slow" / ".git").mkdir(parents=True)
        with mock.patch.object(bearings_sweep, "run",
                               side_effect=subprocess.TimeoutExpired("git", 1)):
            self.assertEqual(bearings_sweep.local_projects([str(base)]), [])


def hostile_repo(base):
    """A repo whose config names a signature program, and whose newest commit
    carries a (fake) signature. `git log` with log.showSignature=true runs the
    program. Returns (repo, marker); the marker file exists only if it ran."""
    repo = base / "evil"
    repo.mkdir()
    marker = base / "ran"
    prog = base / "gpg.sh"
    prog.write_text(f"#!/bin/sh\ntouch '{marker}'\nexit 1\n")
    prog.chmod(0o755)
    git = ["git", "-C", str(repo)]
    subprocess.run([*git, "init", "-q"], check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t"), ("gpg.program", str(prog)),
                 ("log.showSignature", "true")):
        subprocess.run([*git, "config", k, v], check=True)
    subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "x"], check=True)
    head = subprocess.run([*git, "cat-file", "commit", "HEAD"], capture_output=True,
                          text=True, check=True).stdout
    header, _, msg = head.partition("\n\n")
    signed = header + "\ngpgsig -----BEGIN PGP SIGNATURE-----\n \n abc\n -----END PGP SIGNATURE-----\n\n" + msg
    sha = subprocess.run([*git, "hash-object", "-t", "commit", "-w", "--stdin"], input=signed,
                         capture_output=True, text=True, check=True).stdout.strip()
    subprocess.run([*git, "update-ref", "HEAD", sha], check=True)
    return repo, marker


class TestGitHardening(unittest.TestCase):
    def test_setup_really_triggers_the_program_without_the_options(self):
        repo, marker = hostile_repo(Path(tempfile.mkdtemp()))
        subprocess.run(["git", "-C", str(repo), "log", "-1", "--format=%ct"], capture_output=True)
        self.assertTrue(marker.exists(), "test setup is wrong: the program did not run")

    def test_local_discovery_does_not_run_the_program(self):
        base = Path(tempfile.mkdtemp())
        repo, marker = hostile_repo(base)
        out = bearings_sweep.local_projects([str(base)])
        self.assertEqual([o[0] for o in out], ["evil"])
        self.assertFalse(marker.exists())

    def test_remote_script_does_not_run_the_program(self):
        base = Path(tempfile.mkdtemp())
        repo, marker = hostile_repo(base)
        script = bearings_sweep.remote_script({"dirs": [str(base)]})
        out = subprocess.run(["bash", "-c", script], capture_output=True, text=True).stdout
        self.assertIn("evil|", out)
        self.assertFalse(marker.exists())


class TestRemoteFilter(unittest.TestCase):
    machine = {"ssh": "h", "dirs": ["/code"]}

    def test_only_wanted_folders_reach_the_scan(self):
        listing = "git|/code/keep/\ndir|/code/skip/\ndir|/code/plain/\n"
        scan = "keep|1761818400|git|/code/keep/\n"
        with mock.patch.object(bearings_sweep, "run") as run:
            run.side_effect = [mock.Mock(returncode=0, stdout=listing),
                               mock.Mock(returncode=0, stdout=scan)]
            seen = []
            def wanted(name, is_git):
                seen.append((name, is_git))
                return name == "keep"
            out = bearings_sweep.remote_projects(self.machine, wanted)
        self.assertEqual(seen, [("keep", True), ("skip", False), ("plain", False)])
        self.assertEqual([o[0] for o in out], ["keep"])
        script = run.call_args_list[1][0][0][-1]
        self.assertIn("/code/keep/", script)
        self.assertNotIn("skip", script)
        self.assertNotIn("plain", script)

    def test_no_wanted_folder_means_no_scan_call(self):
        with mock.patch.object(bearings_sweep, "run") as run:
            run.return_value = mock.Mock(returncode=0, stdout="dir|/code/a/\n")
            self.assertEqual(bearings_sweep.remote_projects(self.machine, lambda n, g: False), [])
        self.assertEqual(run.call_count, 1)

    def test_unreachable_host_returns_none(self):
        with mock.patch.object(bearings_sweep, "run") as run:
            run.return_value = mock.Mock(returncode=255, stdout="")
            self.assertIsNone(bearings_sweep.remote_projects(self.machine, lambda n, g: True))

    def test_without_wanted_one_call_scans_all(self):
        with mock.patch.object(bearings_sweep, "run") as run:
            run.return_value = mock.Mock(returncode=0, stdout="")
            bearings_sweep.remote_projects(self.machine)
        self.assertEqual(run.call_count, 1)
        self.assertIn("/code/*/", run.call_args[0][0][-1])

    def test_script_prunes_instead_of_filtering(self):
        script = bearings_sweep.remote_script(self.machine)
        self.assertIn("-prune", script)
        self.assertNotIn("-not -path", script)

    def test_path_with_shell_syntax_stays_literal(self):
        marker = Path(tempfile.mkdtemp()) / "pwned"
        script = bearings_sweep.remote_script(self.machine, [f"/nonexistent/$(touch {marker})/"])
        subprocess.run(["bash", "-c", script])
        self.assertFalse(marker.exists())


@unittest.skipUnless(gnu_find(), "needs GNU find (-printf)")
class TestPrunedFindBehavior(unittest.TestCase):
    def scan(self, base):
        script = bearings_sweep.remote_script({"dirs": [str(base)]})
        out = subprocess.run(["bash", "-c", script], capture_output=True, text=True).stdout
        return {line.split("|")[0]: line.split("|")[1] for line in out.splitlines()}

    def test_pruned_folders_do_not_set_the_stamp(self):
        base = Path(tempfile.mkdtemp())
        proj = base / "proj"
        for rel, mtime in (("a.txt", 1000), ("node_modules/n.txt", 5000),
                           ("sub/data/d.txt", 6000), ("x.log", 7000), ("sub/b.txt", 2000)):
            f = proj / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("x")
            os.utime(f, (mtime, mtime))
        self.assertEqual(float(self.scan(base)["proj"]), 2000.0)

    def test_project_named_like_a_pruned_folder_is_scanned(self):
        base = Path(tempfile.mkdtemp())
        (base / "data").mkdir()
        f = base / "data" / "a.txt"
        f.write_text("x")
        os.utime(f, (3000, 3000))
        self.assertEqual(float(self.scan(base)["data"]), 3000.0)


if __name__ == "__main__":
    unittest.main()

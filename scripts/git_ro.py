#!/usr/bin/env python3
"""Read-only git for headless bearings runs.

The headless allowlist does not include plain `git`. A prefix permission
rule cannot see a later flag, and git has flags that write files (`log
--output=<file>`), run commands (`-c core.fsmonitor=…`) or change the repo
(`tag <name>`, `remote add`). This wrapper is an allowlist, not a denylist:
it accepts a fixed set of subcommands, and for each one a fixed set of
read-only flags. Everything else is rejected, including abbreviated long
options, because an unknown flag never matches the list.

Git itself runs hardened: no pager, no system config, no fsmonitor and no
hooks path from the repo configuration.

Usage: git_ro.py <subcommand> [args ...]
Exit codes: git's own, or 1 when an argument is not allowed.
"""

import os
import subprocess
import sys
from pathlib import Path

# No `status` and no modification checks: they can re-read racily-clean
# files through a clean filter, and `filter.<name>.clean` is a program
# named by attributes the repo controls.
SUBCOMMANDS = {"log", "shortlog", "remote", "tag", "branch",
               "rev-parse", "describe", "ls-files"}

# Per subcommand: the read-only flags the bearings skills need. A flag
# matches exactly, or as "<flag>=<value>". "--" is always allowed.
FLAGS = {
    "log": {"--since", "--until", "--author", "--committer", "--grep",
            "--format", "--pretty", "--date", "--oneline", "--no-merges",
            "--merges", "--first-parent", "--all", "--tags", "--branches",
            "--reverse", "--max-count", "-n", "--abbrev-commit", "--decorate",
            "--name-only", "--name-status", "--follow"},
    "shortlog": {"-s", "-n", "-e", "--since", "--until", "--no-merges"},
    "remote": {"-v", "--verbose"},
    "tag": {"--list", "-l", "--sort", "-n", "--contains", "--points-at",
            "--merged", "--no-merged"},
    "branch": {"--list", "-l", "-a", "-r", "--all", "--remotes", "-v", "-vv",
               "--verbose", "--sort", "--contains", "--merged", "--no-merged",
               "--show-current"},
    "rev-parse": {"--show-toplevel", "--abbrev-ref", "--short", "--verify",
                  "--is-inside-work-tree", "--git-dir"},
    "describe": {"--tags", "--always", "--abbrev", "--long", "--match"},
    "ls-files": {"-z", "--others", "-o", "--exclude-standard", "--cached",
                 "-c", "--full-name"},
}

# --pretty and --format accept only an inline format string or a built-in
# name. A repo can define pretty.<alias> in its config, and an alias can
# expand to %G placeholders, so alias names are rejected.
BUILTIN_PRETTY = {"oneline", "short", "medium", "full", "fuller", "raw",
                  "reference", "email"}


def flag_allowed(arg, allowed):
    if arg == "--":
        return True
    # A bare count such as -3 is a read-only shorthand for --max-count.
    if arg[1:].isdigit():
        return True
    return any(arg == f or arg.startswith(f + "=") for f in allowed)


def main(argv):
    if not argv:
        print("usage: git_ro.py <subcommand> [args ...]", file=sys.stderr)
        return 1
    sub, args = argv[0], argv[1:]
    if sub not in SUBCOMMANDS:
        print(f"git_ro: subcommand not allowed: {sub}", file=sys.stderr)
        return 1
    allowed = FLAGS[sub]
    positionals = []
    for a in args:
        if a.startswith("-"):
            if not flag_allowed(a, allowed):
                print(f"git_ro: argument not allowed: {a}", file=sys.stderr)
                return 1
            if a.startswith(("--format=", "--pretty=")):
                value = a.split("=", 1)[1]
                inline = value.startswith(("format:", "tformat:")) or "%" in value
                if not inline and value not in BUILTIN_PRETTY:
                    print(f"git_ro: pretty alias not allowed: {a}", file=sys.stderr)
                    return 1
                # %G placeholders verify signatures, which runs a gpg program.
                if "%G" in value:
                    print(f"git_ro: %G placeholders are not allowed: {a}",
                          file=sys.stderr)
                    return 1
        else:
            positionals.append(a)
    # `git remote <positional>` is a mutating sub-subcommand (add, set-url,
    # …) except get-url, which only prints.
    if sub == "remote" and positionals and positionals[0] != "get-url":
        print(f"git_ro: 'git remote {positionals[0]}' is not allowed",
              file=sys.stderr)
        return 1
    # For tag and branch, a positional without --list creates a ref. Force
    # list mode, so positionals are only patterns.
    if sub in ("tag", "branch") and not any(a in ("-l", "--list") for a in args):
        args = ["--list"] + args

    # Git reads configuration from the system, the user and the repo. The
    # repo copy is attacker-influenced in a scanned external project, and
    # several keys name a program to run. Command-line -c outranks every
    # file, so override each such key; the fail-closed value is `false`.
    # The system and global files are skipped completely, and discovery
    # stops at the project folder.
    env = {**os.environ,
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
           "GIT_ATTR_NOSYSTEM": "1", "GIT_PAGER": "cat",
           "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0",
           "GIT_CEILING_DIRECTORIES": str(Path.cwd().parent)}
    base = ["git", "--no-pager",
            "-c", "core.pager=cat",
            "-c", "core.fsmonitor=false",
            "-c", "core.hooksPath=" + os.devnull,
            "-c", "core.attributesFile=" + os.devnull,
            "-c", "log.showSignature=false",
            "-c", "gpg.format=openpgp",
            "-c", "gpg.program=false",
            "-c", "gpg.x509.program=false",
            "-c", "gpg.ssh.program=false",
            "-c", "diff.external=false",
            "-c", "safe.bareRepository=explicit"]
    return subprocess.call(base + [sub] + args, env=env)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

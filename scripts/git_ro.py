#!/usr/bin/env python3
"""Read-only git for headless bearings runs.

The headless allowlist does not include plain `git`. A prefix permission
rule cannot see a later flag, and some flags change `git log` into a file
write (`--output=<file>`) or a subcommand into a repo change (`git tag
<name>`, `git remote add`). This wrapper vets the subcommand and every
argument, then calls git in the current directory.

Usage: git_ro.py <subcommand> [args ...]
Exit codes: git's own, or 1 when an argument is not allowed.
"""

import subprocess
import sys

SUBCOMMANDS = {"log", "shortlog", "remote", "status", "tag", "branch",
               "rev-parse", "describe", "ls-files"}

# Arguments that write files or change the repo, wherever they appear.
BLOCKED = {"-d", "-D", "-m", "-M", "-f", "--force", "--delete", "--move",
           "--copy", "--edit", "add", "remove", "rename", "rm", "set-url",
           "set-head", "set-branches", "prune", "update"}
BLOCKED_PREFIXES = ("--output",)

# For these, a positional argument without a list flag creates a ref.
CREATE_CAPABLE = {"tag", "branch"}
LIST_FLAGS = ("-l", "--list", "-n")


def main(argv):
    if not argv:
        print("usage: git_ro.py <subcommand> [args ...]", file=sys.stderr)
        return 1
    sub, args = argv[0], argv[1:]
    if sub not in SUBCOMMANDS:
        print(f"git_ro: subcommand not allowed: {sub}", file=sys.stderr)
        return 1
    for a in args:
        if a in BLOCKED or a.startswith(BLOCKED_PREFIXES):
            print(f"git_ro: argument not allowed: {a}", file=sys.stderr)
            return 1
    if sub in CREATE_CAPABLE:
        has_list = any(a == f or a.startswith(f) for a in args for f in LIST_FLAGS)
        positional = [a for a in args if not a.startswith("-")]
        if positional and not has_list:
            print(f"git_ro: 'git {sub} <name>' creates a ref — use --list",
                  file=sys.stderr)
            return 1
    return subprocess.call(["git", sub] + args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

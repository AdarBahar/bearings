#!/usr/bin/env python3
"""PreToolUse hook for headless bearings runs.

A deny glob cannot say "every .env file except the templates". This hook
can: it blocks Read, Edit, Write, Grep and notebook edits on the .env
family before the tool runs, and it lets the secret-free template names
through. The check folds case and resolves symlinks, so .ENV.PROD and a
link that points at a .env file are blocked too. Exit code 2 blocks the
call, and Claude gets the reason on stderr.
"""

import json
import os
import sys
from pathlib import Path

SAFE = {".env.example", ".env.sample", ".env.dist", ".env.template"}


def _name_blocked(name):
    n = name.lower()
    return (n == ".env" or n.startswith(".env.")) and n not in SAFE


def is_blocked(file_path):
    """The given name, and the name the path resolves to."""
    names = {Path(file_path).name, Path(os.path.realpath(file_path)).name}
    return any(_name_blocked(n) for n in names)


def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    tool_input = data.get("tool_input") or {}
    for key in ("file_path", "path", "notebook_path"):
        value = tool_input.get(key)
        if value and is_blocked(str(value)):
            print(f"bearings guard: {Path(str(value)).name} can hold secrets "
                  "— read .env.example or the code instead", file=sys.stderr)
            return 2
    # A Grep glob that targets the .env family is a read of it.
    glob = tool_input.get("glob")
    if glob and ".env" in str(glob).lower() \
            and Path(str(glob)).name.lower() not in SAFE:
        print(f"bearings guard: the glob {glob!r} targets .env files — "
              "read .env.example or the code instead", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""PreToolUse hook for headless bearings runs.

A deny glob cannot say "every .env file except the templates". This hook
can: it blocks Read, Edit, Write, Grep and notebook edits on the .env
family before the tool runs, and it lets the secret-free template names
through. The check folds case and resolves symlinks, so .ENV.PROD and a
link that points at a .env file are blocked too. Exit code 2 blocks the
call, and Claude gets the reason on stderr.
"""

import fnmatch
import json
import os
import sys
from pathlib import Path

SAFE = {".env.example", ".env.sample", ".env.dist", ".env.template"}

# Names a search glob must not be able to reach.
PROBE_NAMES = (".env", ".env.x", ".env.local", ".env.prod")


def _name_blocked(name):
    n = name.lower()
    return (n == ".env" or n.startswith(".env.")) and n not in SAFE


def is_blocked(file_path):
    """The given name, and the name the path resolves to."""
    names = {Path(file_path).name, Path(os.path.realpath(file_path)).name}
    return any(_name_blocked(n) for n in names)


def glob_may_match_env(glob):
    """True when the glob can reach a non-template .env name. A bare *,
    .*, or .env* can; *.py cannot; an exact template name cannot."""
    base = str(glob).replace("\\", "/").split("/")[-1].lower()
    if base in SAFE:
        return False
    return any(fnmatch.fnmatch(name, base) for name in PROBE_NAMES)


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
    # A glob that can reach the .env family is a read of it.
    glob = tool_input.get("glob")
    if glob and glob_may_match_env(glob):
        print(f"bearings guard: the glob {glob!r} can reach .env files — "
              "narrow it (for example *.py)", file=sys.stderr)
        return 2
    # A folder-scoped Grep searches every file in the tree, the .env
    # family among them, so it needs a filter that excludes that family.
    if data.get("tool_name") == "Grep":
        path = tool_input.get("path")
        dir_scope = not path or Path(str(path)).is_dir()
        if dir_scope and not tool_input.get("type") and not glob:
            print("bearings guard: a folder Grep needs a glob or type that "
                  "excludes .env files (for example glob *.py)", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

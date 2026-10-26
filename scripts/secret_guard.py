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
import re
import sys
import time
from pathlib import Path

SAFE = {".env.example", ".env.sample", ".env.dist", ".env.template"}

# A plain file name without a leading dot: it can match only itself.
LITERAL_GLOB = re.compile(r"[a-z0-9][a-z0-9._-]*")

# The scope scan fails closed when it cannot finish well inside the hook
# timeout. A scope too large to scan is a scope too large to clear.
SCAN_MAX_ENTRIES = 20000
SCAN_MAX_SECONDS = 3.0


def _name_blocked(name):
    n = name.lower()
    return (n == ".env" or n.startswith(".env.")) and n not in SAFE


def is_blocked(file_path):
    """The given name, and the name the path resolves to."""
    names = {Path(file_path).name, Path(os.path.realpath(file_path)).name}
    return any(_name_blocked(n) for n in names)


def scope_has_env(scope):
    """True when a non-template .env file exists under the scope, by its
    own name or as a symlink target. The guard reasons about the files
    that really exist, never about what a glob or type filter might mean,
    so there is no parser to disagree with. Nothing is pruned — the
    search may see folders a pruned scan would have skipped — and an
    unknown scope or a budget overrun fails closed."""
    if not scope or not Path(str(scope)).is_dir():
        return True
    deadline = time.monotonic() + SCAN_MAX_SECONDS
    entries = 0
    for root, dirs, files in os.walk(str(scope)):
        entries += len(dirs) + len(files)
        if entries > SCAN_MAX_ENTRIES or time.monotonic() > deadline:
            return True
        for f in files:
            if _name_blocked(f):
                return True
            p = os.path.join(root, f)
            if os.path.islink(p) \
                    and _name_blocked(os.path.basename(os.path.realpath(p))):
                return True
    return False


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
    # A folder-scoped Grep can reach every file under its scope, and any
    # glob or type filter can be written (or parsed) to include a .env
    # name. So the rule does not judge filters: a plain file-name glob
    # always passes (it matches only itself, and never a dotfile), and
    # any other folder search passes only when the scope holds no
    # non-template .env file.
    if data.get("tool_name") == "Grep":
        glob = tool_input.get("glob")
        if glob and LITERAL_GLOB.fullmatch(str(glob).strip().lower()):
            return 0
        path = tool_input.get("path")
        if path and Path(str(path)).is_file():
            return 0  # single-file scope; the name checks above passed it
        if scope_has_env(path or data.get("cwd")):
            print("bearings guard: the search scope holds .env files — "
                  "grep a subfolder without them, use a plain file-name "
                  "glob, or Read the files you need", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

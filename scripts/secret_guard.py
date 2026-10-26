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
from pathlib import Path

SAFE = {".env.example", ".env.sample", ".env.dist", ".env.template"}

# A plain file name without a leading dot: it can match only itself.
LITERAL_GLOB = re.compile(r"[a-z0-9][a-z0-9._-]*")
# *.ext, with an optional **/ prefix: it matches names by extension only.
EXT_GLOB = re.compile(r"(\*\*/)?\*\.[a-z0-9]+")

# ripgrep type filters that cannot select a .env file. An unknown type
# fails closed.
SAFE_TYPES = {"py", "js", "ts", "jsx", "tsx", "md", "markdown", "json",
              "yaml", "toml", "html", "css", "sh", "go", "rust", "java",
              "c", "cpp", "h", "rb", "ruby", "php", "swift", "kotlin",
              "sql", "xml", "docker", "make", "cmake", "txt"}


def _name_blocked(name):
    n = name.lower()
    return (n == ".env" or n.startswith(".env.")) and n not in SAFE


def is_blocked(file_path):
    """The given name, and the name the path resolves to."""
    names = {Path(file_path).name, Path(os.path.realpath(file_path)).name}
    return any(_name_blocked(n) for n in names)


def glob_allowed(glob):
    """Only a glob whose meaning needs no interpretation passes: a template
    name, a plain file name without a leading dot, or *.ext with an
    optional **/ prefix. Everything else fails closed — this guard does
    not re-implement ripgrep's glob parser, so it never disagrees with
    it."""
    text = str(glob).strip().lower()
    if text in SAFE:
        return True
    return (LITERAL_GLOB.fullmatch(text) is not None
            or EXT_GLOB.fullmatch(text) is not None)


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
    # A glob that could reach the .env family is a read of it. Only
    # unambiguous glob forms pass.
    glob = tool_input.get("glob")
    if glob and not glob_allowed(glob):
        print(f"bearings guard: the glob {glob!r} is not an allowed form — "
              "use *.py-style, **/*.py, or a plain file name", file=sys.stderr)
        return 2
    # A folder-scoped Grep searches every file in the tree, the .env
    # family among them, so it needs a filter that excludes that family:
    # a safe glob, or a type from the known-safe list.
    if data.get("tool_name") == "Grep":
        rtype = tool_input.get("type")
        if rtype and str(rtype).lower() not in SAFE_TYPES:
            print(f"bearings guard: the type {rtype!r} is not on the safe "
                  "list — use a glob such as *.py", file=sys.stderr)
            return 2
        path = tool_input.get("path")
        dir_scope = not path or Path(str(path)).is_dir()
        if dir_scope and not rtype and not glob:
            print("bearings guard: a folder Grep needs a glob or type that "
                  "excludes .env files (for example glob *.py)", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

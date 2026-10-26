#!/usr/bin/env python3
"""PostToolUse hook for headless bearings runs.

Claude Code calls this after each Write/Edit, with the hook JSON on stdin.
If the edited file is a note in the vault and the linter finds problems,
the hook exits with code 2. Claude Code then feeds stderr back to the model
in the same turn, and the model fixes the note before the run ends.

Files outside the vault, and vault files without a typed frontmatter
(changelog, dashboard, index), pass without checks.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bearings_lint import collect_names, lint_file, resolve_vault  # noqa: E402


def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    file_path = (data.get("tool_input") or {}).get("file_path")
    if not file_path or not str(file_path).endswith(".md"):
        return 0
    vault = resolve_vault(None)
    if vault is None:
        return 0
    path = Path(file_path).resolve()
    try:
        path.relative_to(vault.resolve())
    except ValueError:
        return 0
    if not path.exists():
        return 0
    problems = lint_file(path, vault, collect_names(vault))
    if problems:
        print(f"bearings lint — fix these problems in {path.name}, then save again:",
              file=sys.stderr)
        for msg in problems:
            print(f"- {msg}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

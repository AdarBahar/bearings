#!/usr/bin/env python3
"""PreToolUse hook for headless bearings runs.

A deny glob cannot say "every .env file except the templates". This hook
can: it blocks Read, Edit and Write on the .env family before the tool
runs, and it lets the secret-free template names through. Exit code 2
blocks the call, and Claude gets the reason on stderr.
"""

import json
import sys
from pathlib import Path

SAFE = {".env.example", ".env.sample", ".env.dist", ".env.template"}


def is_blocked(file_path):
    name = Path(file_path).name
    return (name == ".env" or name.startswith(".env.")) and name not in SAFE


def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    file_path = (data.get("tool_input") or {}).get("file_path")
    if file_path and is_blocked(str(file_path)):
        print(f"bearings guard: {Path(file_path).name} can hold secrets — "
              "read .env.example or the code instead", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

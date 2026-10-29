#!/usr/bin/env python3
"""Bearings lint — deterministic checks for the vault notes.

The model writes the notes; this script checks them. No AI inside, stdlib only,
zero tokens. Checks: required frontmatter properties per note type, allowed
values, quoted links in deployment notes, wikilink resolution, leftover
template placeholders and hints, and template parity with the repo.

Usage:
  bearings_lint.py                 lint every typed note in the vault
  bearings_lint.py <note.md> ...   lint these notes only
  bearings_lint.py --vault DIR     use DIR instead of the configured vault

Exit codes: 0 clean, 1 problems found, 2 cannot run.
"""

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bearings_sweep import load_env, parse_frontmatter  # noqa: E402

NOTE_TYPES = {"project", "deployment", "archive", "machine", "group"}

REQUIRED = {
    "project": ["project", "summary", "status", "updated"],
    "deployment": ["project", "env", "status", "host", "updated"],
    "machine": ["machine", "summary", "status", "updated"],
    "group": ["project", "summary", "updated"],
    "archive": ["project", "updated"],
}

# (note type, property) -> allowed values. From the template hints.
VALUES = {
    ("deployment", "env"): {"prod", "staging", "qa", "test", "lan", "preview",
                            "ci", "store", "testing"},
    ("deployment", "status"): {"running", "stopped", "planned", "retired", "unknown"},
    ("project", "deploy_scope"): {"public", "private", "lan", "none"},
    ("machine", "kind"): {"server", "laptop", "desktop", "platform", "external"},
}

# Tokens that only appear in unfilled templates.
PLACEHOLDERS = ["PROJECT_NAME", "GROUP_NAME", "MACHINE", "OWNER/REPO",
                "YYYY-MM-DD", "HEALTH_URL"]

# The templates that /bearings-setup copies into <vault>/_templates/ verbatim.
PARITY_TEMPLATES = ["project.md", "deployment.md", "archive.md", "machine.md", "group.md"]

DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2})?)?")
HINT_RE = re.compile(r"%%.*?%%", re.DOTALL)
MANUAL_RE = re.compile(
    r"<!-- manual:start -->.*?<!-- manual:end -->"
    r"|<!-- manual-extra:start -->.*?<!-- manual-extra:end -->", re.DOTALL)
LINK_RE = re.compile(r"\[\[([^\]\n]+)\]\]")
FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")


def repo_dir():
    home = os.environ.get("BEARINGS_HOME") or load_env().get("BEARINGS_HOME")
    return Path(home).expanduser() if home else Path(__file__).resolve().parent.parent


_HINTS = None


def template_hints():
    """The %% … %% hint texts from the repo templates, whitespace-normalized.
    A note may keep its own %% comments; only these exact hints are leftovers."""
    global _HINTS
    if _HINTS is None:
        _HINTS = set()
        tdir = repo_dir() / "templates"
        if tdir.is_dir():
            for p in tdir.glob("*.md"):
                _HINTS.update(" ".join(h.split()) for h in HINT_RE.findall(p.read_text()))
    return _HINTS


def resolve_vault(arg):
    """--vault flag > BEARINGS_VAULT_DIR in the environment > bearings.env."""
    v = arg or os.environ.get("BEARINGS_VAULT_DIR") or load_env().get("BEARINGS_VAULT_DIR")
    if not v:
        return None
    p = Path(v).expanduser()
    return p if p.is_dir() else None


def in_scope(path, vault):
    """Skip the templates and hidden folders (.obsidian, .trash)."""
    rel = path.relative_to(vault)
    return "_templates" not in rel.parts and not any(part.startswith(".") for part in rel.parts)


def find_obsidian_root(vault):
    """The bearings folder is usually a subfolder of an Obsidian vault, and
    links can point to notes elsewhere in that vault. The nearest ancestor
    with an .obsidian folder is the vault root."""
    for p in [vault.resolve(), *vault.resolve().parents]:
        if (p / ".obsidian").is_dir():
            return p
    return vault


# Notes link without the extension; attachments and Base files link with
# it. Both kinds are valid [[link]] targets in Obsidian.
NOTE_SUFFIXES = {".md", ".base", ".canvas"}
ATTACHMENT_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp",
                       ".avif", ".bmp", ".pdf", ".mp3", ".wav", ".m4a",
                       ".ogg", ".flac", ".webm", ".mp4", ".mov", ".mkv"}


def collect_names(vault):
    """Everything a [[link]] can resolve to, across the whole Obsidian vault:
    a set of exact names (stem, file name, root-relative path) and a list of
    root-relative paths for partial-path links."""
    root = find_obsidian_root(vault)
    exact, paths = set(), []
    for p in root.rglob("*"):
        suffix = p.suffix.lower()
        if suffix not in NOTE_SUFFIXES | ATTACHMENT_SUFFIXES or not p.is_file():
            continue
        rel = p.relative_to(root)
        if any(part.startswith(".") for part in rel.parts) or "_templates" in rel.parts:
            continue
        exact.update({p.name, str(rel)})
        paths.append(str(rel))
        # Only a note resolves without its extension.
        if suffix in NOTE_SUFFIXES:
            exact.update({p.stem, str(rel.with_suffix(""))})
            paths.append(str(rel.with_suffix("")))
    return exact, paths


def link_resolves(target, names):
    exact, paths = names
    if target in exact:
        return True
    # Obsidian accepts a partial path when it identifies the note.
    if "/" in target:
        suffix = "/" + target
        return any(p.endswith(suffix) for p in paths)
    return False


def is_linted(text):
    """True when the note text has a frontmatter with a recognized `type:`."""
    fm = parse_frontmatter(text)
    return fm is not None and isinstance(fm.get("type"), str) and fm["type"] in NOTE_TYPES


def lint_file(path, vault, names):
    """Lint one note. Returns a list of problem messages. A file without a
    recognized `type:` (changelog, dashboard, index) returns no problems."""
    text = path.read_text()
    fm = parse_frontmatter(text)
    if fm is None:
        return []
    ntype = fm.get("type")
    if not isinstance(ntype, str) or ntype not in NOTE_TYPES:
        return []

    problems = []
    for key in REQUIRED[ntype]:
        if key not in fm or fm.get(key) in ("", []):
            problems.append(f"missing required property: {key}")

    upd = fm.get("updated")
    if isinstance(upd, str) and upd and not DATE_RE.fullmatch(upd):
        problems.append(f"updated is not a date: {upd!r}")

    for (vtype, key), allowed_vals in VALUES.items():
        val = fm.get(key)
        if vtype == ntype and isinstance(val, str) and val and val not in allowed_vals:
            problems.append(f"{key}: {val!r} — use one of {sorted(allowed_vals)}")

    if ntype == "deployment":
        fm_block = re.match(r"\A---\n(.*?)\n---", text, re.DOTALL).group(1)
        for key in ("project", "host"):
            if fm.get(key) and not re.search(rf'^{key}:\s*"\[\[[^\]]+\]\]"\s*$', fm_block, re.M):
                problems.append(f'{key} must be a quoted link, for example {key}: "[[name]]"')

    # Content checks skip the user's manual sections and all code.
    body = INLINE_CODE_RE.sub("", FENCE_RE.sub("", MANUAL_RE.sub("", text)))
    for ph in PLACEHOLDERS:
        if re.search(rf"(?<![A-Za-z0-9_]){re.escape(ph)}(?![A-Za-z0-9_])", body):
            problems.append(f"template placeholder left in the note: {ph}")
    for hint in HINT_RE.findall(body):
        if " ".join(hint.split()) in template_hints():
            problems.append("template hint (%% … %%) left in the note")
            break

    for link in LINK_RE.findall(body):
        # The alias separator is | or, inside tables, the escaped \|.
        target = re.split(r"\\\||\|", link)[0].split("#")[0].strip()
        if target and not link_resolves(target, names):
            problems.append(f"link does not resolve: [[{target}]]")

    return problems


def template_parity(vault):
    """The vault copies in _templates/ must equal the repo copies."""
    templates = repo_dir() / "templates"
    vault_dir = vault / "_templates"
    problems = []
    if not templates.is_dir() or not vault_dir.is_dir():
        return problems
    for name in PARITY_TEMPLATES:
        repo_copy, vault_copy = templates / name, vault_dir / name
        if repo_copy.exists() and vault_copy.exists() and repo_copy.read_text() != vault_copy.read_text():
            problems.append((f"_templates/{name}",
                             "differs from the repo template — copy the repo file over it"))
    return problems


def lint_vault(vault, paths=None):
    """Lint the given notes, or the whole vault. Returns 'path: message' strings."""
    names = collect_names(vault)
    out = []
    if paths:
        targets = [Path(p).resolve() for p in paths]
    else:
        targets = sorted(p for p in vault.rglob("*.md") if in_scope(p, vault))
    for p in targets:
        try:
            rel = p.resolve().relative_to(vault.resolve())
        except ValueError:
            out.append(f"{p}: not inside the vault {vault}")
            continue
        out.extend(f"{rel}: {msg}" for msg in lint_file(p, vault, names))
    if not paths:
        out.extend(f"{f}: {msg}" for f, msg in template_parity(vault))
    return out


def main(argv):
    vault_arg, paths = None, []
    args = list(argv)
    while args:
        a = args.pop(0)
        if a == "--vault":
            vault_arg = args.pop(0) if args else None
        else:
            paths.append(a)
    vault = resolve_vault(vault_arg)
    if vault is None:
        print("bearings lint: no vault — pass --vault DIR or run /bearings-setup",
              file=sys.stderr)
        return 2
    problems = lint_vault(vault, paths)
    for p in problems:
        print(p)
    scope = f"{len(paths)} note(s)" if paths else "the vault"
    print(f"bearings lint: {len(problems)} problem(s) in {scope}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

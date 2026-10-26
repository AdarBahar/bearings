#!/usr/bin/env python3
"""Bearings sweep — change detection and scheduled refresh for the project vault.

Reads its configuration from the vault page `_Config.md` (frontmatter), so users
edit settings in Obsidian and the next run picks them up. The only machine-local
state is ~/.bearings/bearings.env (pointer to the vault) and ~/.bearings/state.json.

Stdlib only — no pip installs.
"""

import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

BEARINGS_DIR = Path.home() / ".bearings"
ENV_FILE = BEARINGS_DIR / "bearings.env"
STATE_FILE = BEARINGS_DIR / "state.json"

MARK = {
    "warn": ("<!-- bearings:warnings -->", "<!-- /bearings:warnings -->"),
    "last": ("<!-- bearings:last-sweep -->", "<!-- /bearings:last-sweep -->"),
    "month": ("<!-- bearings:month -->", "<!-- /bearings:month -->"),
    "pending": ("<!-- bearings:pending -->", "<!-- /bearings:pending -->"),
    "history": ("<!-- bearings:history -->", "<!-- /bearings:history -->"),
}

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


# ---------- machine-local pointer + state ----------

def load_env():
    env = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = os.path.expanduser(v.strip())
    return env


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            pass
    return {}


def save_state(state):
    BEARINGS_DIR.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


# ---------- config page (frontmatter subset parser) ----------

def parse_value(val):
    """Parse a frontmatter scalar: plain value, quoted value, or inline flow
    list ('[]', '["*", "tmp-*"]'). Empty value -> [] (list expected to follow)."""
    val = val.split("#")[0].strip()
    if val.startswith("[") and val.endswith("]"):
        inner = val[1:-1].strip()
        if not inner:
            return []
        return [item.strip().strip("\"'") for item in inner.split(",") if item.strip()]
    val = val.strip("\"'")
    return val if val else []


def parse_frontmatter(text):
    """Parse the YAML subset used by _Config.md: scalars, inline flow lists,
    and block lists of scalars."""
    m = re.match(r"\A---\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return None
    data, key = {}, None
    for raw in m.group(1).splitlines():
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        if re.match(r"^\S", raw) and ":" in raw:
            key, _, val = raw.partition(":")
            key = key.strip()
            data[key] = parse_value(val)
        elif raw.lstrip().startswith("- ") and key is not None:
            if not isinstance(data[key], list):
                data[key] = [data[key]] if data[key] else []
            data[key].append(raw.lstrip()[2:].split(" #")[0].strip().strip("\"'"))
    return data


def parse_machines(items, errors):
    """'name | local | dir1, dir2'  or  'name | ssh=alias | dir1, dir2'"""
    machines = []
    for item in items if isinstance(items, list) else []:
        parts = [p.strip() for p in item.split("|")]
        if len(parts) != 3:
            errors.append(f"machine entry not 'name | local-or-ssh=alias | dirs': {item!r}")
            continue
        name, how, dirs = parts
        ssh = None
        if how != "local":
            if not how.startswith("ssh="):
                errors.append(f"machine {name}: expected 'local' or 'ssh=<alias>', got {how!r}")
                continue
            ssh = how[4:]
        machines.append({"name": name, "ssh": ssh,
                         "dirs": [os.path.expanduser(d.strip()) for d in dirs.split(",") if d.strip()]})
    return machines


def load_config(vault):
    """Returns (config, errors). config is None if the page is unusable."""
    page = vault / "_Config.md"
    errors = []
    if not page.exists():
        return None, [f"missing {page}"]
    fm = parse_frontmatter(page.read_text())
    if fm is None:
        return None, ["_Config.md has no frontmatter block"]

    cfg = {}
    cadence = str(fm.get("cadence", "weekly-monday")).lower()
    if cadence not in {"daily", "manual"} and not (
            cadence.startswith("weekly-") and cadence.split("-", 1)[1] in WEEKDAYS):
        errors.append(f"cadence {cadence!r} — use daily, weekly-<weekday>, or manual")
        cadence = "manual"
    cfg["cadence"] = cadence

    for key, allowed, default in (("refresh_mode", {"auto", "report-only"}, "report-only"),
                                  ("create_new", {"auto", "ask", "never"}, "ask")):
        val = str(fm.get(key, default)).lower()
        if val not in allowed:
            errors.append(f"{key} {val!r} — use one of {sorted(allowed)}")
            val = default
        cfg[key] = val

    try:
        cfg["budget_alert_usd"] = float(fm.get("budget_alert_usd", 0) or 0)
    except ValueError:
        errors.append(f"budget_alert_usd {fm.get('budget_alert_usd')!r} is not a number")
        cfg["budget_alert_usd"] = 0

    def as_list(key):
        v = fm.get(key, [])
        return v if isinstance(v, list) else ([v] if v else [])

    cfg["include"] = as_list("include") or ["*"]
    cfg["exclude"] = as_list("exclude")
    cfg["owners"] = as_list("owners")
    cfg["aliases"] = {}
    for item in as_list("aliases"):
        if "=" in item:
            src, dst = item.split("=", 1)
            cfg["aliases"][src.strip()] = dst.strip()
        else:
            errors.append(f"alias entry not 'dir-name = note-name': {item!r}")
    cfg["machines"] = parse_machines(as_list("machines"), errors)
    if not cfg["machines"]:
        errors.append("no valid machines configured")
        return None, errors
    return cfg, errors


# ---------- include / exclude ----------

def pattern_applies(pattern, machine, name):
    """Patterns are 'glob' (all machines) or 'machine:glob' (one machine)."""
    if ":" in pattern:
        pm, _, pg = pattern.partition(":")
        return pm == machine and fnmatch.fnmatch(name, pg)
    return fnmatch.fnmatch(name, pattern)


def allowed(cfg, machine, name, is_git, has_note):
    if any(pattern_applies(p, machine, name) for p in cfg["exclude"]):
        return False
    included = any(pattern_applies(p, machine, name) for p in cfg["include"])
    if not included:
        return False
    # Non-git folders are only tracked when named explicitly (not via bare '*')
    # or when a note for them already exists — random folders shouldn't be documented.
    if not is_git and not has_note:
        return any(pattern_applies(p, machine, name) for p in cfg["include"] if p not in ("*",))
    return True


# ---------- project discovery ----------

def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def local_projects(dirs):
    out = []
    for base in dirs:
        basep = Path(base)
        if not basep.is_dir():
            continue
        for d in sorted(basep.iterdir()):
            if not d.is_dir():
                continue
            is_git = (d / ".git").is_dir()
            if is_git:
                r = run(["git", "-C", str(d), "log", "-1", "--format=%ad", "--date=short"])
                stamp = r.stdout.strip()
            else:
                stamp = newest_mtime_local(d)
            if stamp:
                out.append((d.name, stamp, is_git, str(d)))
    return out


MTIME_PRUNE = ["node_modules", ".git", ".venv", "__pycache__", "data", "uploads"]


def newest_mtime_local(d):
    newest = None
    for root, subdirs, files in os.walk(d):
        subdirs[:] = [s for s in subdirs if s not in MTIME_PRUNE]
        for f in files:
            if f.endswith((".log", ".pid")):
                continue
            try:
                ts = os.path.getmtime(os.path.join(root, f))
                newest = max(newest or ts, ts)
            except OSError:
                pass
    return date.fromtimestamp(newest).isoformat() if newest else None


def remote_projects(machine):
    prune = " ".join(f'-not -path "*/{p}/*"' for p in MTIME_PRUNE)
    dirs = " ".join(f'"{d}"/*/' for d in machine["dirs"])
    script = f'''
for d in {dirs}; do
  [ -d "$d" ] || continue
  n=$(basename "$d")
  if [ -d "$d/.git" ]; then
    echo "$n|$(git -C "$d" log -1 --format=%ad --date=short 2>/dev/null)|git|$d"
  else
    dt=$(find "$d" -type f {prune} -not -name "*.log" -not -name "*.pid" \
         -printf "%TY-%Tm-%Td\\n" 2>/dev/null | sort -r | head -1)
    echo "$n|$dt|dir|$d"
  fi
done'''
    r = run(["ssh", "-o", "ConnectTimeout=8", "-o", "BatchMode=yes", machine["ssh"], script])
    if r.returncode != 0:
        return None
    out = []
    for line in r.stdout.splitlines():
        parts = line.split("|")
        if len(parts) == 4 and parts[1]:
            out.append((parts[0], parts[1], parts[2] == "git", parts[3]))
    return out


# ---------- vault pages ----------

def note_path(vault, name):
    """A project's note: <vault>/<name>/<name>.md, or one level down when it is
    grouped under a parent project (<vault>/<group>/<name>/<name>.md)."""
    note = vault / name / f"{name}.md"
    if note.exists():
        return note
    return next(iter(sorted(vault.glob(f"*/{name}/{name}.md"))), note)


def note_updated(vault, name):
    note = note_path(vault, name)
    if not note.exists():
        return None
    m = re.search(r"^updated:\s*(\S+)", note.read_text(), re.MULTILINE)
    return m.group(1) if m else ""


def is_stale(stamp, updated):
    """stamp is YYYY-MM-DD; updated can also carry a time (YYYY-MM-DDTHH:MM)."""
    return stamp > updated[:10]


def replace_section(text, key, content):
    start, end = MARK[key]
    block = f"{start}\n{content}\n{end}"
    if start in text and end in text:
        return re.sub(re.escape(start) + r".*?" + re.escape(end), block, text, flags=re.DOTALL)
    return text.rstrip() + "\n\n" + block + "\n"


def read_pending_approvals(dash_text):
    """Checked boxes inside the pending block -> [(name, machine)]."""
    start, end = MARK["pending"]
    m = re.search(re.escape(start) + r"(.*?)" + re.escape(end), dash_text, re.DOTALL)
    approved = []
    if m:
        for line in m.group(1).splitlines():
            bm = re.match(r"- \[[xX]\] (\S+) @(\S+)", line.strip())
            if bm:
                approved.append((bm.group(1), bm.group(2)))
    return approved


# ---------- claude runs (refresh / create) ----------

# Deny rules for the headless runs. The skill prompt also says "never read
# .env files", but a prompt is a suggestion; these rules are enforced.
# .env.example stays readable — the skill uses it for the variable names.
# The rules are defense in depth, not a sandbox: a tool that is not listed
# here can still find another path to a file.
# .env suffix families that carry secrets. The template names
# (.env.example, .env.sample, .env.dist, .env.template) stay readable;
# the secret_guard.py hook enforces the full "everything except the
# templates" rule, which a deny glob cannot express.
ENV_SECRET_SUFFIXES = [
    "local", "*.local", "test*", "prod*", "dev*", "stag*", "preprod*",
    "preview*", "qa*", "uat*", "ci*", "live*", "private*", "secret*",
    "backup*", "bak*", "old*", "orig*", "save*", "docker*", "compose*",
    "override*", "enc*",
]

STATIC_DENY = (
    ["Read(**/.env)", "Edit(**/.env)", "Edit(**/.env.*)", "Read(**/.envrc)"]
    + [f"Read(**/.env.{s})" for s in ENV_SECRET_SUFFIXES]
    + [
        "Read(**/*.pem)", "Read(**/*.key)", "Read(**/*.p12)", "Read(**/*.pfx)",
        "Read(**/id_rsa*)", "Read(**/id_ed25519*)", "Read(**/id_ecdsa*)",
        "Read(**/.ssh/**)", "Read(**/.aws/**)", "Read(**/secrets/**)",
        # A write to .git/config or .git/hooks turns the next git call into
        # command execution.
        "Edit(**/.git/**)", "Write(**/.git/**)",
        # Bare git is denied even though it is not in --allowedTools:
        # Claude Code auto-allows read-only commands, and bare git obeys
        # the repo config (fsmonitor, pager). This forces every git call
        # through git_ro.py.
        "Bash(git:*)",
    ]
)

def deny_tools(home, vault):
    """The static denies, plus: the run must not change its own guardrails or
    escalate its own permissions. The repo holds the linter, the hook, the
    git wrapper and the settings; ~/.bearings holds the vault pointer that
    the hook trusts; _Config.md holds refresh_mode and create_new;
    _Dashboard.md holds the approval checkboxes; _templates/ defines the
    note structure that the linter compares against."""
    home, vault = Path(home).resolve(), Path(vault).resolve()
    guard_paths = [f"{home}/**", f"{BEARINGS_DIR.resolve()}/**",
                   f"{vault}/_Config.md", f"{vault}/_Dashboard.md",
                   f"{vault}/_templates/**"]
    guard = [f"{tool}(//{str(p).lstrip('/')})"
             for p in guard_paths for tool in ("Edit", "Write")]
    return ",".join(STATIC_DENY + guard)


# The deny rules above cover the file tools, but they match paths as text.
# This pair enforces the same guard outside the model: a byte snapshot
# before the runs, a compare and restore after them.

def guard_snapshot(vault):
    files = [vault / "_Config.md", vault / "_Dashboard.md"]
    tdir = vault / "_templates"
    if tdir.is_dir():
        files += sorted(p for p in tdir.iterdir() if p.is_file())
    return {str(p.relative_to(vault)): (p.read_bytes(), p.stat().st_mode & 0o7777)
            for p in files if p.exists()}


def _write_guarded(p, data):
    """Replace, never follow: a run could have put a symlink at the path,
    and a plain write would then land at the link target."""
    if p.is_symlink():
        p.unlink()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


def guard_restore(vault, snap):
    """Put every guarded file back as it was. Returns the restored names."""
    changed = []
    tdir = vault / "_templates"
    if tdir.is_symlink():
        tdir.unlink()
        tdir.mkdir()
        changed.append("_templates (symlink replaced)")
    for rel, (data, mode) in snap.items():
        p = vault / rel
        if (p.is_symlink() or not p.exists() or p.read_bytes() != data
                or (p.stat().st_mode & 0o7777) != mode):
            _write_guarded(p, data)
            os.chmod(p, mode)
            changed.append(rel)
    if tdir.is_dir():
        for p in sorted(tdir.iterdir()):
            if p.is_file() and str(p.relative_to(vault)) not in snap:
                p.unlink()
                changed.append(f"{p.relative_to(vault)} (new file removed)")
    return changed


# The **/.git/** deny rules match paths as text, and a case-insensitive
# file system accepts spellings the rules do not. So the .git guard is
# also enforced outside the model, like the vault guard: snapshot before
# the run, compare and restore after it.

# The whole .git tree is guarded, except the content stores that change
# legitimately and are not configuration. This also covers the config,
# hooks and info files of submodules (.git/modules/**) and linked
# worktrees (.git/worktrees/**). Symlinks are part of the guarded state:
# the snapshot records each link and its target, and the restore puts
# them back as links, so a repo that uses them keeps them.
REPO_GUARD_SKIP_DIRS = {"objects", "refs", "logs", "lfs"}
REPO_GUARD_SKIP_FILES = {"index", "packed-refs", "FETCH_HEAD", "ORIG_HEAD",
                         "COMMIT_EDITMSG", "shallow"}


def _repo_guard_walk(base):
    """Yield (path, kind): regular files ('file'), file symlinks ('link')
    and symlinked folders ('dirlink', never descended)."""
    for root, dirs, files in os.walk(base):
        keep = []
        for d in dirs:
            dp = Path(root) / d
            if dp.is_symlink():
                yield dp, "dirlink"
            elif d not in REPO_GUARD_SKIP_DIRS:
                keep.append(d)
        dirs[:] = keep
        for f in files:
            if f in REPO_GUARD_SKIP_FILES:
                continue
            p = Path(root) / f
            yield p, "link" if p.is_symlink() else "file"


def _norm_target(link_path, text):
    """The link's target as an absolute path with . and .. collapsed
    lexically — never resolved through other symlinks."""
    raw = text if os.path.isabs(text) else str(link_path.parent / text)
    return Path(os.path.normpath(raw))


def _snapshot_entry(p, kind, snap, root):
    """Record one guarded entry. A symlink's target is guarded too — a
    run could change the target instead of the link. A link in the chain
    (an alias) becomes its own entry, so a no-op run keeps it and a
    retargeted one is restored. Only targets inside the project are
    followed: following one outside would read, and later prune, folders
    the guard does not own."""
    key = str(p)
    if key in snap:
        return
    if kind == "file":
        # The mode is guarded state too: a hook with its execute bit
        # removed is a disabled hook, even with its contents intact.
        snap[key] = ("file", p.read_bytes(), p.stat().st_mode & 0o7777)
        return
    text = os.readlink(p)
    snap[key] = (kind, text)
    target = _norm_target(p, text)
    if target == root or not _inside(target, root):
        return
    # Validate every component of the target path, not only the last
    # one. The first symlink component becomes its own guarded entry,
    # and the descent stops there: deeper guarding flows through that
    # entry's own recorded target. This also stops the snapshot from
    # reading external files through a middle link that points outside.
    link_component = _first_link_component(target, root)
    if link_component is not None:
        nkind = "dirlink" if link_component.resolve().is_dir() else "link"
        _snapshot_entry(link_component, nkind, snap, root)
        return
    if target.is_file():
        _snapshot_entry(target, "file", snap, root)
    elif target.is_dir():
        for q, k in _repo_guard_walk(target):
            _snapshot_entry(q, k, snap, root)


def _inside(target, root):
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False


def _first_link_component(target, root):
    """The first component of root-relative `target` that is a symlink,
    the final component included — or None when the whole path is real."""
    cur = root
    for part in target.relative_to(root).parts:
        cur = cur / part
        if cur.is_symlink():
            return cur
    return None


def _lexical_root(path):
    """The project root as the guard's paths spell it: absolute and
    normalized, but never resolved — the snapshot keys and the link
    targets are lexical, and containment must compare like with like."""
    return Path(os.path.normpath(os.path.abspath(str(path))))


def repo_guard_snapshot(path):
    base = Path(path) / ".git"
    if base.is_symlink() or not base.is_dir():
        return {}
    root = _lexical_root(path)
    snap = {}
    for p, kind in _repo_guard_walk(base):
        _snapshot_entry(p, kind, snap, root)
    return snap


def _entry_matches(p, entry):
    if entry[0] == "file":
        _, data, mode = entry
        return (p.is_file() and not p.is_symlink()
                and (p.stat().st_mode & 0o7777) == mode
                and p.read_bytes() == data)
    return p.is_symlink() and os.readlink(p) == entry[1]


def _real_inside(p, real_root):
    """The backstop rule: the REAL location must be inside the real
    project root. It holds even when a lexical analysis is wrong."""
    rp = os.path.realpath(str(p))
    return rp == real_root or rp.startswith(real_root + os.sep)


def _remove_entry(p, real_root):
    """Remove a file, link or folder — but never one whose real location
    is outside the project. Returns True when something was removed."""
    p = Path(p)
    if not _real_inside(p.parent, real_root):
        return False
    if p.is_symlink() or p.is_file():
        p.unlink()
        return True
    if p.is_dir():
        if not _real_inside(p, real_root):
            return False
        shutil.rmtree(p)
        return True
    return False


def _restore_entry(p, entry, real_root):
    """Write a snapshot entry back. Returns False, and changes nothing,
    when the write would land outside the real project root."""
    if not _real_inside(Path(p).parent, real_root):
        return False
    _remove_entry(p, real_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    if entry[0] == "file":
        p.write_bytes(entry[1])
        os.chmod(p, entry[2])
    else:
        p.symlink_to(entry[1])
    return True


def _ensure_real_chain(p, snap, root, real_root, changed):
    """Every folder above a snapshot entry was a real folder at snapshot
    time — a symlinked folder became its own snapshot entry and was never
    descended. So a symlink (or a file) in the chain now is a redirect a
    run planted, and it is replaced with a real folder before any prune
    or write resolves through it. A component that is itself a guarded
    link stops the repair: its own entry was restored first, and the
    chain continues from its recorded target. Paths with . or .. are
    never repaired — lexical containment cannot be trusted for them."""
    try:
        rel = Path(p).relative_to(root)
    except ValueError:
        return
    if ".." in rel.parts or "." in rel.parts:
        return
    cur = root
    for part in rel.parts[:-1]:
        cur = cur / part
        if str(cur) in snap:
            return
        if cur.is_symlink() or cur.is_file():
            if not _remove_entry(cur, real_root):
                return
            cur.mkdir()
            changed.append(f"{cur} (replaced with a real folder)")


def repo_guard_restore(path, snap):
    """Put the guarded .git entries back as they were — contents and link
    state — and remove entries a run added. Returns the changed paths."""
    if not snap:
        return []
    changed = []
    base = Path(path) / ".git"
    if base.is_symlink():
        base.unlink()
        base.mkdir()
        changed.append(f"{base} (symlink replaced)")
    root = _lexical_root(path)
    real_root = os.path.realpath(str(path))

    # 1. Put the guarded links back first, shallow paths first. Every
    #    later step then traverses the recorded chain, not a planted one.
    for fp, entry in sorted(snap.items()):
        if entry[0] == "file":
            continue
        p = Path(fp)
        _ensure_real_chain(p, snap, root, real_root, changed)
        if not _entry_matches(p, entry) and _restore_entry(p, entry, real_root):
            changed.append(fp)

    # 2. Repair the remaining parent chains: afterwards no snapshot path,
    #    and no recorded link target, resolves through a planted component.
    for fp, entry in snap.items():
        if entry[0] == "file":
            _ensure_real_chain(Path(fp), snap, root, real_root, changed)
        else:
            target = _norm_target(Path(fp), entry[1])
            if str(target) not in snap and _inside(target, root):
                _ensure_real_chain(target / "x", snap, root, real_root, changed)

    # 3. Remove additions. A linked folder is guarded through its
    #    recorded target — never the link's current target — and only a
    #    target whose whole path is real, lexically inside the project
    #    and really inside it is walked. A target that is, or traverses,
    #    a guarded link is covered by that link's own entry.
    current = {str(p) for p, _ in _repo_guard_walk(base)}
    for fp, entry in snap.items():
        if entry[0] != "dirlink":
            continue
        target = _norm_target(Path(fp), entry[1])
        if (str(target) in snap or not _inside(target, root)
                or not _real_inside(target, real_root)
                or _first_link_component(target, root) is not None
                or not target.is_dir()):
            continue
        current.update(str(q) for q, _ in _repo_guard_walk(target))
    for fp in sorted(current - set(snap)):
        if _remove_entry(Path(fp), real_root):
            changed.append(f"{fp} (new entry removed)")

    # 4. Put the file contents and modes back.
    for fp, entry in snap.items():
        p = Path(fp)
        if entry[0] == "file" and not _entry_matches(p, entry) \
                and _restore_entry(p, entry, real_root):
            changed.append(fp)
    return changed


def bearings_home(env):
    return Path(env.get("BEARINGS_HOME") or Path(__file__).resolve().parent.parent)


def run_claude(env, vault, machine, path, warnings):
    claude = env.get("BEARINGS_CLAUDE_BIN", "claude")
    target = path if machine["ssh"] is None else f"ssh={machine['ssh']}:{path}"
    home = bearings_home(env)
    # No plain git: a prefix rule cannot see a flag like --output=<file>.
    # The wrapper vets the subcommand and every argument.
    tools = ",".join(["Read", "Glob", "Grep", "Write", "Edit", "Bash(ls:*)",
                      f"Bash(python3 {home}/scripts/git_ro.py:*)"])
    if machine["ssh"] and env.get("BEARINGS_ALLOW_SSH") == "1":
        tools += ",Bash(ssh:*)"
    cmd = [claude, "-p", f"/bearings-doc {target}", "--output-format", "json",
           "--add-dir", str(vault), "--permission-mode", "acceptEdits",
           "--allowedTools", tools, "--disallowedTools", deny_tools(home, vault)]
    settings = home / "config" / "headless-settings.json"
    if settings.exists():
        cmd += ["--settings", str(settings)]
    run_env = {**os.environ, "BEARINGS_HOME": str(home),
               "BEARINGS_VAULT_DIR": str(vault)}
    repo_guard = repo_guard_snapshot(path) if machine["ssh"] is None else {}
    r = None
    try:
        r = run(cmd, cwd=path if machine["ssh"] is None else str(Path.home()),
                timeout=900, env=run_env)
    except subprocess.TimeoutExpired:
        warnings.append(f"refresh timed out after 900s: {path}")
    finally:
        # The guard must run even when the claude call times out.
        restored = repo_guard_restore(path, repo_guard)
        if restored:
            warnings.append("a run changed .git guard files; restored: "
                            + ", ".join(restored))
    if r is None:
        return False, 0, 0, 0
    cost = tokens_in = tokens_out = 0
    try:
        j = json.loads(r.stdout)
        cost = float(j.get("total_cost_usd") or 0)
        usage = j.get("usage") or {}
        tokens_in = int(usage.get("input_tokens") or 0) + int(usage.get("cache_read_input_tokens") or 0)
        tokens_out = int(usage.get("output_tokens") or 0)
    except (json.JSONDecodeError, ValueError):
        pass
    return r.returncode == 0, cost, tokens_in, tokens_out


# ---------- main ----------

def main():
    force = "--force" in sys.argv
    report_only = "--report" in sys.argv
    env = load_env()
    if "BEARINGS_VAULT_DIR" not in env:
        print("bearings: not configured — run the /bearings-setup skill first "
              f"(missing {ENV_FILE})", file=sys.stderr)
        return 1
    vault = Path(env["BEARINGS_VAULT_DIR"])
    if not vault.is_dir():
        print(f"bearings: vault not reachable: {vault}", file=sys.stderr)
        return 1

    state = load_state()
    cfg, errors = load_config(vault)
    warnings = [f"config: {e}" for e in errors]
    if cfg is None:
        if state.get("last_good_config"):
            cfg = state["last_good_config"]
            warnings.append("using last-known-good configuration")
        else:
            print("bearings: unusable _Config.md and no previous good config:\n  "
                  + "\n  ".join(errors), file=sys.stderr)
            return 1
    else:
        state["last_good_config"] = cfg

    today = date.today()
    if not force:
        if cfg["cadence"] == "manual":
            return 0
        if cfg["cadence"].startswith("weekly-") and WEEKDAYS[today.weekday()] != cfg["cadence"].split("-", 1)[1]:
            return 0
        if state.get("last_run") == today.isoformat():
            return 0

    dash = vault / "_Dashboard.md"
    dash_text = dash.read_text() if dash.exists() else "# Bearings Dashboard\n"
    approved = read_pending_approvals(dash_text)

    do_refresh = cfg["refresh_mode"] == "auto" and not report_only
    new, stale, ok, unreachable, actions = [], [], 0, [], []
    cost = t_in = t_out = 0.0
    start_time = datetime.now()

    for machine in cfg["machines"]:
        projects = local_projects(machine["dirs"]) if machine["ssh"] is None else remote_projects(machine)
        if projects is None:
            unreachable.append(machine["name"])
            continue
        for raw_name, stamp, is_git, path in projects:
            name = cfg["aliases"].get(raw_name, raw_name)
            updated = note_updated(vault, name)
            if not allowed(cfg, machine["name"], raw_name, is_git, updated is not None):
                continue
            if updated is None:
                new.append((name, machine, path, stamp))
            elif is_stale(stamp, updated):
                stale.append((name, machine, path, stamp, updated))
            else:
                ok += 1

    # de-duplicate: same note name seen on several machines — first machine wins
    seen = set()
    new = [n for n in new if not (n[0] in seen or seen.add(n[0]))]
    seen = set()
    stale = [s for s in stale if not (s[0] in seen or seen.add(s[0]))]

    guard = guard_snapshot(vault)
    pending_out = []
    attempted = False
    try:
        for name, machine, path, stamp, updated in stale if do_refresh else []:
            attempted = True
            good, c, ti, to = run_claude(env, vault, machine, path, warnings)
            cost += c; t_in += ti; t_out += to
            actions.append(f"refreshed {name}" if good else f"refresh FAILED {name}")

        for name, machine, path, stamp in new:
            approve = cfg["create_new"] == "auto" or (name, machine["name"]) in approved
            if approve and not report_only:
                attempted = True
                good, c, ti, to = run_claude(env, vault, machine, path, warnings)
                cost += c; t_in += ti; t_out += to
                actions.append(f"created {name}" if good else f"create FAILED {name}")
            elif cfg["create_new"] == "ask":
                pending_out.append(f"- [ ] {name} @{machine['name']} (changed {stamp})")
    finally:
        # The vault guard must run even when the first refresh raises, so
        # it keys on attempted runs, not on completed actions.
        if attempted:
            restored = guard_restore(vault, guard)
            if restored:
                warnings.append("a run changed guarded files; restored: "
                                + ", ".join(restored))

    # ---- lint (deterministic, zero tokens) ----
    lint_problems = []
    try:
        import bearings_lint
        os.environ.setdefault("BEARINGS_HOME", str(bearings_home(env)))
        lint_problems = bearings_lint.lint_vault(vault)
    except Exception as e:  # the lint must never break the sweep
        warnings.append(f"lint did not run: {e}")
    if lint_problems:
        warnings.extend(f"lint: {p}" for p in lint_problems[:8])
        if len(lint_problems) > 8:
            warnings.append(f"lint: {len(lint_problems) - 8} more — "
                            "run scripts/bearings_lint.py")

    # ---- dashboard ----
    month_key = today.strftime("%Y-%m")
    months = state.setdefault("months", {})
    mo = months.setdefault(month_key, {"runs": 0, "cost": 0.0, "t_in": 0, "t_out": 0})
    mo["runs"] += 1; mo["cost"] += cost; mo["t_in"] += int(t_in); mo["t_out"] += int(t_out)

    warn_block = "\n".join(f"> [!warning] {w}" for w in warnings) if warnings else "_none_"
    dur = int((datetime.now() - start_time).total_seconds())
    last = (f"**{today} {datetime.now().strftime('%H:%M')}** — "
            f"{len(new)} new · {len(stale)} stale · {ok} up-to-date"
            + (f" · unreachable: {', '.join(unreachable)}" if unreachable else "")
            + (f"\nActions: {'; '.join(actions)}" if actions else "\nActions: none (report-only)" if not do_refresh else "\nActions: none")
            + f"\nTokens: {int(t_in):,} in / {int(t_out):,} out · Cost: ${cost:.2f} · {dur}s")
    budget = cfg["budget_alert_usd"]
    month_line = (f"**{month_key}**: {mo['runs']} runs · ${mo['cost']:.2f}"
                  + (f" / budget ${budget:.0f} {'⚠️ OVER' if budget and mo['cost'] > budget else '✓'}" if budget else "")
                  + f" · {mo['t_in']:,} in / {mo['t_out']:,} out")
    pending_block = "\n".join(pending_out) if pending_out else "_none — new projects appear here for approval when `create_new: ask`_"

    dash_text = replace_section(dash_text, "warn", warn_block)
    dash_text = replace_section(dash_text, "last", last)
    dash_text = replace_section(dash_text, "month", month_line)
    dash_text = replace_section(dash_text, "pending", pending_block)
    done_count = sum(1 for a in actions if "FAILED" not in a)
    hist_row = f"| {today} | {len(new)} | {len(stale)} | {done_count} | ${cost:.2f} | {ok} ok |"
    header = "| Date | New | Stale | Actions | Cost | Notes |\n|---|---|---|---|---|---|"
    start_m, end_m = MARK["history"]
    sep_re = re.compile(re.escape(start_m) + r".*?\|-+\|[-|]*\n", re.DOTALL)
    if sep_re.search(dash_text):
        dash_text = sep_re.sub(lambda m: m.group(0) + hist_row + "\n", dash_text, count=1)
    else:
        dash_text = replace_section(dash_text, "history", header + "\n" + hist_row)
    dash.write_text(dash_text)

    state["last_run"] = today.isoformat()
    save_state(state)

    print(f"bearings sweep: {len(new)} new, {len(stale)} stale, {ok} up-to-date, "
          f"{len(lint_problems)} lint problem(s), ${cost:.2f} spent"
          + (f", unreachable: {','.join(unreachable)}" if unreachable else ""))
    for p in lint_problems:
        print(f"  LINT  {p}")
    for name, machine, path, stamp in new:
        print(f"  NEW   {name} @{machine['name']} (changed {stamp})")
    for name, machine, path, stamp, updated in stale:
        print(f"  STALE {name} @{machine['name']} (note {updated}, changed {stamp})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

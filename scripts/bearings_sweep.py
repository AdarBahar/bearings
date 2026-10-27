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
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

BEARINGS_DIR = Path.home() / ".bearings"
ENV_FILE = BEARINGS_DIR / "bearings.env"
STATE_FILE = BEARINGS_DIR / "state.json"

MARK = {
    "warn": ("<!-- bearings:warnings -->", "<!-- /bearings:warnings -->"),
    "last": ("<!-- bearings:last-sweep -->", "<!-- /bearings:last-sweep -->"),
    "month": ("<!-- bearings:month -->", "<!-- /bearings:month -->"),
    "costs": ("<!-- bearings:costs -->", "<!-- /bearings:costs -->"),
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

    model = fm.get("model", "")
    cfg["model"] = model.strip() if isinstance(model, str) else ""

    for key in ("budget_alert_usd", "budget_stop_usd"):
        try:
            cfg[key] = float(fm.get(key, 0) or 0)
        except ValueError:
            errors.append(f"{key} {fm.get(key)!r} is not a number")
            cfg[key] = 0

    notify = str(fm.get("notify", "off") or "off").lower()
    if notify not in {"off", "on-action", "always"}:
        errors.append(f"notify {notify!r} — use off, on-action, or always")
        notify = "off"
    cfg["notify"] = notify
    email = fm.get("notify_email", "")
    cfg["notify_email"] = email.strip() if isinstance(email, str) else ""

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


# ---------- cost counters ----------

RUNS_KEEP_DAYS = 95   # covers day, week, this month and the previous month
RUNS_CAP = 2000


def record_runs(state, today, kind, name, models):
    """One record per model per claude call, in state.json. The records
    of one call share one id, so the run counter counts calls, not
    (day, kind, project) triples — two sweeps can touch the same project
    on one day."""
    runs = state.setdefault("runs", [])
    call_id = uuid.uuid4().hex[:12]
    for m, u in models.items():
        runs.append({"id": call_id, "d": today.isoformat(), "kind": kind,
                     "name": name, "model": m,
                     "cost": round(float(u["cost"]), 6),
                     "in": int(u["in"]), "cache": int(u.get("cache", 0)),
                     "out": int(u["out"])})


def prune_runs(state, today):
    cutoff = (today - timedelta(days=RUNS_KEEP_DAYS)).isoformat()
    runs = [r for r in state.get("runs", []) if r.get("d", "") >= cutoff]
    state["runs"] = runs[-RUNS_CAP:]


def _agg(records):
    # Older records have no id; they fall back to the (day, kind, name)
    # triple. Older records also have no "cache" field (cache reads were
    # folded into "in"); they count as zero cache reads.
    runs = len({r.get("id") or (r["d"], r["kind"], r["name"])
                for r in records})
    return (runs, sum(r["cost"] for r in records),
            sum(r["in"] for r in records),
            sum(r.get("cache", 0) for r in records),
            sum(r["out"] for r in records))


def cost_block(state, today):
    """The Costs section of the dashboard: today / week / month counters,
    a per-day table for the last week, a per-model table for the last 30
    days, and the monthly history."""
    runs = state.get("runs", [])
    days7 = [(today - timedelta(days=i)).isoformat() for i in range(7)]
    t = _agg([r for r in runs if r["d"] == days7[0]])
    w = _agg([r for r in runs if r["d"] in set(days7)])
    m = _agg([r for r in runs if r["d"].startswith(today.strftime("%Y-%m"))])
    out = [f"**Today:** {t[0]} runs · ${t[1]:.2f} · "
           f"**Last 7 days:** {w[0]} runs · ${w[1]:.2f} · "
           f"**This month:** {m[0]} runs · ${m[1]:.2f}", ""]

    day_rows = []
    for d in days7:
        n, c, ti, tc, to = _agg([r for r in runs if r["d"] == d])
        if n:
            day_rows.append(f"| {d} | {n} | ${c:.2f} | {ti:,} | {tc:,} | {to:,} |")
    if day_rows:
        out += ["| Day | Runs | Cost | Fresh in | Cache in | Out |",
                "|---|---|---|---|---|---|"] + day_rows + [""]

    cutoff30 = (today - timedelta(days=30)).isoformat()
    by_model = {}
    for r in runs:
        if r["d"] >= cutoff30:
            by_model.setdefault(r["model"], []).append(r)
    if by_model:
        out += ["**Per model, last 30 days** (all runs go through the "
                "Claude CLI; the model is the vendor breakdown; a cache "
                "read costs about a tenth of a fresh input token):", "",
                "| Model | Runs | Cost | Fresh in | Cache in | Out |",
                "|---|---|---|---|---|---|"]
        for name, rs in sorted(by_model.items(),
                               key=lambda kv: -sum(r["cost"] for r in kv[1])):
            n, c, ti, tc, to = _agg(rs)
            out.append(f"| {name} | {n} | ${c:.2f} | {ti:,} | {tc:,} | {to:,} |")
        out.append("")

    months = state.get("months", {})
    if months:
        out += ["**Monthly history:**", "",
                "| Month | Sweeps | Cost | Tokens in | Tokens out |",
                "|---|---|---|---|---|"]
        for key in sorted(months, reverse=True)[:12]:
            mo = months[key]
            out.append(f"| {key} | {mo['runs']} | ${mo['cost']:.2f} "
                       f"| {mo['t_in']:,} | {mo['t_out']:,} |")
    return "\n".join(out).rstrip()


# ---------- email notification ----------

def smtp_settings(env):
    """SMTP settings from bearings.env, or None when incomplete. The
    credentials stay machine-local; the vault never sees them."""
    host = env.get("BEARINGS_SMTP_HOST", "")
    user = env.get("BEARINGS_SMTP_USER", "")
    password = env.get("BEARINGS_SMTP_PASS", "")
    if not (host and user and password):
        return None
    try:
        port = int(env.get("BEARINGS_SMTP_PORT", "") or 587)
    except ValueError:
        port = 587
    return {"host": host, "port": port, "user": user, "pass": password,
            "from": env.get("BEARINGS_SMTP_FROM", "") or user}


def should_notify(notify, actions, budget_stopped):
    """'always' sends after every executed sweep. 'on-action' sends when
    the sweep spent usage or hit the budget stop."""
    if notify == "always":
        return True
    if notify == "on-action":
        return bool(actions) or budget_stopped
    return False


def build_notification(today, last, month_line, warnings, budget_stopped,
                       budget_stop, actions):
    """(subject, body) for the sweep email. Plain text."""
    if budget_stopped:
        subject = f"bearings: budget stop reached — sweep ran no refreshes ({today})"
    elif any("FAILED" in a for a in actions):
        subject = f"bearings sweep {today}: {len(actions)} action(s), some FAILED"
    else:
        subject = f"bearings sweep {today}: {len(actions)} action(s)"
    body = ["Bearings sweep report", "", last, "", month_line]
    if budget_stopped:
        body += ["",
                 f"The month cost reached budget_stop_usd (${budget_stop:.2f}).",
                 "The sweep skipped all refreshes and creations.",
                 "What to do:",
                 "  - Raise or remove budget_stop_usd in _Config.md to let runs continue.",
                 "  - Or do nothing; runs continue in the next month.",
                 "Approved new projects stay checked in _Dashboard.md and run later."]
    if warnings:
        body += ["", "Warnings:"] + [f"  - {w}" for w in warnings]
    body += ["", "Details: _Dashboard.md in the vault."]
    return subject, "\n".join(body)


def send_email(settings, to, subject, body):
    """Send one plain-text email. Raises on failure; the caller catches."""
    import smtplib
    from email.message import EmailMessage
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings["from"]
    msg["To"] = to
    msg.set_content(body)
    if settings["port"] == 465:
        with smtplib.SMTP_SSL(settings["host"], settings["port"], timeout=30) as s:
            s.login(settings["user"], settings["pass"])
            s.send_message(msg)
    else:
        with smtplib.SMTP(settings["host"], settings["port"], timeout=30) as s:
            s.starttls()
            s.login(settings["user"], settings["pass"])
            s.send_message(msg)


def notify_sweep(env, cfg, warnings, today, last, month_line,
                 budget_stopped, actions):
    """Send the sweep email when the notify settings ask for one. A
    notification failure becomes a warning; it never breaks the sweep."""
    notify = cfg.get("notify", "off")
    to = cfg.get("notify_email", "")
    if notify == "off" or not should_notify(notify, actions, budget_stopped):
        return
    if not to:
        warnings.append("notify is on but notify_email is empty in _Config.md")
        return
    settings = smtp_settings(env)
    if settings is None:
        warnings.append("notify is on but SMTP settings are missing in "
                        "bearings.env (BEARINGS_SMTP_HOST, BEARINGS_SMTP_USER, "
                        "BEARINGS_SMTP_PASS)")
        return
    subject, body = build_notification(today, last, month_line, warnings,
                                       budget_stopped,
                                       cfg.get("budget_stop_usd", 0), actions)
    try:
        send_email(settings, to, subject, body)
    except Exception as e:
        warnings.append(f"notification email failed: {e}")


def bearings_home(env):
    return Path(env.get("BEARINGS_HOME") or Path(__file__).resolve().parent.parent)


def parse_claude_json(stdout):
    """(cost, tokens in, tokens out, result text, per-model usage) from a
    claude -p JSON reply; zeros, an empty string and an empty dict when
    the output is not JSON. Per-model usage comes from the CLI's own
    modelUsage report, so subagent models count correctly:
    {model: {"cost": float, "in": int, "cache": int, "out": int}}.
    "in" counts fresh input tokens only; "cache" counts prompt-cache
    reads, which cost about a tenth of a fresh input token."""
    try:
        j = json.loads(stdout)
    except (json.JSONDecodeError, ValueError):
        return 0, 0, 0, "", {}
    try:
        cost = float(j.get("total_cost_usd") or 0)
        usage = j.get("usage") or {}
        t_in = int(usage.get("input_tokens") or 0) + int(usage.get("cache_read_input_tokens") or 0)
        t_out = int(usage.get("output_tokens") or 0)
    except (ValueError, TypeError, AttributeError):
        return 0, 0, 0, "", {}
    models = {}
    for name, u in (j.get("modelUsage") or {}).items():
        if not isinstance(u, dict):
            continue
        models[str(name)] = {
            "cost": float(u.get("costUSD") or u.get("cost_usd") or 0),
            "in": int(u.get("inputTokens") or 0),
            "cache": int(u.get("cacheReadInputTokens") or 0),
            "out": int(u.get("outputTokens") or 0),
        }
    return cost, t_in, t_out, str(j.get("result") or ""), models


def skills_canary(env, model=""):
    """One cheap headless run that invokes /bearings-doc with --canary.
    The loaded skill answers with a fixed token; in bare mode (a possible
    future default for -p) the slash command resolves to nothing and the
    token never appears. The check must invoke the skill, not ask about
    it: disable-model-invocation hides the skill from the model's own
    view, while a -p invocation still works. Returns (ok, cost,
    tokens in, tokens out)."""
    claude = env.get("BEARINGS_CLAUDE_BIN", "claude")
    cmd = [claude, "-p", "/bearings-doc --canary",
           "--output-format", "json", "--allowedTools", ""]
    if model:
        cmd += ["--model", model]
    try:
        r = run(cmd, timeout=300)
    except subprocess.TimeoutExpired:
        return False, 0, 0, 0, {}
    cost, t_in, t_out, result, models = parse_claude_json(r.stdout)
    if not models and (cost or t_in or t_out):
        models = {model or "default": {"cost": cost, "in": t_in, "out": t_out}}
    return (r.returncode == 0 and "BEARINGS-DOC-LOADED" in result.upper(),
            cost, t_in, t_out, models)


def run_claude(env, vault, machine, path, warnings, model=""):
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
    if model:
        cmd += ["--model", model]
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
        return False, 0, 0, 0, {}
    cost, tokens_in, tokens_out, _, models = parse_claude_json(r.stdout)
    if not models and (cost or tokens_in or tokens_out):
        models = {model or "default": {"cost": cost, "in": tokens_in,
                                       "out": tokens_out}}
    return r.returncode == 0, cost, tokens_in, tokens_out, models


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

    model = cfg.get("model", "")

    # Before any run starts: one cheap prompt proves that headless runs
    # load the bearings-doc skill. Bare mode does not load skills, and a
    # sweep that refreshes nothing must say so, not stay silent.
    creates = [n for n in new
               if not report_only
               and (cfg["create_new"] == "auto" or (n[0], n[1]["name"]) in approved)]

    # Budget stop: a hard cap, unlike budget_alert_usd, which only warns.
    # When the month's spend reaches it, the sweep skips every paid run.
    stop = float(cfg.get("budget_stop_usd", 0) or 0)
    month_key = today.strftime("%Y-%m")
    spent_before = float(state.get("months", {}).get(month_key, {}).get("cost", 0.0))
    budget_stopped = False

    def over_stop():
        return bool(stop) and spent_before + cost >= stop

    if ((do_refresh and stale) or creates) and over_stop():
        budget_stopped = True
        warnings.append(f"budget stop — this month's cost (${spent_before:.2f}) "
                        f"reached budget_stop_usd (${stop:.2f}); refreshes and "
                        "creations skipped this sweep")

    canary_ok = True
    if not budget_stopped and ((do_refresh and stale) or creates):
        canary_ok, c, ti, to, models = skills_canary(env, model)
        cost += c; t_in += ti; t_out += to
        record_runs(state, today, "canary", "-", models)
        if not canary_ok:
            warnings.append("canary FAILED — headless runs do not load the "
                            "bearings-doc skill (bare mode?); refreshes and "
                            "creations skipped this sweep")

    guard = guard_snapshot(vault)
    pending_out = []
    attempted = False
    try:
        for name, machine, path, stamp, updated in (
                stale if do_refresh and canary_ok and not budget_stopped else []):
            if over_stop():
                budget_stopped = True
                warnings.append(f"budget stop — month cost reached "
                                f"budget_stop_usd (${stop:.2f}) mid-sweep; "
                                "remaining runs skipped")
                break
            attempted = True
            good, c, ti, to, models = run_claude(env, vault, machine, path, warnings, model)
            cost += c; t_in += ti; t_out += to
            record_runs(state, today, "refresh", name, models)
            actions.append(f"refreshed {name}" if good else f"refresh FAILED {name}")

        for name, machine, path, stamp in new:
            approve = cfg["create_new"] == "auto" or (name, machine["name"]) in approved
            if (approve and not report_only and canary_ok
                    and not budget_stopped and over_stop()):
                budget_stopped = True
                warnings.append(f"budget stop — month cost reached "
                                f"budget_stop_usd (${stop:.2f}) mid-sweep; "
                                "remaining runs skipped")
            if approve and not report_only and canary_ok and not budget_stopped:
                attempted = True
                good, c, ti, to, models = run_claude(env, vault, machine, path, warnings, model)
                cost += c; t_in += ti; t_out += to
                record_runs(state, today, "create", name, models)
                actions.append(f"created {name}" if good else f"create FAILED {name}")
            elif approve and not report_only:
                # The canary failed or the budget stop hit: keep the
                # approval, as a checked box.
                pending_out.append(f"- [x] {name} @{machine['name']} (changed {stamp})")
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
    months = state.setdefault("months", {})
    mo = months.setdefault(month_key, {"runs": 0, "cost": 0.0, "t_in": 0, "t_out": 0})
    mo["runs"] += 1; mo["cost"] += cost; mo["t_in"] += int(t_in); mo["t_out"] += int(t_out)

    dur = int((datetime.now() - start_time).total_seconds())
    last = (f"**{today} {datetime.now().strftime('%H:%M')}** — "
            f"{len(new)} new · {len(stale)} stale · {ok} up-to-date"
            + (f" · unreachable: {', '.join(unreachable)}" if unreachable else "")
            + (f"\nActions: {'; '.join(actions)}" if actions else "\nActions: none (report-only)" if not do_refresh else "\nActions: none")
            + f"\nTokens: {int(t_in):,} in / {int(t_out):,} out · Cost: ${cost:.2f} · {dur}s")
    budget = cfg["budget_alert_usd"]
    month_line = (f"**{month_key}**: {mo['runs']} runs · ${mo['cost']:.2f}"
                  + (f" / budget ${budget:.0f} {'⚠️ OVER' if budget and mo['cost'] > budget else '✓'}" if budget else "")
                  + (f" · stop at ${stop:.0f}" if stop else "")
                  + f" · {mo['t_in']:,} in / {mo['t_out']:,} out")
    pending_block = "\n".join(pending_out) if pending_out else "_none — new projects appear here for approval when `create_new: ask`_"

    # The email goes out before the warnings block renders, so a notify
    # failure still shows on the dashboard.
    notify_sweep(env, cfg, warnings, today, last, month_line,
                 budget_stopped, actions)
    warn_block = "\n".join(f"> [!warning] {w}" for w in warnings) if warnings else "_none_"

    prune_runs(state, today)
    dash_text = replace_section(dash_text, "warn", warn_block)
    dash_text = replace_section(dash_text, "last", last)
    dash_text = replace_section(dash_text, "month", month_line)
    dash_text = replace_section(dash_text, "costs", cost_block(state, today))
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

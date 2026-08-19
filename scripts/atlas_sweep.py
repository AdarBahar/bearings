#!/usr/bin/env python3
"""Atlas sweep — change detection and scheduled refresh for the project vault.

Reads its configuration from the vault page `_Config.md` (frontmatter), so users
edit settings in Obsidian and the next run picks them up. The only machine-local
state is ~/.atlas/atlas.env (pointer to the vault) and ~/.atlas/state.json.

Stdlib only — no pip installs.
"""

import fnmatch
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

ATLAS_DIR = Path.home() / ".atlas"
ENV_FILE = ATLAS_DIR / "atlas.env"
STATE_FILE = ATLAS_DIR / "state.json"

MARK = {
    "warn": ("<!-- atlas:warnings -->", "<!-- /atlas:warnings -->"),
    "last": ("<!-- atlas:last-sweep -->", "<!-- /atlas:last-sweep -->"),
    "month": ("<!-- atlas:month -->", "<!-- /atlas:month -->"),
    "pending": ("<!-- atlas:pending -->", "<!-- /atlas:pending -->"),
    "history": ("<!-- atlas:history -->", "<!-- /atlas:history -->"),
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
    ATLAS_DIR.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


# ---------- config page (frontmatter subset parser) ----------

def parse_frontmatter(text):
    """Parse the YAML subset used by _Config.md: scalars and lists of scalars."""
    m = re.match(r"\A---\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return None
    data, key = {}, None
    for raw in m.group(1).splitlines():
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        if re.match(r"^\S", raw) and ":" in raw:
            key, _, val = raw.partition(":")
            key, val = key.strip(), val.split("#")[0].strip().strip("\"'")
            data[key] = val if val else []
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

def note_updated(vault, name):
    note = vault / name / f"{name}.md"
    if not note.exists():
        return None
    m = re.search(r"^updated:\s*(\S+)", note.read_text(), re.MULTILINE)
    return m.group(1) if m else ""


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

def run_claude(env, vault, machine, path):
    claude = env.get("ATLAS_CLAUDE_BIN", "claude")
    target = path if machine["ssh"] is None else f"ssh={machine['ssh']}:{path}"
    tools = "Read,Glob,Grep,Write,Edit,Bash(git:*),Bash(ls:*)"
    if machine["ssh"] and env.get("ATLAS_ALLOW_SSH") == "1":
        tools += ",Bash(ssh:*)"
    r = run([claude, "-p", f"/atlas-doc {target}", "--output-format", "json",
             "--add-dir", str(vault), "--permission-mode", "acceptEdits",
             "--allowedTools", tools],
            cwd=path if machine["ssh"] is None else str(Path.home()), timeout=900)
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
    if "ATLAS_VAULT_DIR" not in env:
        print("atlas: not configured — run the /atlas-setup skill first "
              f"(missing {ENV_FILE})", file=sys.stderr)
        return 1
    vault = Path(env["ATLAS_VAULT_DIR"])
    if not vault.is_dir():
        print(f"atlas: vault not reachable: {vault}", file=sys.stderr)
        return 1

    state = load_state()
    cfg, errors = load_config(vault)
    warnings = [f"config: {e}" for e in errors]
    if cfg is None:
        if state.get("last_good_config"):
            cfg = state["last_good_config"]
            warnings.append("using last-known-good configuration")
        else:
            print("atlas: unusable _Config.md and no previous good config:\n  "
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
    dash_text = dash.read_text() if dash.exists() else "# Atlas Dashboard\n"
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
            elif stamp > updated:
                stale.append((name, machine, path, stamp, updated))
            else:
                ok += 1

    # de-duplicate: same note name seen on several machines — first machine wins
    seen = set()
    new = [n for n in new if not (n[0] in seen or seen.add(n[0]))]
    seen = set()
    stale = [s for s in stale if not (s[0] in seen or seen.add(s[0]))]

    for name, machine, path, stamp, updated in stale if do_refresh else []:
        good, c, ti, to = run_claude(env, vault, machine, path)
        cost += c; t_in += ti; t_out += to
        actions.append(f"refreshed {name}" if good else f"refresh FAILED {name}")

    pending_out = []
    for name, machine, path, stamp in new:
        approve = cfg["create_new"] == "auto" or (name, machine["name"]) in approved
        if approve and not report_only:
            good, c, ti, to = run_claude(env, vault, machine, path)
            cost += c; t_in += ti; t_out += to
            actions.append(f"created {name}" if good else f"create FAILED {name}")
        elif cfg["create_new"] == "ask":
            pending_out.append(f"- [ ] {name} @{machine['name']} (changed {stamp})")

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

    print(f"atlas sweep: {len(new)} new, {len(stale)} stale, {ok} up-to-date, "
          f"${cost:.2f} spent"
          + (f", unreachable: {','.join(unreachable)}" if unreachable else ""))
    for name, machine, path, stamp in new:
        print(f"  NEW   {name} @{machine['name']} (changed {stamp})")
    for name, machine, path, stamp, updated in stale:
        print(f"  STALE {name} @{machine['name']} (note {updated}, changed {stamp})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

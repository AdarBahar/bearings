---
name: atlas-ops
description: Answer plain-English questions about the user's projects, machines, services, and deployments — using the Atlas vault as the knowledge base, verified against live state (ssh/docker/systemd) when the question concerns what is running now. Can perform ops actions (restart, logs) when explicitly asked.
---

# atlas-ops: project & infrastructure Q&A

The argument (or the user's next message) is the question.

## Knowledge base

1. `~/.atlas/atlas.env` → `ATLAS_VAULT_DIR` is the vault folder (if missing: point the user to `/atlas-setup`).
2. `_Index.md` — one row per project. Open only the relevant `<name>/<name>.md` (orientation) and `<name>/changelog.md` (history).
3. Machine notes (`type: machine` frontmatter) — per-machine inventories; treat their "running" tables as snapshots, not truth.
4. `_Config.md` — the machines list tells you how to reach each machine (`local` or `ssh=<alias>`).

## Static vs live — the core rule

- **Procedural/factual** ("how do I restart X", "where is Y's .env", "what's Z's prod URL"): answer from the notes; quote exact commands/paths.
- **Current-state** (*currently, running, status, up, down, healthy, logs, disk, ports, "is X…"*): verify live and answer from command output — `docker ps`, `systemctl` / `systemctl --user`, `launchctl print`, `ss -tlnp` / `lsof -i`, `pm2 ls`, run over `ssh <alias>` for remote machines. If live state contradicts a note, say so and offer to update the note. If a machine is unreachable, fall back to the note's snapshot, clearly labeled "as of <updated>".

## Actions

Perform only when explicitly asked ("restart X" acts; "how do I restart X" answers). Use the exact commands from the project's note. Dev/local targets: do it and report. Staging/production targets: state the exact command and get confirmation first.

## Answer style

Lead with the direct answer (list, command, status), then one line of provenance (which note / which command). Compact tables for multi-project questions. Don't dump whole notes.

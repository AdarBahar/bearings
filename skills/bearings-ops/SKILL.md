---
name: bearings-ops
description: Answer plain-English questions about the user's projects, machines, services, and deployments — using the Bearings vault as the knowledge base, verified against live state (ssh/docker/systemd) when the question concerns what is running now. Can perform ops actions (restart, logs) when explicitly asked.
---

# bearings-ops: project & infrastructure Q&A

The argument (or the user's next message) is the question.

## Knowledge base

1. `~/.bearings/bearings.env` → `BEARINGS_VAULT_DIR` is the vault folder (if missing: point the user to `/bearings-setup`).
2. `_Index.md` — one row per project. Open only the relevant note (current state). Follow the index link: a note is at `<name>/<name>.md`, or `<group>/<name>/<name>.md` when grouped under a parent project, whose `<group>/<group>.md` describes the whole system. Next to it: `changelog.md` (code history) and `archive.md` (old facts and ops events).
3. Deployment notes (`<name>@<env>.md`, `type: deployment`) — one running instance each. The frontmatter holds the facts: `host`, `ssh`, `urls`, `health_url`, `app_path`, `config_path`, `run_as`, `runtime`, `process`, `port`, `database`, `deploy_method`. `verified` tells the date of the last live check. For a question across projects ("what runs on server X", "which prod uses PostgreSQL"), grep the frontmatter of `*@*.md` files. Ignore `status: retired` unless asked.
4. Machine notes (`type: machine` frontmatter) — per-machine facts. The deployments on a machine are the deployment notes whose `host` links to it. A table "Without a project note" lists services that have no project note; treat it as a snapshot, not truth. Notes with `kind: platform` (`Stores`, `GitHub`) or `external` (`Testing`) are hosts that are not your machines.
5. `_Config.md` — the machines list tells you how to reach each machine (`local` or `ssh=<alias>`).

## Static vs live — the core rule

- **Procedural/factual** ("how do I restart X", "where is Y's .env", "what's Z's prod URL"): answer from the notes; quote exact commands/paths.
- **Current-state** (*currently, running, status, up, down, healthy, logs, disk, ports, "is X…"*): verify live and answer from command output — `docker ps`, `systemctl` / `systemctl --user`, `launchctl print`, `ss -tlnp` / `lsof -i`, `pm2 ls`, run over `ssh <alias>` for remote machines. If live state contradicts a note, say so and offer to update the note. If a machine is unreachable, fall back to the note's snapshot, clearly labeled "as of <updated>".

## Actions

Perform only when explicitly asked ("restart X" acts; "how do I restart X" answers). Use the exact commands from the project's note. Dev/local targets: do it and report. Staging/production targets: state the exact command and get confirmation first.

## Answer style

Lead with the direct answer (list, command, status), then one line of provenance (which note / which command). Compact tables for multi-project questions. Don't dump whole notes.

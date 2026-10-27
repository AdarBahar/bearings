---
cadence: weekly-monday
refresh_mode: report-only
create_new: ask
model:
budget_alert_usd: 0
budget_stop_usd: 0
notify: off
notify_email:
machines:
  - "mac | local | ~/Code"
include:
  - "*"
exclude: []
owners:
  - your-github-username
aliases: []
---

# Bearings Configuration

**Edit the values above — the next sweep reads this page fresh, so changes apply automatically.** No restart or reinstall needed (including cadence changes: the OS timer ticks daily and this page decides whether it acts).

| Setting | Values | Meaning |
|---|---|---|
| `cadence` | `daily` / `weekly-<weekday>` / `manual` | When the scheduled sweep actually runs. `manual` = only when you run it yourself. |
| `refresh_mode` | `report-only` / `auto` | `auto` regenerates stale notes headlessly — **this spends Claude usage**. `report-only` just lists them in the dashboard. |
| `create_new` | `ask` / `auto` / `never` | What happens when a new repo is discovered. `ask` puts a checkbox in [[_Dashboard]] — tick it to approve documentation on the next run. |
| `model` | model name or empty | The model for headless refresh runs, e.g. `claude-haiku-5-5`. A note refresh is mechanical work, so a smaller model cuts the cost. Empty = the CLI default. A wrong name makes runs fail; the dashboard shows it. |
| `budget_alert_usd` | number | Warn in the dashboard when a month's sweep spend exceeds this. 0 = off. |
| `budget_stop_usd` | number | Hard cap. When a month's sweep spend reaches this, the sweep skips all refreshes and creations until the next month. Approvals stay checked in [[_Dashboard]]. 0 = off. |
| `notify` | `off` / `on-action` / `always` | Email after a sweep. `on-action` = only when the sweep spent usage or hit the budget stop. `always` = after every executed sweep. Needs `notify_email` here and SMTP settings in `~/.bearings/bearings.env` (`BEARINGS_SMTP_HOST`, `BEARINGS_SMTP_PORT`, `BEARINGS_SMTP_USER`, `BEARINGS_SMTP_PASS`, `BEARINGS_SMTP_FROM`). |
| `notify_email` | address | Where the sweep email goes. |
| `machines` | `name \| local \| dirs` or `name \| ssh=alias \| dirs` | Machines to scan. Multiple dirs comma-separated. The ssh alias must work non-interactively (key auth). |
| `include` / `exclude` | glob patterns | Which project folders to track. Bare pattern = all machines; `machine:pattern` scopes to one. Exclude wins. Non-git folders are only tracked when matched by an explicit (non-`*`) include, or when they already have a note. |
| `owners` | GitHub users/orgs | Repos whose origin matches → `ownership: mine` (gets a CLAUDE.md backlink). Everything else → `external` (repo never touched; docs live only in the vault). |
| `aliases` | `dir-name = note-name` | Map renamed/secondary checkouts to an existing note (e.g. `garmin-sync-repo = garmin-sync`). |

> [!warning] Secrets
> This vault syncs wherever your vault syncs. Bearings records env-variable **names and purposes only**, never values — keep it that way in manual edits too.

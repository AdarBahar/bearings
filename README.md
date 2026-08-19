# Atlas

**One go-to place for every project you work on** — an auto-generated, auto-maintained Obsidian folder where each repo gets an orientation note (setup, deployment, environments, config locations, dependencies, URLs) and a summarized changelog, across all your machines. Ask it questions in plain English; it answers from the notes and verifies live state over SSH when the question is about *now*.

Built on [Claude Code](https://claude.com/claude-code) skills: the intelligence is prompt-defined, the only code is a dependency-free Python sweep and a scheduler installer.

## What you get

- **Per-project orientation notes** in your Obsidian vault — resume any project in under 5 minutes. Machine-readable frontmatter + human sections; your manual notes survive regeneration.
- **Per-project changelogs** — summarized git history, appended on each refresh.
- **Machine notes** — what runs where (containers, services, shared databases with port maps).
- **A dashboard page** — every sweep logs what it found, what it did, and what it cost (tokens + USD, captured from Claude's own usage reporting), with monthly totals and a budget alert.
- **A config page in Obsidian** (`_Config.md`) — cadence, refresh policy, include/exclude lists, machines. Edit it in Obsidian (even on your phone); the next run picks it up. No reinstalls.
- **Plain-English Q&A** — `/atlas-ops how do I restart X?` answers from the notes; `/atlas-ops what's running on my server?` verifies live before answering.

## Install

```bash
git clone https://github.com/<you>/dev-atlas && cd dev-atlas
./install.sh                # links the skills into ~/.claude/skills
claude "/atlas-setup"       # interactive onboarding
```

Onboarding detects your Obsidian vaults, code directories, ssh aliases (and live-tests them), and GitHub identity; asks the decisions that matter (see below); seeds 2–3 representative projects for review before bulk backfill; and installs a daily OS timer (launchd / systemd / cron) that self-gates on your configured cadence.

Requirements: Claude Code CLI, python3, git. Remote machines need a non-interactive ssh alias (key auth).

## The decisions onboarding asks (all editable later in `_Config.md`)

| Question | Why it matters |
|---|---|
| `refresh_mode: report-only` vs `auto` | **Scheduled refreshes spend your Claude usage.** Default is report-only: the sweep lists stale notes in the dashboard and you refresh when you choose. |
| `create_new: ask` / `auto` / `never` | New repos appear as checkboxes in the dashboard; tick to approve documentation. |
| `cadence` | daily / weekly-\<day\> / manual. |
| `include` / `exclude` | Glob lists controlling which folders are tracked — global or scoped per machine (`laptop:tmp-*`). Exclude wins. Non-git folders need an explicit include. |
| `budget_alert_usd` | Monthly spend threshold flagged on the dashboard. |
| SSH for headless runs | Whether scheduled refreshes may connect to your remote machines. |

## Daily use

```bash
claude "/atlas-doc"                    # document/refresh the repo you're in
claude "/atlas-ops <any question>"     # ask about projects, services, machines
python3 scripts/atlas_sweep.py --force # sweep now (respects refresh_mode; --report to only report)
scripts/install-schedule.sh --uninstall  # remove the timer
```

## Security model

- **No secret values, ever.** Notes record env-file locations and variable names/purposes. `.env` files are never read (only `.env.example`). Your vault syncs wherever your vault syncs — Atlas assumes that's semi-public.
- **External repos are never touched.** Repos whose origin isn't in your `owners:` list get vault-only documentation; no file in their working tree is created or modified.
- **Headless permission surface is explicit:** scheduled runs get `Read/Glob/Grep/Write/Edit` plus `git`/`ls`, and `ssh` only if you opted in. Everything else a refresh might want triggers nothing — it's simply not permitted.
- The dashboard shows every run and its cost; nothing spends silently.

## Layout

```
skills/atlas-setup/   onboarding wizard (interactive)
skills/atlas-doc/     note generator/refresher (local + ssh remotes)
skills/atlas-ops/     plain-English Q&A over vault + live state
scripts/atlas_sweep.py       change detection, dashboard, cost tracking (stdlib only)
scripts/install-schedule.sh  daily timer: launchd / systemd user / cron
templates/            _Config.md, _Dashboard.md, project note template
```

## License

MIT

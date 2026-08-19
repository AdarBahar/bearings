---
name: bearings-setup
description: One-time (and re-runnable) onboarding wizard for Bearings. Detects vaults/machines, asks the configuration questions, writes _Config.md into the vault, creates the vault structure, seeds the first project notes, and installs the scheduler.
---

# bearings-setup: onboarding wizard

You are setting up Bearings for this user. Be interactive — use AskUserQuestion for every decision below. Re-running is safe: detect existing config and offer to update rather than overwrite.

## Steps

1. **Locate the Bearings install.** This skill ships with the bearings repo; find its `scripts/` dir (check `~/.bearings/bearings.env` → `BEARINGS_HOME` first, else look for the repo containing this skill, else ask).

2. **Find the vault.** Auto-detect Obsidian vaults from `~/Library/Application Support/obsidian/obsidian.json` (macOS) or `~/.config/obsidian/obsidian.json` (Linux). Ask which vault and which folder inside it (suggest `Projects/Dev`). Warn once: *vault contents inherit the vault's sync exposure (iCloud/Google Drive/Obsidian Sync) — Bearings never writes secret values, only variable names.*

3. **Machines.** Ask which code directories to scan on this machine (suggest detected candidates like `~/Code`, `~/Projects`, `~/src`). Then ask about remote machines: offer aliases found in `~/.ssh/config`; for each accepted one, **test it live** (`ssh -o BatchMode=yes -o ConnectTimeout=8 <alias> hostname`) and ask for its code directories. Only accept machines that pass the test.

4. **Identity.** Detect GitHub identity (`gh auth status`, `git config user.name`, remotes of existing repos) and confirm the list of users/orgs whose repos count as "mine" (everything else is documented as external and its working tree is never touched).

5. **The token-spend questions** (be explicit that scheduled refreshes spend Claude usage):
   - `refresh_mode`: `report-only` (default — sweep only reports; you refresh manually) or `auto` (stale notes regenerate headlessly).
   - `create_new`: `ask` (default — new repos wait for a checkbox in the dashboard) / `auto` / `never`.
   - `cadence`: `weekly-<day>` (default weekly-monday) / `daily` / `manual`.
   - `budget_alert_usd`: monthly alert threshold (0 = off).
   - If any remote machines were configured: may headless runs use SSH? (`BEARINGS_ALLOW_SSH`)
   - **Include/exclude:** ask if they want to document *all* repos in the scanned dirs or a subset. Record `include:` globs (default `*`) and `exclude:` globs; patterns may be scoped per machine as `machine:pattern`. Note: non-git folders are only tracked when explicitly included by name.

6. **Write the config:**
   - `~/.bearings/bearings.env`: `BEARINGS_VAULT_DIR`, `BEARINGS_HOME`, `BEARINGS_CLAUDE_BIN` (resolve with `which claude`), `BEARINGS_ALLOW_SSH`.
   - `<vault>/_Config.md` from `templates/_Config.md`, frontmatter filled with the answers. This page is the source of truth from now on — tell the user they edit settings there.
   - `<vault>/_Dashboard.md` and `<vault>/_templates/project.md` from templates (skip any that exist).
   - `<vault>/_Index.md` if missing.

7. **Seed gradually.** Offer to document 2–3 representative repos now (pick a complex deployed one and a simple one) so the user can review the format before bulk backfill. Run the `/bearings-doc` procedure for the chosen repos. Then tell them how to backfill the rest (`python3 $BEARINGS_HOME/scripts/bearings_sweep.py --force` with `create_new: auto`, or approving checkboxes in the dashboard).

8. **Scheduler.** Ask, then run `$BEARINGS_HOME/scripts/install-schedule.sh` (daily OS timer; the sweep self-gates on the page's `cadence`, so cadence changes in Obsidian apply without reinstalling). Tell the user how to remove it (`install-schedule.sh --uninstall`).

9. **Recap:** where config lives, where the dashboard is, the three commands that matter (`/bearings-doc` in a repo, `/bearings-ops <question>`, `bearings_sweep.py --force`).

---
name: bearings-doc
description: Generate or refresh the Bearings notes for a project. Scans the repo (locally or over SSH) and writes the project note (current state), one note per running deployment, the changelog and the archive into the Bearings vault folder.
disable-model-invocation: true
---

# bearings-doc: generate/refresh the notes of a project

You are documenting a project into the user's Obsidian vault so they (and future Claude sessions) can get oriented fast. The argument is a local path (default: current directory) or `ssh=<alias>:<path>` for a project on a remote machine.

## Locations (resolve first)

1. Read `~/.bearings/bearings.env` → `BEARINGS_VAULT_DIR` is the vault folder. If missing, tell the user to run `/bearings-setup` and stop.
2. Read `<vault>/_Config.md` frontmatter → `owners:` (GitHub users/orgs that count as "mine"), `machines:`, `aliases:` (dir-name = note-name mappings).
3. Templates in `<vault>/_templates/`: `project.md`, `deployment.md`, `archive.md` (also `machine.md`, `group.md`). Read them; they are the canonical structure. The `%% … %%` hints in them list the allowed values. Do not copy the hints into a note.
4. Note path: `<vault>/<name>/<name>.md` where `<name>` is the repo dir name after applying `aliases`. If that doesn't exist but `<vault>/<group>/<name>/<name>.md` does (the project is grouped under a parent project's folder), use that one and keep it there. Below, `<dir>` means the folder that holds the note; the index link is its vault-relative path without `.md`.

## The files of a project

| File | Holds |
|---|---|
| `<dir>/<name>.md` (`type: project`) | The current state only. |
| `<dir>/<name>@<env>.md` (`type: deployment`) | One running instance: one note for each. Two instances with the same env: `<name>@<env>-<host>.md`. |
| `<dir>/changelog.md` | Code changes, from git. |
| `<dir>/archive.md` (`type: archive`) | Old facts, ops events, done items. Newest first. Add entries only. |

A deployment is an instance that runs without a person at the keyboard: a server, a LAN service, a store listing, a scheduled job. A dev server on `localhost` is not a deployment; write its command in Quick start. A dev instance that other clients use over the LAN is a deployment (`@lan`). A scheduled job on a workstation (launchd, cron) is a deployment (`@lan`) on that workstation; the workstation gets a machine note. A project with no deployment (scripts, CLI tools, libraries) gets `deploy_scope: none` and no deployment notes.

## Note rules

- **Current facts only** in the project and deployment notes.
- **Archive before you replace.** Before you change or remove a fact that is in a note, add a "Replaced" entry to `archive.md` with the date, the reason, and the old text. Do this for facts, not for wording changes. Move done open items to `archive.md` as "Done" entries.
- **One place for each fact.** Deployment facts are only in the deployment note (properties). The project note embeds `![[_Deployments.base#Linked to this note]]` and does not repeat them.
- **Properties for data.** Values that a reader searches or compares (host, path, port, URL, user, process, database) go in the properties, one value per property. Text explains; it does not repeat the properties.
- **Empty or unknown.** Leave a property empty if it does not apply. Write `unknown` if it applies but you cannot find the value. Never guess.
- **Names.** `host`: a quoted link to the machine note, `host: "[[server-1]]"`, never an SSH alias (put that in `ssh`). `project`: a quoted link to the project note, `project: "[[app]]"`. The Base views compare these properties with links; a plain name does not match, and the deployment is missing from the table of that machine or project. `database`: `engine@machine/db`. `clones`: `machine:path`. `env`, `status`, `runtime`, `deploy_method`: only the values in the template hints.
- **Hosts that are not your machines.** App store listings: `host: "[[Stores]]"`, `env: store`, one note per store (`<name>@store-chrome.md`). GitHub Pages and scheduled GitHub Actions: `host: "[[GitHub]]"`. A service on a server that is not yours: `host: "[[Testing]]"`, `env: testing`. Each of these hosts has a note with `type: machine` and `kind: platform` or `external`. Make the note if it does not exist.
- **YAML.** Quote a property value that contains `: ` or starts with `:` (`port: ":3000"`, `summary: "…: …"`). Obsidian cannot read the properties of a note with invalid YAML, and the note is missing from the views.
- **Dates.** `updated`: date and time of this write (`YYYY-MM-DDTHH:MM`). `verified`: change it only when you checked the deployment against the live system in this run; then set `verified_how: live`. Each section with facts gets the stamp line `*Updated YYYY-MM-DD · source: repo|live|owner*`; change the stamp only for a section whose facts you checked.
- **Retired.** A deployment that stopped for good: set `status: retired`, add a "Replaced" entry to `archive.md`, keep the note.

## Procedure

1. **Scan the project.** In a headless sweep run, plain `git` is not an allowed tool; run `python3 $BEARINGS_HOME/scripts/git_ro.py <subcommand> …` instead (read-only subcommands: log, shortlog, remote, tag, branch, rev-parse, describe, ls-files; there is no `status` and no modification check; do not quote the script path). In a headless run, a folder-scoped Grep works only in a folder without `.env` files: grep a subfolder, use a plain file-name glob (for example `glob: "package.json"`), or Read the files you need.. Local: read directly. Remote (`ssh=<alias>:<path>`): batch reads over SSH (`ssh <alias> 'cat …; ls …; git -C … log …'`) to minimize round-trips. Sources in priority order: `CLAUDE.md`, `AGENTS.md`, `README*`, `docs/`, `docker-compose*`, `Dockerfile*`, reverse-proxy configs, deploy scripts/CI workflows, manifests (`package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`, …), `.env.example`, `git remote -v` + last commit. Use an Explore agent for large repos.
2. **Ownership:** `mine` if the git origin belongs to one of `owners:`, else `external`. External repos are documented in the vault the same way, but NEVER create or modify any file inside an external repo.
3. **Write the notes** following the templates. Real commands, ports, URLs, paths. Find the deployments in deploy scripts, CI workflows, compose files, proxy configs and the machine notes. Set `doc_architecture`, `doc_deployment`, `doc_runbook`, `doc_api` to `repo:<path>` when the repo has such a document.
4. **SECRETS RULE (hard):** vaults sync to cloud services. Record env file *locations*, variable *names + purpose*, and where secrets are kept (`secrets_in`) only. Never read `.env` files — use `.env.example` or references in code/compose.
5. **Refresh (note exists):** preserve verbatim the `<!-- manual:start/end -->` and `<!-- manual-extra:start/end -->` fenced sections. In deployment notes, keep property values that the user set and that you cannot check; keep `verified` unless you checked live. Regenerate the rest by the note rules above.
6. **Old format.** A project note without `type: project` uses the old format. Convert it: (a) copy the full old note into `archive.md` as one "Replaced: full note (old format)" entry; (b) make one deployment note for each running environment in its `environments` list and its Environments/Deployment text; (c) move each dated ops or incident section to `archive.md` as an "Ops" entry; (d) write the project note from the template. Keep the manual fences.
7. **Changelog** — maintain `<dir>/changelog.md`, newest first. On refresh: summarize `git log --since=<previous updated>` into one dated entry (3–8 bullets grouped by theme, PR numbers linked, version tags named). First creation: seed from tags + last ~30 days. No git history (plain folder): summarize file-level changes. No new commits: leave untouched.
8. **Index** — add/update this project's row in `<vault>/_Index.md` (link, status, ownership, stack, deployments as `env@host` from the deployment notes that are not retired, updated date). Keep rows alphabetized. (When invoked by the sweep for many projects, still update your own row only.)
9. **Backlinks (owned local repos only):** ensure the repo's agent context files end with a pointer line to the vault note — `CLAUDE.md` always (create a minimal one if none exists), and `AGENTS.md` too **if it already exists** (never create AGENTS.md just for this). This makes the knowledge base discoverable by both Claude Code and Codex/other agents that read AGENTS.md. Leave changes uncommitted. Skip for external repos and remote (`ssh=`) projects.
10. **Live checks:** while connected to a remote machine, check this project's deployments there (`docker ps`, `systemctl --user …`, `pm2 ls`). Update those deployment notes and their `verified`. Machine notes embed the deployment view; do not add deployment rows to them.
11. **Lint:** run `python3 "$BEARINGS_HOME/scripts/bearings_lint.py" <paths of the notes you wrote>` (`BEARINGS_HOME` is in `~/.bearings/bearings.env`). Fix each reported problem, then run it again until it is clean. In a headless sweep run a hook runs this check after each edit; if you cannot run Bash commands beyond git/ls, skip this step and rely on the hook.
12. **Report:** the paths written, the deployment notes made or retired, the archive entries added, lint problems you could not fix, and what's marked unknown.

## Style

Orientation, not exhaustive documentation — link repo docs for depth. Short sentences. The test: "could the user resume this project after 3 months away, in under 5 minutes, from these notes alone?"

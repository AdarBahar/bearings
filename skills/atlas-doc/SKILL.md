---
name: atlas-doc
description: Generate or refresh the Atlas orientation note for a project. Scans the repo (locally or over SSH) and writes a structured note (setup, deployment, environments, config, dependencies) plus a changelog into the Atlas vault folder.
---

# atlas-doc: generate/refresh a project orientation note

You are documenting a project into the user's Obsidian vault so they (and future Claude sessions) can get oriented fast. The argument is a local path (default: current directory) or `ssh=<alias>:<path>` for a project on a remote machine.

## Locations (resolve first)

1. Read `~/.atlas/atlas.env` → `ATLAS_VAULT_DIR` is the vault folder. If missing, tell the user to run `/atlas-setup` and stop.
2. Read `<vault>/_Config.md` frontmatter → `owners:` (GitHub users/orgs that count as "mine"), `machines:`, `aliases:` (dir-name = note-name mappings).
3. Template: `<vault>/_templates/project.md` — read it; it is the canonical structure.
4. Note path: `<vault>/<name>/<name>.md` where `<name>` is the repo dir name after applying `aliases`.

## Procedure

1. **Scan the project.** Local: read directly. Remote (`ssh=<alias>:<path>`): batch reads over SSH (`ssh <alias> 'cat …; ls …; git -C … log …'`) to minimize round-trips. Sources in priority order: `CLAUDE.md`, `AGENTS.md`, `README*`, `docs/`, `docker-compose*`, `Dockerfile*`, reverse-proxy configs, deploy scripts/CI workflows, manifests (`package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`, …), `.env.example`, `git remote -v` + last commit. Use an Explore agent for large repos.
2. **Ownership:** `mine` if the git origin belongs to one of `owners:`, else `external`. External repos are documented in the vault the same way, but NEVER create or modify any file inside an external repo.
3. **Write the note** following the template exactly. Real commands, ports, URLs, paths — mark genuinely undiscoverable facts "unknown" rather than guessing. `local_path`: the path, prefixed `<machine>:` for remote projects. Hosts in `environments[].host`: use the machine names from `_Config.md` and any host names found in deploy configs.
4. **SECRETS RULE (hard):** vaults sync to cloud services. Record env file *locations* and variable *names + purpose* only. Never read `.env` files — use `.env.example` or references in code/compose.
5. **Refresh (note exists):** preserve verbatim the `<!-- manual:start/end -->` and `<!-- manual-extra:start/end -->` fenced sections and manually added `environments` entries. Regenerate the rest; set `updated:` to today.
6. **Changelog** — maintain `<vault>/<name>/changelog.md`, newest first. On refresh: summarize `git log --since=<previous updated>` into one dated entry (3–8 bullets grouped by theme, PR numbers linked, version tags named). First creation: seed from tags + last ~30 days. No git history (plain folder): summarize file-level changes. No new commits: leave untouched.
7. **Index** — add/update this project's row in `<vault>/_Index.md` (link, status, ownership, stack, environments as `env@host`, updated). Keep rows alphabetized. (When invoked by the sweep for many projects, still update your own row only.)
8. **Backlink (owned local repos only):** ensure the repo's `CLAUDE.md` ends with a pointer line to the vault note (create a minimal `CLAUDE.md` if none). Leave uncommitted. Skip for external repos and remote (`ssh=`) projects.
9. **Machine notes:** if `<vault>/<machine>/<machine>.md` exists for a remote project's machine (frontmatter `type: machine`), verify live state while connected (`docker ps`, `systemctl --user …`) and update that note's tables if this project's rows changed.
10. **Report:** note path, what was filled, what's marked unknown.

## Style

Orientation, not exhaustive documentation — link repo docs for depth. The test: "could the user resume this project after 3 months away, in under 5 minutes, from this note alone?"

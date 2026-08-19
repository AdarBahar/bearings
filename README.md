# Bearings

**A second brain for your development environment.**

Bearings builds and maintains a persistent knowledge base for your projects, local development environments, machines, and deployments, so important technical context does not disappear between coding sessions, machines, or months away from a project.

It captures the information you need to get your bearings quickly: **how a project is structured, how to run it, where it is deployed, configuration locations, dependencies, services, environments, URLs, infrastructure, and what recently changed.**

The knowledge base lives in your Obsidian vault and acts as persistent **architecture and operational context for coding agents**. Claude Code uses it directly through the Bearings skills instead of rediscovering your environment every session. For repositories you own, Bearings also adds a pointer to the knowledge base in `CLAUDE.md` and — when the repo has one — `AGENTS.md`, so Codex and other agents that read those files discover it automatically.

Think of Bearings as the persistent layer between **your code, your infrastructure, your notes, and your coding agents**.

> The goal: come back to any project after three months and understand how it works, how to run it, and where everything lives in under five minutes.

## Why Bearings?

The knowledge needed to work on a project rarely lives in one place.

Some of it is in the repository:

* `README.md`
* `CLAUDE.md` / `AGENTS.md`
* Docker and Compose files
* deployment scripts
* CI configuration
* `.env.example`
* package manifests
* reverse proxy configuration

Some of it lives outside the repository:

* which machine runs the service
* which ports it uses
* where the database lives
* how staging or production is deployed
* SSH aliases
* service and container names
* local development setup
* URLs and API endpoints

And some of it tends to live only in your memory.

Bearings turns that scattered information into a **persistent, human-readable project knowledge base** that can also be used by your coding agents.

## How it works

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/architecture-dark.svg">
  <img alt="Bearings architecture: repos, dev machines, and servers feed the Bearings skills and sweep, which maintain an Obsidian knowledge base consumed by you, Claude Code, and other coding agents. Live-state questions are verified over SSH." src="assets/architecture-light.svg">
</picture>

There are three main pieces:

1. **`/bearings-doc`** scans a project and creates or refreshes its orientation note and changelog.
2. **`bearings_sweep.py`** discovers projects, detects stale documentation, tracks new projects, and optionally triggers refreshes.
3. **`/bearings-ops`** answers questions using the knowledge base and verifies live infrastructure state when the question depends on what is running now.

The Markdown files in Obsidian are the persistent layer. They remain useful independently of any individual Claude or coding-agent session.

## What you get

### Project orientation notes

Each project gets a compact orientation note containing information such as:

* what the project does
* architecture and major components
* quick-start commands
* environments
* local development setup
* deployment process
* configuration file locations
* environment variable names and purposes
* dependencies
* services and infrastructure
* URLs and API endpoints
* important repository documentation
* where the project lives on your machines

Machine-readable frontmatter makes the notes structured, while normal Markdown keeps them readable and editable by humans.

Manual sections survive regeneration.

### Project changelogs

Each project gets a summarized changelog derived from Git history.

On refresh, Bearings summarizes what changed since the previous update instead of requiring you to reconstruct months of project history manually.

### Machine and deployment knowledge

Bearings can maintain machine-level knowledge about where things run, including:

* services
* containers
* shared databases
* ports
* project locations
* deployment environments

This keeps operational knowledge alongside project architecture instead of leaving it scattered across shell history, old notes, and memory.

### Persistent context for coding agents

Bearings gives your coding agent a durable knowledge layer across sessions.

Instead of starting cold and repeatedly rediscovering:

> Where is the database?

> How is this deployed?

> Which machine runs this service?

> What port does it use?

> How do I run this locally?

the agent can start from the Bearings knowledge base.

**Claude Code integration is built in** through the Bearings skills.

**Codex and other agents are supported through the knowledge base itself**: the notes are standard Markdown, and for repositories you own, Bearings adds an orientation-doc pointer to `CLAUDE.md` (always) and `AGENTS.md` (when the repo already has one). Any agent that reads those files — or is given access to the vault — starts oriented.

The interactive parts of Bearings (`/bearings-doc`, `/bearings-ops`, live-state verification over SSH) run as Claude Code skills; other agents consume the generated knowledge, not the skills.

### Plain-English project and ops Q&A

Ask questions such as:

```bash
claude "/bearings-ops how do I run project-a locally?"
```

or:

```bash
claude "/bearings-ops where is the database for project-a?"
```

For stored architectural or procedural knowledge, Bearings answers from the notes.

For questions about **current state**, such as:

```bash
claude "/bearings-ops what's running on my server?"
```

`/bearings-ops` verifies live state before answering, using the SSH access you configured (falling back to the last documented state, clearly labeled, when a machine is unreachable).

It can inspect things such as:

* Docker containers
* systemd services
* listening ports
* PM2 processes
* launchd services

`/bearings-ops` can also perform explicit operational actions when requested.

For example:

```bash
claude "/bearings-ops restart project-a"
```

Development and local operations can be performed directly when permitted.

For staging or production operations, Bearings presents the exact action and requires confirmation first.

### Dashboard

Every sweep updates an Obsidian dashboard showing:

* new projects
* stale project notes
* up-to-date projects
* unreachable machines
* actions performed
* Claude token usage
* estimated USD cost
* monthly totals
* budget warnings

When `create_new: ask` is enabled, newly discovered projects appear as checkboxes that you can approve directly from Obsidian.

### Configuration in Obsidian

Most Bearings configuration lives in:

```text
_Config.md
```

This includes:

* refresh cadence
* refresh policy
* new-project behavior
* include/exclude rules
* machines
* repository owners
* project aliases
* monthly budget alerts

Edit the page in Obsidian, including from another synced device, and the next sweep reads the updated configuration.

No reinstall is needed when these settings change.

A small amount of machine-specific configuration lives separately in:

```text
~/.bearings/bearings.env
```

This includes local paths and permissions such as whether automated Claude refreshes may use SSH.

## Install

```bash
git clone https://github.com/AdarBahar/bearings
cd bearings

./install.sh
claude "/bearings-setup"
```

`install.sh` links the Bearings skills into:

```text
~/.claude/skills
```

The interactive onboarding then:

1. finds your Obsidian vaults
2. detects local code directories
3. detects SSH aliases and live-tests selected remote machines
4. detects your GitHub identity
5. asks which repositories should be tracked
6. configures refresh and new-project behavior
7. creates the Bearings vault structure
8. offers to document a few representative projects first
9. optionally installs the automatic sweep scheduler

This lets you review what Bearings generates before backfilling your entire development environment.

### Requirements

* Claude Code CLI
* Python 3
* Git
* an Obsidian vault

For remote machines:

* SSH access
* a non-interactive SSH alias using key authentication

## Daily use

### Document or refresh the current project

```bash
claude "/bearings-doc"
```

You can also target another local path or a configured remote project.

### Ask about your projects or infrastructure

```bash
claude "/bearings-ops <question>"
```

Examples:

```bash
claude "/bearings-ops how do I restart project-a?"
claude "/bearings-ops where is project-a deployed?"
claude "/bearings-ops which projects use the shared Postgres server?"
claude "/bearings-ops what's currently running on my server?"
```

### Run project discovery now

```bash
python3 scripts/bearings_sweep.py --force
```

The sweep respects your configured refresh policy.

To discover and report without triggering documentation generation:

```bash
python3 scripts/bearings_sweep.py --force --report
```

### Remove the scheduler

```bash
scripts/install-schedule.sh --uninstall
```

## Refresh model

Bearings separates **change detection** from **AI-powered documentation refreshes**.

This matters because scanning your machines is inexpensive, while regenerating documentation consumes Claude usage.

### `refresh_mode`

#### `report-only`

The default.

Bearings detects stale project notes and reports them in the dashboard, but does not automatically invoke Claude to regenerate them.

#### `auto`

When a project has changed since its Bearings note was last updated, Bearings automatically invokes `/bearings-doc`.

This consumes Claude usage.

### `create_new`

Controls what happens when Bearings discovers a project that does not have a note yet.

| Value   | Behavior                                      |
| ------- | --------------------------------------------- |
| `ask`   | Add the project to the dashboard for approval |
| `auto`  | Automatically document it                     |
| `never` | Ignore new projects                           |

### `cadence`

Supported values:

```text
daily
weekly-<weekday>
manual
```

The installed OS timer runs daily. The sweep itself reads `_Config.md` and decides whether it should act that day.

This means changing cadence does not require reinstalling the scheduler.

## Remote machines and SSH

Remote machines are configured using SSH aliases.

For example:

```text
linux-laptop | ssh=linux | ~/Code
server | ssh=server | /var/www
```

Bearings can use remote machines for two related purposes:

1. **Project discovery**, to determine which projects exist and whether they have changed. This runs inside `bearings_sweep.py` and costs no Claude usage.
2. **Claude-powered documentation and live-state inspection**, performed by the `/bearings-doc` and `/bearings-ops` skills. For scheduled (headless) runs, SSH is only used if you explicitly enabled it during onboarding (`BEARINGS_ALLOW_SSH`).

Remote access should use SSH keys so scheduled operations do not depend on interactive password prompts. If a machine is unreachable, Bearings reports that and falls back to the last documented state, clearly labeled with its date.

## Security model

### No secret values

Bearings records:

* environment file locations
* variable names
* what those variables are used for

It does **not** intentionally record secret values.

`.env` files are never read by `/bearings-doc`. Safe sources such as `.env.example` and references from code or deployment configuration are used instead.

Your Bearings folder may be synced through services such as Obsidian Sync, iCloud, or Google Drive, so it should be treated as semi-public documentation rather than a secrets store.

### External repositories are not modified

Repositories are classified using the configured `owners:` list.

Repos belonging to one of those GitHub users or organizations are treated as yours.

Other repositories are treated as external.

External repositories can still be documented in the Bearings vault, but Bearings does not create or modify files in their working tree.

### Human notes survive regeneration

Generated project notes contain protected manual sections.

You can use them for:

* what you were working on
* open questions
* next steps
* architectural decisions
* anything else Claude could not infer from the repository

Those sections survive future Bearings refreshes.

### Explicit operational actions

`/bearings-ops` distinguishes between asking **how** to do something and asking Bearings to **do** it.

For example:

```text
How do I restart project-a?
```

returns instructions.

```text
Restart project-a
```

requests an action.

Production and staging actions require confirmation before execution.

### Visible AI usage

The dashboard records Claude usage from automated Bearings runs, including:

* input tokens
* output tokens
* estimated cost
* monthly totals

You can configure a monthly budget warning.

## Configuration

The main configuration is stored as frontmatter in:

```text
_Config.md
```

Typical configuration:

```yaml
---
cadence: weekly-monday
refresh_mode: report-only
create_new: ask
budget_alert_usd: 0

machines:
  - "mac | local | ~/Code"
  - "linux-laptop | ssh=linux | ~/Code"

include:
  - "*"

exclude:
  - "tmp-*"

owners:
  - your-github-username

aliases:
  - "old-directory-name = project-name"
---
```

### Settings

| Setting            | Meaning                                                 |
| ------------------ | ------------------------------------------------------- |
| `cadence`          | `daily`, `weekly-<weekday>`, or `manual`                |
| `refresh_mode`     | `report-only` or `auto`                                 |
| `create_new`       | `ask`, `auto`, or `never`                               |
| `budget_alert_usd` | Monthly automated-refresh budget warning                |
| `machines`         | Local and SSH machines and directories to scan          |
| `include`          | Project folder patterns to include                      |
| `exclude`          | Project folder patterns to exclude                      |
| `owners`           | GitHub users/orgs whose repositories count as yours     |
| `aliases`          | Map multiple or renamed directories to one project note |

Patterns can also be scoped to a specific machine:

```text
linux-laptop:tmp-*
```

Exclude rules win over include rules.

Non-Git folders are only tracked when explicitly included or when they already have a Bearings note.

## What Bearings stores

A typical vault looks like:

```text
Bearings/
├── _Config.md
├── _Dashboard.md
├── _Index.md
│
├── project-a/
│   ├── project-a.md
│   └── changelog.md
│
├── project-b/
│   ├── project-b.md
│   └── changelog.md
│
└── linux-laptop/
    └── linux-laptop.md
```

A project orientation note contains sections such as:

```text
Project
├── Resume here
├── Quick start
├── Environments & access
├── Deployment
├── Configuration
├── External dependencies
├── Architecture
└── Links
```

The intention is **orientation, not exhaustive documentation**.

Existing repository documentation remains the source for deeper technical detail.

## Repository layout

```text
skills/
├── bearings-setup/
│   └── SKILL.md
├── bearings-doc/
│   └── SKILL.md
└── bearings-ops/
    └── SKILL.md

scripts/
├── bearings_sweep.py
└── install-schedule.sh

templates/
├── _Config.md
├── _Dashboard.md
└── project.md

assets/
├── architecture-light.svg
└── architecture-dark.svg

install.sh
README.md
LICENSE
```

### `bearings-setup`

Interactive onboarding and configuration.

### `bearings-doc`

Scans local or remote projects and maintains their persistent orientation notes and changelogs.

### `bearings-ops`

Uses the Bearings vault as a knowledge base for project and infrastructure questions, with live verification when current state matters.

### `bearings_sweep.py`

Dependency-free Python responsible for:

* discovering projects
* detecting changes
* identifying stale notes
* processing project approvals
* invoking documentation refreshes
* updating the dashboard
* tracking automated Claude usage

### `install-schedule.sh`

Installs the daily trigger using:

* `launchd` on macOS
* a systemd user timer on Linux
* cron as a fallback

The daily trigger does not necessarily cause an AI refresh. The configured cadence and refresh policy determine what the sweep actually does.

## Design principles

**Persistent over conversational**

Important project knowledge should survive the end of an AI session.

**Human-readable**

The source of truth is Markdown in your Obsidian vault, not an opaque AI memory store.

**Agent-friendly**

The same knowledge should help both you and the coding agents working on the project.

**Orientation over exhaustive documentation**

Bearings should tell you where to look and how things fit together, not duplicate every document in your repository.

**Live state when it matters**

Stored knowledge is useful for architecture and procedures. Questions about what is running *right now* should be verified against the actual machine.

**No secrets**

Architecture knowledge belongs in Bearings. Credentials do not.

## License

MIT

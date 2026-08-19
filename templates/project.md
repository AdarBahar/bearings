---
project: PROJECT-NAME
repo: github.com/OWNER/REPO
ownership: mine          # mine | external
status: active           # active | paused | archived
stack: []
local_path: ~/Code/PROJECT-NAME
environments: []
  # - {name: dev, host: mac, url: "http://localhost:PORT"}
  # - {name: dev, host: linux-laptop, url: "http://192.168.x.x:PORT"}
  # - {name: staging, host: server-1, url: "https://..."}
  # - {name: prod, host: server-2, url: "https://..."}
updated: YYYY-MM-DD
---

# PROJECT-NAME

> One-line description of what this project does.

## Resume here

<!-- manual:start -->
*What I was doing last, open threads, next steps. This section is never touched by the generator — keep your own notes here.*
<!-- manual:end -->

## Quick start

```bash
# run locally (dev)
# run tests
# build
```

## Environments & access

| Env | Host | URL / Access | Notes |
|-----|------|--------------|-------|
| dev | mac | http://localhost:PORT | |

**API endpoints:** base URL, docs URL (Swagger/OpenAPI), auth method.

## Deployment

How each environment gets deployed (script, compose file, PM2, CI). One subsection per target if they differ.

## Configuration

> ⚠️ Variable **names and purpose only** — never values. This vault syncs to Google Drive.

| File | Machine | Purpose |
|------|---------|---------|
| `.env` | mac | local dev config |

**Key variables:** grouped by purpose (DB, LLM providers, external APIs, feature flags).

## External dependencies

Services this project talks to: LLM providers, third-party APIs, my other services (link them: [[other-project]]).

## Architecture

Short overview of components and data flow. Link repo docs for depth — don't duplicate them here.

## Links

- Repo: https://github.com/OWNER/REPO
- Changelog: [[PROJECT-NAME/changelog|changelog]]
- CLAUDE.md: `~/Code/PROJECT-NAME/CLAUDE.md`
- Key docs: (paths in repo)
- Full-context dump for AI (useful for external/unfamiliar repos): `npx repomix` in the repo root → single AI-friendly file

<!-- manual-extra:start -->
<!-- Anything else you add below survives regeneration. -->
<!-- manual-extra:end -->

---
type: project
project: PROJECT_NAME
summary: What the project does, in one sentence.
status: active
ownership: mine
group:
stack: []
repo: https://github.com/OWNER/REPO
default_branch: main
clones:
  - "mac:~/Code/PROJECT_NAME"
deploy_scope: none
deployments: []
domains: []
databases: []
doc_architecture:
doc_deployment:
doc_runbook:
doc_api:
updated: YYYY-MM-DDTHH:MM
verified:
---
%% Rules: current facts only. Before you change a fact, move the old text to archive.md. Empty = does not apply. "unknown" = applies, value not known. Never write a secret value. deploy_scope: public | private | lan | none. Quote a YAML value that contains ": ". Delete these %% hints when you fill the note. %%

# PROJECT_NAME

> What the project does, in one sentence. The current focus, in one more sentence.

## Resume here

<!-- manual:start -->
%% Your notes: last work, open threads, next step. The generator does not change this section. %%
<!-- manual:end -->

## Quick start

*Updated YYYY-MM-DD · source: repo*

```bash
# install
# run      → http://localhost:PORT
# test
# build
```

## Deployments

![[_Deployments.base#Linked to this note]]

%% Do not type this table. Make one note for each running instance: PROJECT_NAME@<env>.md (template: deployment). %%

## Deployment process

*Updated YYYY-MM-DD · source: repo*

%% 3–8 lines: trigger → build → transfer → migrate → restart → health check → rollback. Link doc_deployment for the details. %%

## Configuration

*Updated YYYY-MM-DD · source: repo*

| File | Where | Purpose |
|---|---|---|
| `.env` | clone | dev settings |

%% Variable names grouped by purpose. Then one line: "Secrets kept in: …" (names of vault items or files, not values). %%

## External dependencies

| Dependency | Used for | Variable |
|---|---|---|
| | | |

## Architecture

*Updated YYYY-MM-DD · source: repo*

%% 5–15 lines: components and data flow. Link doc_architecture for the details. Do not copy repo documents. %%

## Open items

- [ ] YYYY-MM-DD — item

%% Move done items to archive.md. %%

## Links

- Changelog: [[PROJECT_NAME/changelog|changelog]]
- Archive: [[PROJECT_NAME/archive|archive]]
- CLAUDE.md: `~/Code/PROJECT_NAME/CLAUDE.md`

<!-- manual-extra:start -->
<!-- manual-extra:end -->

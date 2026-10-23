---
type: deployment
project: "[[PROJECT_NAME]]"
env: prod
status: running
host: "[[MACHINE]]"
ssh:
urls: []
health_url:
app_path:
config_path:
log_path:
run_as:
runtime:
process:
service_unit:
port:
proxy:
auth:
database:
db_roles: []
deploy_method:
deploy_trigger:
deploy_ref:
deploy_user:
version:
deployed:
backups:
secrets_in:
verified:
verified_how:
updated: YYYY-MM-DDTHH:MM
---
%% File name: PROJECT_NAME@<env>.md. One note for each running instance.
env: prod | staging | qa | test | lan | preview | ci | store
status: running | stopped | planned | retired | unknown
host: the machine note name, never an SSH alias
runtime: pm2 | systemd | systemd-user | docker | launchd | cron | static | cpanel | store
deploy_method: github-actions | script | git-pull | manual | store-upload | ftp
database: engine@machine/db, for example postgresql-16@server-1/app
verified: the date of the last live check · verified_how: live | repo | owner | memory
Empty = does not apply. "unknown" = applies, value not known. Delete these hints when you fill the note. %%

# PROJECT_NAME @ ENV

## Access

```bash
ssh ALIAS
curl -s HEALTH_URL
```

## Deploy

%% Steps, or a link to doc_deployment. %%

## Rollback

%% Steps. %%

## Notes

%% Limits and special rules. Delete this section if there are none. %%

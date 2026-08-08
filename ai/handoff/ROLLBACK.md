# Rollback — OEM Radar cloud migration

## Code rollback

```
6805c0c  Baseline commit: current state of OEM Radar before cloud migration
08f0da6  Cloud portability: Docker, runtime bridge, backup/restore (Tier C, not production)
<next>   Shopify investigation report (docs only, no code change to roll back)
```

`git checkout master` (or reset to `6805c0c`) fully reverts. The Windows launchers
(`start-radar.cmd`, `crawl-hourly.cmd`, `.vbs`, `install-hourly-task.*`) were never
modified in this phase (the webhook redaction happened in the baseline commit, before
this branch), so native Windows operation is unaffected regardless of branch.

## Deployment rollback

Not applicable yet — nothing has been deployed. `docker-compose.yml` requires an
explicit `IMAGE_TAG` (immutable commit SHA), so there is no bare `:latest` reference
to accidentally roll forward or back to once a real deployment exists.

## State rollback

No schema changes were made. The backup/restore drill in this phase
(`scripts/backup.py` / `scripts/restore.py`) is itself the proven rollback mechanism
for state: restore into an isolated directory, verify `PRAGMA integrity_check`, then
point a container at the verified copy before ever touching a live volume.

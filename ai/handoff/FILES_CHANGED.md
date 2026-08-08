# Files changed — cloud/oem-portability

## Commit 08f0da6 (mechanical portability)
### Added
- `Dockerfile`, `.dockerignore`, `docker-compose.yml` (portability/investigation only, no production compose)
- `scripts/docker-entrypoint.sh`
- `scripts/backup.py`, `scripts/restore.py` (new — no backup mechanism existed before)
- `src/oem_radar/paths.py` (OEM_RADAR_DATA_DIR remap, used only by the new health command)
- `src/oem_radar/runtime_bridge.py`

### Modified
- `src/oem_radar/cli.py` — added `version`/`identity`/`health` as new argparse subcommands (additive; `validate`/`run`/`status`/etc. unchanged)

## Commit (this one) — investigation only
### Added
- `ai/handoff/SHOPIFY_INVESTIGATION.md`
- `ai/handoff/CLOUD_OEM_RADAR_REPORT.md`, `FILES_CHANGED.md`, `TEST_RESULTS.md`, `KNOWN_ISSUES.md`, `DECISIONS.md`, `ROLLBACK.md`

No collector, engine, provider, or database code was touched by the investigation —
it produced no code changes, only evidence and a report.

## Explicitly left unchanged
- All engines (`src/oem_radar/engines/*`), providers, core crawl/pipeline logic
- Database schema
- `config/oems/*.yaml` (no OEMs added/removed)
- Windows launchers (`start-radar.cmd`, `crawl-hourly.cmd`, `.vbs`, `install-hourly-task.*`) — retained for transitional rollback, excluded from the container path via `.dockerignore`

# OEM Radar — Stage 1 Portability Report

**Pilot clank:** OEM Radar (`oem-radar`)  
**Date:** 2026-08-03  
**Objective:** Linux-first Docker portability without changing collector behavior.

## Portability issues found

| Issue | Severity | Location | Resolution |
|-------|----------|----------|------------|
| Windows Task Scheduler wrappers | High (ops) | `crawl-hourly.cmd`, `install-hourly-task.cmd`, `*.vbs` | Added `scripts/crawl.sh` for cron/external schedulers. Original Windows scripts retained for dual-boot ops. |
| Launcher scripts assume `cmd.exe` / `py -3` | Medium | `start-radar.cmd`, `dashboard.cmd` | Linux uses `oem-radar` console script + Docker entrypoint. |
| Dashboard auto-opens browser | Low | `dashboard/__init__.py` via CLI | Already had `--no-browser`; Stage 1 also honors `OEM_RADAR_OPEN_BROWSER=0` (image default). |
| Windows MAX_PATH commentary / path length | Low | `fetch.py` comments | Code already uses short content-hash filenames; no code change required. |
| README documents `set VAR=` Windows syntax | Low | README | Documented export form; no behavior change. |
| Relative `data/radar.db` paths | Medium | `radar.yaml`, config defaults | Work correctly when process cwd is project/container `/app`. Optional `OEM_RADAR_DATA_DIR` recognized by runtime bridge for health. |
| Discord webhook via env or file | None | already portable | `OEM_RADAR_DISCORD_WEBHOOK` or `config/discord_webhook.txt`. |

## Fixes applied

1. **Dockerfile** (Linux AMD64, non-root user `clank`, no public ports by default).
2. **docker-compose.yml** with named volume for `/app/data`, healthcheck via `oem-radar health`, `restart: unless-stopped`.
3. **scripts/entrypoint.sh** — maps CLI verbs; no scheduling.
4. **scripts/crawl.sh** — Linux equivalent of hourly crawl logging.
5. **runtime_bridge.py** — identity / health / version using Stage 0.5 `clank-runtime` contracts when installed.
6. **CLI** — `oem-radar version|identity|health` (read-only; no crawl).
7. **Inventory registration** in `clank-fleet/inventories/clanks.example.yaml`.
8. **`.env.example`**, **`.dockerignore`**.

## Files changed / added

**Added**
- `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `.env.example`
- `scripts/entrypoint.sh`, `scripts/crawl.sh`
- `src/oem_radar/runtime_bridge.py`
- `tests/test_runtime_bridge.py`
- `inventory.registration.yaml`
- `PORTABILITY_REPORT.md` (this file)

**Modified**
- `src/oem_radar/cli.py` — version/identity/health commands; browser env gate
- `unified-clank-stage0/clank-fleet/inventories/clanks.example.yaml` — pilot entry

**Unchanged (intentionally)**
- All engines, parsers, diff, discord provider, sqlite schema, collectors
- Severity rules, OEM YAML descriptors
- Domain database contents (shipped `data/radar.db` preserved)

## Linux assumptions removed / mitigated

- No dependency on Task Scheduler or `.cmd` / `.vbs` for container operation.
- No Windows drive letters in runtime code paths (already pathlib).
- Container runs as non-root UID 10001.
- Browser auto-open disabled in image.

## Remaining Windows assumptions

- Original `*.cmd` / `*.vbs` still present for operators who keep a Windows host for a while.
- Some docs still show Windows launcher examples (harmless).
- Historical crawl logs may contain Windows-style timestamps from prior runs.

## Docker notes

```bash
cd oem-radar
docker build -t oem-radar:stage1 .
docker compose run --rm oem-radar health
docker compose run --rm oem-radar version
# one-shot crawl (same behavior as before):
docker compose run --rm oem-radar run --dry-run
# persist data across recreations via named volume oem_radar_data
```

**Sandbox limitation:** Docker CLI was not available in the Stage 1 build environment. Dockerfile and compose were validated structurally; image build must be confirmed on an AMD64 Docker host.

## Health / version evidence (Linux host, this environment)

```text
oem-radar version  → clank_id oem-radar, runtime_bridge stage1
oem-radar identity → RuntimeIdentity release_channel=production
oem-radar health   → operational_state=healthy, last_successful_run from crawler_runs
pytest             → 96 existing + 3 bridge = 99 passed
```

## Persistent data survives recreation (design)

- Domain DB path: `data/radar.db` (volume-mounted at `/app/data` in compose).
- Evidence/raw and http_cache under the same volume.
- Container recreation without removing the volume leaves SQLite + evidence intact.
- Image does not bake runtime DB writes into the layer (`data/` excluded from critical cache via dockerignore for cache/raw).

## Unresolved issues

1. Docker image build not executed in this sandbox (no docker binary).
2. Optional: make `db_path` / `raw_dir` fully honor `OEM_RADAR_DATA_DIR` inside the store constructor (today health bridge respects it; crawl still uses radar.yaml relative paths resolved from WORKDIR `/app`, which is correct when the volume is mounted at `/app/data`).
3. Schema has no first-class “backup freshness” field — health leaves it null (accurate).

## Recommended NAS deployment approach (Stage 1 guidance only)

1. Build `oem-radar:stage1` on CI (linux/amd64).
2. On NAS (or any Linux host): place compose file; map a host directory for `/app/data`.
3. Set `OEM_RADAR_DISCORD_WEBHOOK` via NAS secret / env file (not in git).
4. Use NAS task scheduler or cron to `docker compose run --rm oem-radar run` hourly — **external** scheduler (mirrors prior Windows Task Scheduler model).
5. Do not publish dashboard port publicly; if needed, bind `127.0.0.1:8787` over Tailscale later (Stage 1 non-goal).
6. Verify: `docker compose run --rm oem-radar health` after first crawl.

## Architecture deviations

**None.**

- No changes to Stage 0.5 runtime contracts, Fleet shell, desktop shell, or inventory schema shape.
- Runtime bridge **consumes** existing contracts.
- No Fleet API behavior, outbox-to-central, or ingestion worker.

## Non-goals respected

No new OEMs, scrapers, discount detection, schema redesign, central store, search, desktop integration, Tailscale, or backup automation.

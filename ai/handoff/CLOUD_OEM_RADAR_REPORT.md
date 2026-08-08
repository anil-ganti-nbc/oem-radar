```yaml
project: oem-radar
stage: cloud-migration-phase-1 (Tier C: portability + investigation only)
baseline_commit: 6805c0c
branch: cloud/oem-portability
target_environment: Linux AMD64 Docker (host TBD; no cloud host provisioned)
image_digest: sha256:68dc23f210ccd1fcc45821f35126d3aff9fce52e3623e8f7b61b476d0a1b2bc0 (local test tag, not pushed anywhere)
release_channel: experimental
operational_state: degraded-until-first-run (truthful: no run history on a fresh volume reports "degraded", not "healthy")
docker_build_verified: true
container_contracts_verified: true
persistent_state_verified: true
scheduler_verified: false
notifications_verified: false
backup_verified: true
restore_verified: true
tests_passed: 502
tests_failed: 0
contracts_changed: false
schema_changed: false
architecture_deviations: none
known_product_defects: Dell engine got a live HTTP 403 during testing (pre-existing, unrelated to migration, not investigated further here)
known_portability_defects: none found in this phase (WAL-backup issue was fixed, see DECISIONS.md)
review_required: true
```

## Scope discipline

Per Tier C policy, this phase does NOT claim production readiness, does NOT change
collector semantics, does NOT add OEMs, and does NOT redesign the database. It
covers exactly what's allowed: preserve/rebuild the Linux Dockerfile and Compose
pattern, verify build/contracts in a real image, and investigate the Shopify defect
under the brief's controlled protocol — see `SHOPIFY_INVESTIGATION.md` for that,
kept as its own separate concern from the mechanical portability work.

## What was verified

| Check | Result |
|---|---|
| Existing test suite before/after changes | 502 passed, 0 failed (both times) |
| `docker build --platform linux/amd64` | succeeds |
| Non-root execution | `id`: `uid=10001(clank)` |
| `version`/`identity` in container | truthful; `release_channel: "experimental"` |
| `health` on empty volume | `"degraded"`, honest reason (`database file missing`) |
| `validate` (offline config check) | OK: 28 OEMs, 28 sources, 5 engines |
| Real one-shot run (`--source dell-us-laptops`, isolated volume) | got a live 403 from Dell (pre-existing, unrelated); app handled it gracefully, recorded `failed` status, exit 0 |
| Persistence across container recreation | fresh container, same volume, identical recorded run data |
| Backup (`scripts/backup.py`, new — none existed before) | consistent DB snapshot + raw-evidence tarball |
| Isolated restore (`scripts/restore.py`, new) | `PRAGMA integrity_check` ok, 20 tables intact, verified even from a read-only-mounted source after the WAL fix |
| `docker compose config` | validates; no ports, no socket, `restart: "no"` |

## Explicitly not done (Tier C boundary, not an oversight)

- No production Compose file — only the portability/investigation config exists.
- No new OEMs, no collector semantics changes, no schema changes.
- No cloud-host-dependent verification (external schedule over real time, reboot
  recovery, Tailscale) — same blocker as every other clank in this phase.
- Windows launchers (`start-radar.cmd`, `.vbs`, `install-hourly-task.*`) retained
  unmodified for transitional rollback, per Tier C's allowed scope; the secret fix
  to `start-radar.cmd` (removing the hardcoded webhook) happened in the baseline
  commit, before this phase, and is a hygiene fix, not a behavior change.

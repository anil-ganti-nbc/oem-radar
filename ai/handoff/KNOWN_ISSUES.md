# Known issues — OEM Radar cloud migration

## Found and fixed this phase

**Backup portability quirk (WAL header inheritance).** `sqlite3.Connection.backup()`
copies the source database's header, including its journal-mode flag. Since the live
`radar.db` runs WAL mode, the backup copy inherited that flag too — meaning the backup
file needed write access to its own directory just to be *opened* later (to create
`-wal`/`-shm` companions), even for a pure read. This broke restoring from a read-only
mount. Fixed by checkpointing the destination to `journal_mode=DELETE` right after the
backup completes — affects only the backup copy, never the live database's actual
journal mode or the running application's behavior.

## Investigated, not resolved (see SHOPIFY_INVESTIGATION.md for full detail)

**Shopify collector transport defect** — previously documented as Docker `curl`
succeeding (200) while Python `requests` failed (429 `local_rate_limited`) inside
Linux Docker. Did **not** reproduce in this session: 4/4 requests succeeded (bare
curl, bare Python `requests`, and the real app's fetcher against both Aoostar and
Beelink) with zero errors. This is meaningful evidence against a universal
"Linux Python HTTP stack" root cause, but is not proof the issue is resolved — the
original evidence came from a different host, and Cloudflare-fronted rate limiting is
often IP-reputation-based rather than client-library-based. Classified **Unknown**,
not reclassified as fixed or as a confirmed portability defect. No code changed as a
result. Recommendation: re-run the same protocol from whatever host is actually used
for eventual deployment before trusting Shopify collector health there.

## Pre-existing, documented, not touched

- Dell engine (`dell-us-laptops`) got a live HTTP 403 from `dell.com` during this
  session's persistence test. Not investigated — unrelated collector, out of scope for
  a Shopify-focused Tier C investigation, and not required to prove the portability
  work (a failed-but-gracefully-recorded run was sufficient evidence of correct
  DB/status handling).
- Two Windows Task Scheduler code paths exist historically for this app
  (`install-hourly-task.ps1`/`.cmd` + `crawl-silent.vbs`) — unaffected by the
  container path, not consolidated here.
- Prior stale portability snapshot at `unified/oem-radar` was never Docker-verified
  (host had no Docker installed) — this phase supersedes it with real verification on
  the live repository, adapted rather than copied.

## Deferred (needs a cloud host, not yet approved)

External scheduler over real time, host reboot recovery, notification delivery from
the real target network, Tailscale/private access — same as every other clank in this
phase.

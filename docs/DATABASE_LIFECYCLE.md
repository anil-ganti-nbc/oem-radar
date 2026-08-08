# Database Lifecycle

**Written 2026-08-08, during the Epoch 1 → Epoch 2 cutover.** This
document is the procedure, not a one-time report — `docs/SOAK_ARCHIVE_
2026-08.md` is the report for this specific cutover. Read this when you
need to do the same thing again: archive a database that has
accumulated development/soak history and start clean, without losing
anything.

## Why this exists

`data/radar.db` is a single SQLite file (ADR-1: single writer, WAL
mode). Development, feature verification, and architecture experiments
all write through the exact same code path as production crawling —
there is no separate "test mode" database. That is a deliberate
simplicity tradeoff (`docs/ARCHITECTURE.md`), and it means the live
database can accumulate real soak history that was never a deliberate
production run. When that happens, the fix is not to delete the
history — it is evidence of how the system behaves under real load —
but to **separate** it from what counts as production going forward.

## Production epochs

- **Epoch 1** — development + accidental soak. Everything from the
  project's first crawl through 2026-08-08. Archived, read-only,
  documented in `docs/SOAK_ARCHIVE_2026-08.md`.
- **Epoch 2** — clean production baseline, starting 2026-08-08. The
  live `data/radar.db` from this point forward.

This is documentation-only bookkeeping — there is no `epoch` column
anywhere in the schema. The epoch boundary *is* "which file is
currently at `data/radar.db`," recorded in this doc and in each
archive's `MANIFEST.json`.

## The procedure

Never destroy the only copy of the old data. Sequence, in order,
each step gated on the previous one succeeding:

### 1. Stop writers

Confirm nothing is currently writing to the live database before
touching it:

- No lock file at `run_lock_path` (`data/oem-radar.lock` by default) —
  its presence means a crawl is in flight; wait for it or investigate
  before proceeding.
- No `crawler_runs` row at `status='running'`. A row stuck here across
  a process restart is an orphan, not an active crawl — correct it
  (see "Correcting an orphaned run" below) before archiving, so the
  archive doesn't preserve a permanently-stuck row.
- No dashboard `.exe` or `oem-radar dashboard` process holding the DB —
  check for a listener on the dashboard port (`8787` by default).
- No OS-level scheduled task about to fire during the window. Check
  with `Get-ScheduledTask` (Windows) — if this project has no
  registered task, say so explicitly rather than assuming one exists.

### 2. Integrity check

Read-only, against the live file, via `providers.sqlite.connect_
readonly` — never open the live file read-write just to check it:

```python
from oem_radar.providers.sqlite import connect_readonly
conn = connect_readonly("data/radar.db")
assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
```

Also record: `schema_migrations` max version, full table list, row
count per table, file size (plus `-wal`/`-shm` sidecar sizes — a
non-empty `-wal` means uncommitted data the raw file alone wouldn't
capture), the most recent `crawler_runs` row (any status), and the most
recent `status='ok'` row.

**If integrity_check fails or foreign_key_check returns violations:
stop.** Do not proceed to archival or reset. Diagnose the corruption
first — an archive of a corrupt database is not a safety net, and a
reset on top of unexplained corruption may just reproduce it.

### 3. Create the archive

```python
import sqlite3
src = sqlite3.connect("file:data/radar.db?mode=ro", uri=True)
dst = sqlite3.connect(f"data/archive/soak-<epoch-date>/radar-soak-<date>.db")
src.backup(dst)   # page-level, WAL-consistent — not a raw file copy
dst.execute("PRAGMA journal_mode=DELETE")
dst.execute("PRAGMA wal_checkpoint(TRUNCATE)")
dst.commit()
dst.close()
```

Use `Connection.backup()`, not a filesystem copy. A raw copy of a
WAL-mode database taken while sidecar files exist can capture an
inconsistent snapshot; `backup()` cannot. Switching the destination to
`journal_mode=DELETE` afterward keeps the archive a single
self-contained file with no live `-wal`/`-shm` siblings next to it —
appropriate for something meant to never be opened read-write again.

Compute a SHA-256 of the final archived file and write it, alongside
schema version, row counts, and the integrity result, into a
`MANIFEST.json` next to it. Write a `SUMMARY.md` narrating what the
archived data actually contains — link to existing stage docs rather
than re-deriving numbers they already report. Mark every file in the
archive directory read-only at the filesystem level as a last line of
defense against accidental writes.

### 4. Verify the archive

Before touching the live file:

- Reopen the archived file via `connect_readonly` and re-run
  `PRAGMA integrity_check` / `foreign_key_check`.
- Recompute the SHA-256 and confirm it matches the manifest.
- Confirm every table's row count matches the manifest exactly.
- Run representative queries through the **real application code** —
  `dashboard.data.collect()`, `collect_alert_detail()`,
  `collect_evidence_detail()` — not hand-rolled SQL, so you're
  verifying what the app will actually see if this archive is ever
  restored.
- Confirm `SqliteStore.migrate()` is a true no-op against this schema
  version: copy the archive to a **disposable scratch location**
  first (never open the real archive file read-write), open the copy
  through `SqliteStore`, and confirm `schema_migrations` gains no new
  rows. The scratch copy's raw bytes will differ after this (SQLite
  rewrites its header/change-counter on `PRAGMA journal_mode=WAL` and
  `commit()` even with zero migrations applied) — that's expected and
  not a sign of mutation; what matters is the row counts and schema
  version, not byte-identity of a copy you're about to discard.

### 5. Optional compact exports

Only ones that are genuinely useful without SQLite in hand — SQLite
remains authoritative. Past precedent: `collector_health_history.csv`
(one row per `crawler_runs` entry with decoded health status),
`change_event_summary.csv` (real counts by manufacturer × change_type ×
severity, joined off `product_key`'s `source_key:external_id`
convention — `change_events` has no dedicated manufacturer column),
`review_summary.json`. Skip anything that would just restate
`MANIFEST.json`.

### 6. Reset

**Move, never delete:**

```bash
mv data/radar.db "data/radar.db.epoch1-pre-reset-<date>"
mv data/radar.db-wal "data/radar.db.epoch1-pre-reset-<date>-wal"  # if present
mv data/radar.db-shm "data/radar.db.epoch1-pre-reset-<date>-shm"  # if present
```

This is deliberately a *second* copy of Epoch 1, independent of the
curated archive from step 3 — cheap insurance, not redundant. Then let
the application create the fresh database itself rather than writing
schema SQL by hand:

```python
from oem_radar.providers.sqlite import SqliteStore
store = SqliteStore("data/radar.db", "data/raw")  # runs schema.sql + all migrations
store.close()
```

Verify: `schema_migrations` max version matches `SCHEMA_VERSION`, the
table list matches the archived one, and every operational table
(`products`, `snapshots`, `change_events`, `evidence_*`, `notifications`,
`crawler_runs`, `alert_reviews`, `rule_suggestions`, `stories`,
`manufacturers`, `sources`, `listings`, `prices`, `aliases`,
`components`) is empty. `schema_migrations` itself is expected to be
non-empty (one row per version) — that is not operational data.

Config, fixtures, and code are untouched by this procedure. Confirm
with `oem-radar validate` / `oem-radar coverage` that the enabled
source/OEM/engine counts match what they were immediately before the
reset — if they don't, something other than the DB reset changed, and
that needs separate investigation.

### 7. Baseline crawl

Run every enabled source once, in batches, checking after each batch
rather than firing all 21+ sources in one call:

1. **Small inline engines** (`category_jsonld`, `dell`) — one source
   each currently, seconds per crawl.
2. **Remaining Shopify + WooCommerce Store API** — bulk-inline, seconds
   per source even at a dozen-plus sources.
3. **`sitemap_jsonld`** — per-page-fetch, minutes to over an hour per
   source depending on catalog size (Medion's ~692-product catalog is
   the long pole at ~69 minutes measured in `docs/COLLECTOR_ECONOMICS.md`).
   Run these individually, in the background if a single source would
   exceed your tool's timeout — never run two crawls concurrently
   against the same database; `RunLock` will refuse the second one
   anyway.
4. **Anything else enabled but not covered above** — call out
   explicitly if there is nothing in this category; don't invent a
   batch to match a template.

After each batch, confirm via a read-only query: `crawler_runs` status
per source, `products`/`snapshots` growth, and — the one that actually
matters — **`notifications` has zero `sent` rows and only `pending` or
`suppressed`** on a database whose sources have never crawled before.
`baseline_quiet` (`radar.yaml`) suppresses sends on a source's first-
ever successful crawl (`store.has_completed_run(source_key)` is purely
`crawler_runs`-driven, so a fresh DB makes every source's first crawl a
baseline automatically — nothing else needs to change for this to
work). If a sent notification appears during a baseline batch, stop and
find out why before continuing — that is exactly the failure mode this
whole procedure exists to prevent.

### 8. Post-baseline validation

A report: attempted/successful/degraded/failed per source, products
and snapshots stored, initial events, notifications by status,
per-engine runtime. Initial actionable Discord deliveries should be
zero — anything else is a bug in baseline semantics, not a fact to
document and move past.

### 9. Resume monitoring

If a scheduled task exists for this project, confirm it is enabled and
record when it will next fire. If none exists — say so plainly rather
than describing a "pause/resume" that didn't happen. Manual crawls
(the dashboard's "Run collectors now", or `oem-radar run`) remain
available regardless.

**As of the 2026-08-08 Epoch 2 activation, one does exist**: the "OEM
Radar Hourly Crawl" Windows Scheduled Task, registered via
`install-hourly-task.cmd` → `install-hourly-task.ps1`. Registration
does **not** go through `schtasks.exe /tr` — a real, reproducible bug
was found doing this cutover and is worth knowing about if this
project's folder is ever moved or renamed: `schtasks /tr` takes one
combined "program + arguments" string, and for a path containing a
space (this project's does — `oem-radar v 2.0`), every way of quoting
that value either got mis-split into the wrong `Execute`/`Arguments`
(Task Scheduler then tries to run `...\oem-radar` as the program) or
stored literal quote characters inside `Execute`, which silently
no-ops instead of running the script. `schtasks` reports `SUCCESS`
either way — the failure is only visible by inspecting the registered
`Action` afterward (`(Get-ScheduledTask -TaskName "...").Actions`).
`install-hourly-task.ps1` uses `Register-ScheduledTask` with `Execute`
and `Argument` as separate, unambiguous parameters instead, which
sidesteps the whole class of bug. Verified end-to-end: a manual trigger
correctly used the Epoch 2 database, acquired and released `RunLock`,
skipped every source still within its `min_interval`, and isolated
`dell-us-laptops`'s known failure without aborting the run. If this
project is ever moved to a path *without* a space, `schtasks /tr` would
likely have worked fine — the bug is specific to this repo's own
folder name, not a defect in Windows Task Scheduler generally.

## Restore procedure (rollback)

If Epoch 2 needs to be rolled back — a baseline crawl went wrong, or a
regression is discovered before Epoch 2 has accumulated anything worth
keeping:

```bash
# 1. Stop writers (same checks as step 1 above)
# 2. Move the Epoch 2 database aside — don't delete it either
mv data/radar.db "data/radar.db.epoch2-aborted-<date>"
mv data/radar.db-wal "data/radar.db.epoch2-aborted-<date>-wal"  # if present
mv data/radar.db-shm "data/radar.db.epoch2-aborted-<date>-shm"  # if present

# 3. Restore the archived Epoch 1 database
cp data/archive/soak-<epoch-date>/radar-soak-<date>.db data/radar.db

# 4. Verify
python -c "
from oem_radar.providers.sqlite import connect_readonly
conn = connect_readonly('data/radar.db')
assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
print('schema_migrations max:', conn.execute('select max(version) from schema_migrations').fetchone()[0])
"

# 5. Restart the dashboard / resume scheduling as normal
```

The restored file is a plain copy of the immutable archive — the
archive itself is never touched, so this can be repeated as many times
as needed. `SqliteStore` will re-derive WAL mode and any pending
migrations the next time it opens the restored file, exactly as it
would for any other database.

## What this procedure deliberately does not do

- **No automatic epoch cutover.** This is a manual, reasoned decision
  each time, not a scheduled maintenance job. A database accumulating
  real production history is the intended long-term state — this
  procedure is for the specific situation where the accumulated history
  is soak/development noise, not steady-state signal.
- **No truncation of tables in place.** Every step either copies
  (archival) or moves (reset) — never `DELETE FROM` against the live
  file. A partially-applied truncation is much harder to reason about
  than a file that either exists whole or has been moved aside whole.
- **No migration of reviews, rule suggestions, or evidence into the new
  epoch.** These are editorial/experimental state tied to the specific
  data they were produced against; carrying them forward would make
  them describe products/events that may not exist in the new epoch.

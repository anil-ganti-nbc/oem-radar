# Soak Archive 2026-08 — pointer

**Written 2026-08-08.** This is the short, discoverable pointer.
The full narrative and machine-readable manifest live with the archive
itself, not in `docs/`, per `docs/DATABASE_LIFECYCLE.md`'s own rule
that SQLite (and its accompanying manifest) stays authoritative:

- **`data/archive/soak-2026-08/SUMMARY.md`** — full narrative: what the
  archived database contains, every real bug and finding it produced,
  and what was deliberately not carried into Epoch 2.
- **`data/archive/soak-2026-08/MANIFEST.json`** — checksum, schema
  version, row counts, integrity result, cutover reason.
- **`data/archive/soak-2026-08/radar-soak-2026-08-08.db`** — the
  archived database itself. Read-only, filesystem-marked read-only,
  checksum `ca10117f77dabc27830b8f9441acabd4b48403561f8360706d0d02be69f3579d`.
- **`data/archive/soak-2026-08/collector_health_history.csv`**,
  **`change_event_summary.csv`**, **`review_summary.json`** — compact
  exports for anyone who wants the data without opening SQLite.

## The one-paragraph version

`data/radar.db` accumulated 11 development stages' worth of manual and
feature-verification crawls (2026-08-02 through 2026-08-08) — including
a full Evidence Fusion experiment (1,544 Lenovo PSREF items) and, most
recently, a Stage 11.2 dashboard-crawl-trigger verification that really
notified Discord (9 of the archive's 13 `sent` notifications). None of
this was a deliberate production run — no scheduled task for this
project has ever existed on this machine, so every one of the archive's
59 `crawler_runs` rows is manual. This archive preserves that history
intact, read-only, checksummed. Production restarted from a clean
database (Epoch 2) on 2026-08-08 — see `docs/CURRENT_STATUS.md` for the
current snapshot and `docs/DATABASE_LIFECYCLE.md` for the procedure and
its rollback path.

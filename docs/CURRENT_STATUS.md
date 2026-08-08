# CURRENT_STATUS.md — live pickup document

Read this first. `docs/archive/HANDOFF_2026-07.md` (moved there Stage 10;
was `docs/HANDOFF.md`) is stale (dated 2026-07-19/22/23, predates the
feedback system entirely) — treat it as historical background only, not
current state. This file supersedes it; update it at meaningful checkpoints
instead of rewriting the archived HANDOFF doc.

## Snapshot (2026-08-08, Epoch 2 production activation) — current

- **Tests: 502 passed, 0 failed** (up from 491). Schema unchanged at v7.
- **Baseline events no longer masquerade as fresh alerts.** Root cause:
  `core/pipeline.py::run_source` already tagged every first-crawl event
  with `meta["baseline"]=True` and always had, but nothing downstream
  ever read that tag — the dashboard's default "All changes" view, its
  summary counters, and `core.feedback_analytics`'s signal/noise metrics
  all counted baseline events as ordinary alerts. On the real Epoch 2
  database this put all 1,875 baseline records in front of the first
  genuine alert. Fixed with one shared predicate
  (`core.models.EXCLUDE_BASELINE_EVENTS_SQL`), reused by
  `dashboard.data` and `core.feedback_analytics` — same discipline as
  Stage 11.1's evidence/product split. Baseline events are **not**
  hidden: `summary.baseline_events` reports the real count, and
  `GET /api/baseline-events` lists them for diagnostics. Confirmed
  against the real Epoch 2 DB (read-only, no re-baseline): default view
  now correctly shows 0 events, `baseline_events: 1875`.
- **The OEM Radar Hourly Crawl scheduled task is now registered and
  verified.** A real, reproducible bug was found and fixed along the
  way: `install-hourly-task.cmd`'s `schtasks /tr` call cannot be quoted
  correctly once the project path contains a space (`"oem-radar v
  2.0"`) — every quoting variant either mis-split the value into the
  wrong Execute/Arguments or stored literal quote characters inside
  Execute, which silently no-ops instead of running the script
  (`schtasks` reports success either way). Fixed by switching
  registration to `install-hourly-task.ps1`
  (`Register-ScheduledTask` with `Execute`/`Argument` as separate
  fields — no string to re-quote). A second, unrelated bug (an
  unescaped `)` breaking the batch file's own `if(...)` block, causing
  it to print both the success and failure branches on a real success)
  was found and fixed in the same file.
- **Manually triggered once, verified end-to-end against the real
  Epoch 2 database**: run lock acquired and released cleanly
  (`data/oem-radar.lock`, pid recorded then removed), 20 of 21 sources
  correctly skipped as not-due (`crawled within min_interval` —
  confirms an hourly OS trigger does **not** mean hourly Medion
  crawls), `dell-us-laptops` attempted and failed on the same known
  `HTTP 403` without aborting the run, `data/crawl-runs.log` grew with
  a clean record, exactly one new `crawler_runs` row (the Dell
  attempt), zero notifications sent, zero baseline storm, zero outbox
  replay. Full detail and the exact registered task configuration:
  `docs/DATABASE_LIFECYCLE.md`.
- **`OEM Radar Dashboard.exe` rebuilt** with the baseline-event fix and
  smoke-tested against the real Epoch 2 database (its own auto-crawl on
  launch showed the identical skip/Dell-retry pattern as the scheduled
  task — same code path, same result).
- **`data/radar.db.pre-stage11_1-backup` inspected, found fully
  redundant** against the Epoch 1 soak archive (every table's row count
  is a strict subset; the schema-v6→v7 evidence migration this backup
  predates is already reflected in the archive). Recommended for
  deletion; not deleted — awaiting owner approval.

## Snapshot (2026-08-08, Epoch 2 cutover) — historical

- **Tests: 491 passed, 0 failed** (up from 479). **Schema version: 7,
  unchanged** — this is a data-lifecycle operation, not a schema change.
- **`data/radar.db` was reset. Everything before this point is now
  Epoch 1 — archived, not deleted.** The live database had accumulated
  11 development stages of manual and feature-verification crawls
  (2026-08-02 through 2026-08-08), including the full Evidence Fusion
  experiment and a Stage 11.2 verification crawl that really notified
  Discord. None of it was a deliberate production run — no OEM Radar
  scheduled task has ever existed on this machine. Full procedure:
  `docs/DATABASE_LIFECYCLE.md`. Full soak record: `docs/SOAK_ARCHIVE_
  2026-08.md` → `data/archive/soak-2026-08/`.
- **Archived, checksummed, verified, then reset — in that order, never
  reversed.** `sqlite3.Connection.backup()` for a WAL-consistent
  snapshot (not a raw file copy), SHA-256
  `ca10117f77dabc27830b8f9441acabd4b48403561f8360706d0d02be69f3579d`,
  `PRAGMA integrity_check` = `ok` both before and after archival,
  re-verified through the real `dashboard.data.collect()` /
  `collect_alert_detail()` / `collect_evidence_detail()` code paths
  against the archived file. A second independent copy of Epoch 1 was
  also kept at `data/radar.db.epoch1-pre-reset-2026-08-08` (belt and
  suspenders — the curated archive is canonical). The rollback
  procedure was tested end-to-end against a disposable scratch copy.
- **One real orphaned run found and corrected before archiving**:
  `khadas-sitemap` was stuck at `status='running'` from an interrupted
  dashboard-triggered crawl. Corrected via `SqliteStore.run_finished`
  (the real code path, not hand-written SQL) — same pattern as the
  Stage 10 orphan fix.
- **Fresh Epoch 2 baseline, all 21 enabled sources, batched by engine
  cost** (fast bulk-inline first, `sitemap_jsonld` last/backgrounded —
  Medion alone took ~70 min, matching its historical ~69 min almost
  exactly): **20 ok, 1 failed** (`dell-us-laptops`, the same
  pre-existing, documented `HTTP 403` — not a new failure), **0
  degraded**. 728 products, 1,579 snapshots, 1,875 change events, **0
  notifications sent** — all 1,875 correctly `suppressed` by
  `baseline_quiet`, confirming a fresh DB's first-ever crawl per source
  is purely `crawler_runs`-driven and needed no code change to behave
  correctly.
- **New reusable code**: `core/db_lifecycle.py` — `integrity_report()`,
  `verify_archive()`, `assert_all_operational_tables_empty()`. Codifies
  the PRAGMA-level checks this cutover ran by hand, with 12 new tests
  against temp databases only. Deliberately not a full one-shot
  automation script (that's the spec's own "optional" item) — this
  cutover was executed once, by hand, with full rigor; only the
  reusable primitives were worth keeping.
- **Not carried into Epoch 2, per instruction**: `alert_reviews` (was
  already empty — no alert has ever been reviewed), `rule_suggestions`
  (also empty), all 1,544 Evidence Fusion items/events/links, the
  notification outbox. Config (`config/oems/*.yaml`, `config/radar.yaml`),
  fixtures, and code are unchanged — confirmed via `oem-radar validate`/
  `coverage` matching pre-reset numbers exactly (28 OEM descriptors, 21
  enabled sources, 5 engines).
- **Operational finding, unresolved**: still no OEM Radar scheduled
  task registered on this machine (confirmed again during this cutover
  — the one task present, `SignalRadar`, belongs to an unrelated
  project). Every crawl to date, across both epochs, has been manual.

## Snapshot (2026-08-08, post-Stage-11.2) — historical

- **Tests: 479 passed, 0 failed** (up from 444). **Schema version: 7,
  unchanged** — Stage 11.2 touches no tables. Collectors unchanged at 21.
- **The dashboard can now crawl.** It auto-starts a crawl in the
  background when you open it (both `oem-radar dashboard` and the `.exe`)
  and exposes a "Run collectors now" / "Force re-crawl all" bar with live
  per-source progress. Full writeup: `docs/STAGE11_2.md`.
- **This ends the dashboard's read-only property.** It now reaches the
  network and can send Discord notifications, because it runs the *same*
  crawl `oem-radar run` does. Turn it off with
  `dashboard.auto_crawl_on_start: false` in `config/radar.yaml`, or
  `oem-radar dashboard --no-crawl`.
- **Auto-crawl does not force.** Each source's `min_interval` still
  decides, so opening the dashboard repeatedly costs nothing. Pinned by a
  test, because it is the assumption that makes auto-crawl safe.
- **One crawl code path:** `core/crawl_service.py::execute_crawl` is
  called by both `cli.cmd_run` and the dashboard's `CrawlController`.
  Tests assert `cmd_run` no longer calls `run_all` directly and that
  `cli._build_fetcher is crawl_service.build_fetcher`.
- **Two bugs fixed on the way:** the `.exe` never registered the engine
  modules (only `cli.py` did), so a browser-triggered crawl would have
  failed on its first source; and the `.exe` now `chdir`s to the project
  root so its lock file and HTTP cache land where the scheduled crawl's do.
- **Operational finding, not fixed here:** the hourly scheduled task had
  not fired since 2026-08-07 ~18:00. The manual trigger is a workaround;
  `install-hourly-task.cmd`'s registration is worth checking separately.

## Snapshot (2026-08-08, post-Stage-11.1) — historical

- **Tests: 444 passed, 0 failed** (up from 419). **Schema version: 7.**
- **Stage 11.1 was a regression fix, not a feature stage.** Collectors
  unchanged at 21 / 5 engines. Full writeup: `docs/STAGE11_1.md`.
- **Evidence no longer occupies the product-alert stream.** Stage 11
  wrote a `change_events` row per evidence observation; on the real DB
  that was 1,544 of 3,465 rows (44.6%), all unopenable, all newer than
  every real product change, so they filled 300 of 300 visible slots and
  buried the hardware feed. Schema v7 adds `evidence_events` and the
  migration **moves** (does not delete) those rows out of
  `change_events`. Verified on a copy first, then applied; backup at
  `data/radar.db.pre-stage11_1-backup`. Real DB now: 1,921 product
  alerts, 1,544 evidence events, notifications untouched.
- **The OEM filter is complete for the first time.** `manufacturers` was
  a side effect of crawling, not a registry, so 3 of 28 configured OEMs
  (Star Labs, Trigkey, VAIO) never existed in the DB. One writer
  (`core.runner.sync_oem_registry`, called by `run_all` and by both
  dashboard entry points), one reader
  (`dashboard.data.collect_oem_registry`), one JS accessor
  (`oemRegistry()`). Real DB now shows **28/28**.
- **Evidence is a first-class entity in the UI**: top-level tab with its
  own filters, plus `GET /evidence/{id}` and `/api/evidence/{id}` —
  provenance, source, kind, timestamps, linked products, raw identifiers,
  raw payload. No review form (evidence is not rated HIT/NOISE, and
  `upsert_review()` on an evidence id raises).
- **Still inert by design:** evidence sources are not wired into
  `oem-radar run` and deliver nothing to Discord. Stage 12's blocking
  question is *what promotes an evidence observation into a product
  signal* — see `docs/STAGE11_1.md`.

## Snapshot (2026-08-08, post-Stage-11) — historical

- **Tests:** 419 passed, 0 failed (up from 383). **Schema version: 6**
  (was 5) — additive migration for Evidence Fusion v0.1, see below.
- **Collectors unchanged: still 21 sources / 5 engines.** `EvidenceSource`
  is a new, parallel subsystem, not a 6th engine — see
  `docs/EVIDENCE_ARCHITECTURE.md`.
- **`EvidenceSource` built and proven, after the Stage-10-set trigger
  fired for real.** Stage 11 found HP has the same architectural shape as
  Lenovo PSREF (a real, enumerable, official product-category API,
  `docs/ALTERNATE_SOURCE_MATRIX.md`), satisfying the 2-OEM trigger. Built:
  `EvidenceItem`/`EvidenceKind`/`EvidenceProvenance` models, the
  `EvidenceSource` protocol, schema v6 (`evidence_items`/
  `evidence_links`), a separate small pipeline
  (`core/evidence_pipeline.py`), and the first real implementation
  (`evidence_sources/lenovo_psref/`). Run once against live
  `psref.lenovo.com`: **1,544 real evidence items and events persisted**
  into `data/radar.db`, all correctly unlinked (no tracked Lenovo
  storefront products to correlate against); a repeat run produced zero
  new events, proving dedup against real data. See
  `docs/EVIDENCE_ARCHITECTURE.md` for what was deliberately NOT built
  (CLI wiring, Discord delivery, a second real implementation for HP) and
  why.
- **A real identity bug caught before shipping**: evidence identity
  correlation's first draft compared against `products.canonical_model`
  (a coarse key) and would have linked "ThinkPad X1 Carbon Gen 12" and
  "ThinkPad X1 Yoga Gen 9" as the same product — the same class of bug
  Stage 8 found in `resolve_prior` itself. Caught by this stage's own
  test suite, fixed before merge.
- **PSREF's per-product spec/MTM endpoint remains unresolved** — 9 real
  endpoint-name guesses against a real ProductID, all 404. Added to
  `docs/OWNER_PROBE_BACKLOG.md`'s new DevTools section alongside ASUS —
  both `PENDING_OWNER_ACTION`, no further automated probing planned.
- **Production soak analysis, all 5 engines, real data**
  (`docs/COLLECTOR_ECONOMICS.md`): shopify's real event distribution is
  10-of-23 runs producing **zero** new events — first real proof a mature
  source goes quiet at steady state. Other engines' sample sizes (1-4 real
  runs) are explicitly too small for a p95, stated as a gap, not
  estimated.
- **Medion's ~69-minute crawl investigated, no optimization made**:
  conditional GET is already implemented and active, but only 28.6% of
  cached `sitemap_jsonld` responses carry a real `ETag` — the cost is
  structural (692 real pages), not a caching bug. Documented, nothing
  changed, per this stage's own "if it already works, do nothing" rule.
- **Dashboard**: new read-only "Evidence" tab (manufacturer/kind/
  provenance/model/observed/linked-product/source link). No redesign.

## Snapshot (2026-08-07, post-Stage-10)

- **Tests:** 383 passed, 0 failed (up from 370).
- **Collectors unchanged**: still 21 sources / 27 configured OEMs / 5
  engines. `EvidenceSource` was investigated and **not built** — the
  evidence bar (2 OEMs, or 1 OEM + 3 evidence types) wasn't met. See
  `docs/STAGE10.md`.
- **All 5 engines now have real production run history.**
  `sitemap_jsonld`, `woocommerce_store_api`, and `category_jsonld` were
  run for real (Samsung, Khadas, LG, Medion, SimplyNUC, GEEKOM,
  NovaCustom, Pine64) — all 8 succeeded. Real, measured finding:
  bulk-inline engines finish in seconds; `sitemap_jsonld` costs real
  per-domain-rate-limited minutes proportional to catalog size (Medion's
  692-product catalog took ~69 minutes for one crawl). See
  `docs/COLLECTOR_ECONOMICS.md`.
- **Axiomtek rejected, decisively.** A reproducible 31-page stratified
  sample (up from Stage 8's 8) found JSON-LD on 4 pages (12.9%, matching
  Stage 8's 12.5% almost exactly) — confirms a real, stable ~13% ceiling,
  not sampling noise. Parked with strong evidence, no bespoke parser
  written. See `docs/AXIOMTEK_WIDE_SAMPLE.md`.
- **New alternate-evidence lead: Lenovo PSREF.** `psref.lenovo.com`
  exposes a real, unauthenticated JSON API (found via reading its own
  published JS bundle text, not executing it) returning 1,544 real
  products with stable identifiers — completely outside the blocked
  storefront, no policy exception needed. One OEM, one evidence type —
  short of the pre-committed `EvidenceSource` trigger, so nothing was
  built, but it's the most promising unexploited lead in the project. See
  `docs/ALTERNATE_SOURCE_RECON.md`.
- **ASUS**: `docs/OWNER_DEVTOOLS_GUIDE.md` and `oem-radar sanitize-har`
  built and ready, but no actual owner DevTools capture has been
  performed yet — deliberately kept human-driven rather than automated
  via this project's own browser tooling. ASUS remains `BLOCKED_JS` with
  the same evidence as before.
- **New: `OEM Radar Dashboard.exe`** (project root) — a standalone,
  double-click dashboard launcher built with PyInstaller
  (`launch_dashboard.py` + `build_dashboard_exe.cmd`), no separate Python
  install required.
- **Real dashboard bug found and fixed**: the OEM filter dropdown was
  scoped to the visible (LIMIT-bounded) recent-events window instead of
  the full manufacturer list — invisible until Stage 10's own bulk
  baseline runs flooded that window with just two OEMs' events. Fixed in
  `dashboard/render.py`; regression test added.
- **`docs/HANDOFF.md` archived** to `docs/archive/HANDOFF_2026-07.md`.
  Gzip-sitemap support investigated and left deferred (no real candidate
  needs it — the one OEM ever cited, Dynabook, is blocked by stale
  content, not compression). Owner-probe backlog consolidated into
  `docs/OWNER_PROBE_BACKLOG.md`.

## Snapshot (2026-08-07, post-Stage-9) — historical, see above for current

- **Tests:** 370 passed, 0 failed (up from 349).
- **Collectors unchanged on purpose:** still 21 sources / 27 configured
  OEMs / 5 engines. Stage 9's mandate was the decision layer, not
  collector count — see `docs/STAGE9.md` and `docs/STAGE10_PROPOSAL.md`.
- **`oem-radar probe` is now a reconnaissance-analyst report**, not a raw
  field dump: confidence (0-100, evidence-tied), plain-language evidence
  lines, known risks, missing information, recommended next step, a 0-100
  **discovery quality score** with itemized deductions, recommended
  fixture count/engineer time, and a should-pursue verdict + reason.
  Editorial value is still deliberately never estimated by the probe —
  see `core/probe.py`. 16 new offline tests
  (`tests/test_probe_stage9.py`).
- **New: `core/benchmark.py`** — a real, repeatable discovery benchmark
  (time/requests/products/duplicates/identity quality/validation pass
  rate) run against one real fixture per engine
  (`tests/test_discovery_benchmark.py`); results regenerate
  `docs/DISCOVERY_BENCHMARKS.md`.
- **New: `docs/COLLECTOR_ECONOMICS.md`** — real per-engine LOC/test/
  fixture counts (all 5 engines) plus real `data/radar.db` runtime signal
  (shopify + dell only — the other three engines have never actually run
  in this environment, a real gap this doc states rather than estimates
  around). Found Dell's 3 real local runs all failed on a real `HTTP 403`
  from dell.com, distinguished from a parsing defect via `run_errors`.
- **Enterprise tier (Lenovo/MSI/ASUS/Acer/HP) re-probed live** and
  classified policy vs. engineering per OEM
  (`docs/ENTERPRISE_OEM_ARCHITECTURE.md` §16). New, more specific finding
  this stage: HP's domain root is a clean 200 with zero bot markers — only
  the catalog path times out, narrowing (not resolving) last stage's
  "whole domain times out" finding.
- **New: `docs/OEM_ATLAS.md`** — consolidates every OEM ever probed
  (Stage 3-9) into one institutional-memory document; supersedes
  `docs/OEM_ECOSYSTEM_MAP.md` as the canonical per-OEM reference.
- **Engine/abstraction audit** (`docs/ENTERPRISE_OEM_ARCHITECTURE.md`
  §17): zero dead code found across `core/*.py` via a direct consumer-
  count sweep. No deletions — the project's existing discipline about
  gating shared code behind a real second consumer already prevented
  speculative-abstraction buildup.
- **`docs/STAGE10_PROPOSAL.md`**: recommends a human devtools pass on
  ASUS (the one Fortune-500 OEM that's reachable-but-JS-hydrated, not
  blocked or silently stalling), a wider Axiomtek sample, and real
  production runs for the three under-measured engines. Explicitly rules
  out a new engine, a discovery plugin system, Playwright, and further
  automated Acer/HP probing.

## Snapshot (2026-08-07, post-Stage-8) — historical, see above for current

- **Tests:** 349 passed, 0 failed.
- **Schema version:** 5, unchanged — Stage 8 found the average-crawl-duration
  metric it needed was already computable from `crawler_runs.started_at`/
  `finished_at` (both already stored), correcting a Stage 7 assumption that a
  new column would be required. No migration added.
- **Enabled collectors: 21 sources across 27 configured OEMs (28
  descriptors), 5 engines.** Run `oem-radar coverage` for the live breakdown.
  - **New this stage: `category_jsonld` engine** — a second "category page
    embeds full product data" shape beyond `dell`'s (see
    `docs/ENTERPRISE_OEM_ARCHITECTURE.md` §9), generalized after Samsung
    became the second confirmed real OEM with that shape. **Samsung is now
    enabled** — real ItemList JSON-LD on `samsung.com/us/computers/
    galaxy-book/`, no sitemap needed, no per-product fetch needed.
  - **Lenovo confirmed compatible with the same engine but deliberately NOT
    enabled** — its `/buy/us/en/<slug>` landing pages return the real data
    only to a browser-spoofed User-Agent; with OEM Radar's actual, honest
    crawler UA they 403. Config/fixtures/tests exist and are kept as a
    documented dead end, not a TODO — see `config/oems/lenovo.yaml`.
  - A real cross-OEM identity bug was found and fixed while validating
    Samsung live: `SqliteStore.resolve_prior`'s coarse `model_key` fallback
    could merge two genuinely different SKUs that share a model_key and
    tier word (e.g. Samsung's "Galaxy Book6 Ultra (64 GB)" vs "...(32 GB)").
    Fixed with a vendor-SKU disagreement guard — see
    `tests/test_sqlite_store.py::test_resolve_prior_distinct_vendor_skus_never_merge`.
  - Everything else from Stage 7 is unchanged: shopify (12), sitemap_jsonld
    (4), woocommerce_store_api (3), dell (1).
- **New docs:** `docs/DISCOVERY_ARCHITECTURE.md` (design review — concludes
  discovery should stay per-engine, not become a first-class plugin system,
  with the specific evidence bar that would change that), `docs/STAGE8.md`,
  `docs/OEM_ECOSYSTEM_MAP.md` (flat planning table, supersedes
  `OEM_PLATFORM_MATRIX.md` as the day-to-day reference).
- **New metrics** (`oem-radar coverage`, `core/metrics.py`): average crawl
  duration (from existing timestamp columns), collector stability, per-engine
  run stability, new/changed-products-per-day, alerts-per-day, false-positive
  rate (alias of the existing `noise_rate`). Metrics with no real backing
  data (probe-attempt success/failure isn't persisted anywhere) are
  correctly omitted rather than fabricated.
- **Phase 3/4/5 recon (Axiomtek, Qotom, BOXX, Velocity Micro, Winmate,
  System76, TUXEDO, Slimbook, Insurgo, Juno, OnLogic, Supermicro, Kontron,
  Portwell, Advantech, Neousys): zero new enables.** Full findings in
  `docs/STAGE8.md` and `docs/OEM_ECOSYSTEM_MAP.md` — most are either
  confirmed-not-a-fit (real fetch, zero JSON-LD) or blocked on a wrong/stale
  entry URL a human needs to supply, not a technical gap.

## Snapshot (2026-08-07, post-Stage-7) — historical, see above for current

- **Tests:** 316 passed, 0 failed. Not a git repo — no history/diff
  available; this is a from-source audit, not a diff review.
- **Schema version:** 5 (`SCHEMA_VERSION` in
  [`src/oem_radar/providers/sqlite/__init__.py`](../src/oem_radar/providers/sqlite/__init__.py)).
  Migrations are numbered functions run in sequence on open, not separate
  files.
- **Enabled collectors: 20 sources across 12 OEMs' worth of new additions
  this stage** (26 descriptor files total, 6 still disabled). Run
  `oem-radar coverage` for the live, always-current breakdown — see Phase 6
  below; the numbers here will drift as more OEMs are added, that command
  won't.
  - **shopify (12)**: acemagic, aoostar, beelink, bosgame, chuwi, gmktec,
    kamrui, minisforum, morefine, nipogi, vaio, **starlabs (new Stage 7)**.
  - **sitemap_jsonld (4)**: khadas, simplynuc (Stage 6), **medion, lg
    (new Stage 7)**.
  - **woocommerce_store_api (3, new engine this stage)**: **geekom,
    novacustom, pine64**.
  - **dell (1)**: dell.
- **Disabled/audited:** ayaneo, firebat, gpd, kingnovy, peladn, trigkey.
  Full per-source breakdown and a much larger recon backlog (mainstream
  brands, industrial/workstation WooCommerce candidates) in
  `docs/STAGE7.md`, `docs/STAGE6_RECON.md`, and `docs/OEM_PLATFORM_MATRIX.md`.
- **Engines: `shopify`, `dell`, `sitemap_jsonld`, and
  `woocommerce_store_api` (new, Stage 7)** — built after 3 independently
  confirmed real candidates (GEEKOM, NovaCustom, Pine64). Full architecture
  blueprint: `docs/ENTERPRISE_OEM_ARCHITECTURE.md`. Engine internals were
  also consolidated this stage — see Phase 5 in `docs/STAGE7.md` — via a
  new `core/textutil.py` shared by all four engines.
- **New CLI**: `oem-radar coverage [--json]` — platform-wide metrics
  (coverage, fixture coverage, health, signals). `oem-radar probe` gained
  framework/GraphQL/Magento/Adobe-Commerce/Salesforce-Commerce detection,
  a JSON-LD richness score, and technical (not editorial) engine/effort
  recommendations — see `docs/STAGE7.md` Phase 4.

## Architecture map

- `core/`: `config.py` (Pydantic models incl. `CollectorHealthConfig`),
  `fetch.py`, `diff.py`, `pipeline.py` (`run_source`, `SourceRunStats` with
  `.health`/`.health_reason`), `runner.py` (`run_all`), `story.py`,
  `feedback.py` + `feedback_analytics.py` + `feedback_analyze.py` /
  `feedback_simulate.py`, `run_lock.py`, `probe.py` (reconnaissance),
  `jsonld.py` (shared JSON-LD walker), `textutil.py` (shared
  `strip_html`/`contains_any`/`parse_schema_availability`, Stage 7),
  `metrics.py` (platform-wide stats, Stage 7).
- `engines/shopify`, `engines/dell`, `engines/sitemap_jsonld` (Stage 6),
  `engines/woocommerce_store_api` (Stage 7).
- `providers/sqlite`: `SqliteStore` + `schema.sql`.
- `providers/discord`: notifier.
- `dashboard/`: stdlib `BaseHTTPRequestHandler` app, no framework.
  - `data.py` — pure read-only SQL queries → JSON-serializable dicts.
  - `render.py` — inline HTML/CSS/JS page templates.
  - `__init__.py` — route dispatch (`_Handler.do_GET`/`do_POST`).
- CLI (`cli.py`): `validate`, `run`, `status`, `coverage` (Stage 7),
  `feedback analyze|simulate`, `dashboard`, `outbox`, `test-notify`,
  `probe`. No `review` subcommand — the web review workflow
  (`/alerts/{id}`) replaced the CLI-review plan noted in the old
  HANDOFF.md.

## Dashboard routes

`/`, `/feedback`, `/alerts/{id}`, `/api/data`, `/api/feedback/metrics`,
`/api/feedback/suggestions`, `/api/feedback/reasons`,
`/api/alerts/{id}/review` (GET+POST), `/api/mark-seen` (POST). All Stage
1–3 feedback plumbing was already wired; it just wasn't linked from the UI
before this checkpoint.

## Feedback / review system

- Outcomes: `HIT`, `INTERESTING`, `NOISE`, `BUG`. `change_events.id` is the
  canonical alert ID.
- `alert_reviews`, `alert_review_history`, `rule_suggestions` tables exist
  and are exercised by `tests/test_feedback_*.py`.
- Rule suggestions are advisory only — `status='PROPOSED'` until a human
  approves; no collector behavior changes automatically.

## Collector health

`SourceRunStats.health` (`ok|degraded|failed`) and `.health_reason`
(`HEALTHY_CATALOG`, `CATALOG_WARN_THRESHOLD`, `CATALOG_FAILURE_THRESHOLD`,
`UNEXPECTED_ZERO`, `NO_PREVIOUS_BASELINE`, `RECOVERED`) are computed per run
in `pipeline.py` and persisted into `crawler_runs.stats_json` by
`runner.run_all`. Now also surfaced in the dashboard (see below).

## Dashboard integration pass (this checkpoint)

Problem: the feedback/review/health backend existed but the main dashboard
didn't link to any of it. Fixed by extending the existing stdlib
architecture — no new frontend framework, no new routes needed beyond what
already existed.

- `dashboard/data.py` — `collect()` now also returns `collector_health`
  (latest health per source, read from `crawler_runs.stats_json`, no
  recomputation) and `feedback_summary` (reuses
  `core.feedback_analytics.compute_summary()` verbatim — metrics are not
  duplicated). `collect_alert_detail()` now returns `prev_id`/`next_id` for
  simple adjacent-alert navigation.
- `dashboard/render.py`:
  - Homepage (`render`): persistent nav (`Overview` / `Alerts` / `Feedback`),
    a "N alerts awaiting review" CTA linking to
    `/?tab=events&review=UNREVIEWED` (client-side deep link, no new route),
    a feedback card, a compact collector-health grid, and an extended stats
    row (active OEMs, alerts, unreviewed/reviewed, HIT/INTERESTING/NOISE/BUG
    counts+rates, signal rate, degraded/failed collector counts, proposed
    suggestion count). Added the missing `#f-rev` review-status filter
    `<select>` (the JS already referenced it but the element didn't exist).
  - `render_review_page`: breadcrumbs (Overview / Alerts / Feedback) +
    simple Prev/Next links using adjacent `change_events.id`.
  - `render_feedback_page`: breadcrumbs, plus an explicit "Analytics" vs
    "Proposed rules" section split.
- Verified live against the real `data/radar.db` (534 alerts, 10 active
  collectors) via the browser — nav, CTA deep-link, alert breadcrumbs, and
  `/feedback` all work end-to-end.
- Tests: `tests/test_dashboard_integration.py` (13 new tests) covering nav
  presence on all three pages, review-status exposure, `/alerts/{id}`
  linking, the unreviewed CTA, homepage metrics matching
  `feedback_analytics` output exactly (not reimplemented), seen-state vs
  review-state independence, HTML escaping on the feedback page, no raw
  `/api/` links in nav, and no frontend-framework dependency introduced.
  Full suite: 185 passed.

## Automation audit

- **Fixed:** `crawl-hourly.cmd` (the unattended Task Scheduler entry point)
  previously ran `pip install --quiet pydantic PyYAML requests` silently on
  a failed import. Scheduled production runs should fail loudly instead of
  mutating the environment in the background — changed it to log a clear
  error to `data/crawl-runs.log` and exit 1.
- **Left as-is (intentional):** `start-radar.cmd` and `dashboard.cmd` still
  auto-pip-install on first run. Both are interactive, double-click
  launchers where the user sees the "installing dependencies..." message —
  different risk profile from the silent hourly task. Not touched.
- `core/run_lock.py`: atomic `O_CREAT|O_EXCL` lock file with PID-liveness
  stale-lock reclaim (Windows via `OpenProcess`, POSIX via `os.kill(pid,0)`);
  conservative (refuses to steal if liveness can't be determined). Looks
  solid; `cmd_run` acquires/releases it correctly around `run_all`.
- `deploy/oem-radar-run.service.example` / `.timer.example` /
  `crontab.example`: sane one-shot examples, no auto-install behavior. Minor
  inconsistency (not fixed, low priority): they assume the package is
  `pip install`-ed, whereas the Windows scripts use `PYTHONPATH=src` without
  an install step — worth reconciling if a Linux deploy is actually attempted.
- Exit-code propagation, working-directory handling (`cd /d "%~dp0"`, which
  correctly handles the "oem-radar v 2.0" space in the current folder name),
  and logging to `data/crawl-runs.log` all look correct as-is.

## Stage 5 — OEM reconnaissance and engine decision (2026-08-07)

Full evidence, per-source classification, and the engine decision matrix
live in **`docs/STAGE5_RECON.md`** — this is a summary.

- Re-probed all 8 previously-disabled descriptors + 13 new OEM candidates
  using an upgraded `oem-radar probe` (now reports redirect chains, Shopify
  `products.json` sampling, live WooCommerce Store API checks, sitemap
  index/product detection, and JSON-LD `Product` node counting — see
  `src/oem_radar/core/probe.py`).
- **Enabled 2 real Shopify sources with zero engine changes:**
  `config/oems/vaio.yaml` (new) and `config/oems/morefine.yaml`
  (`base_url` was stale — `store.morefine.com` never resolved; the real
  storefront is `www.morefine.com`, live and Shopify).
- **GEEKOM's storefront is actually live** (confirmed real WooCommerce
  Store API, 77 products) — the old `BROKEN` audit note was wrong/stale.
  Stays `enabled: false` only because no WooCommerce engine exists yet.
- **Trigkey confirmed genuinely broken**: real Shopify theme, but the store
  itself returns HTTP 402 (suspended/unpaid Shopify store) — not a config
  or engine problem.
- Evaluated a sitemap+JSON-LD engine and a WooCommerce Store API engine;
  neither cleared the "≥3 confirmed worthwhile OEMs" bar (sitemap+JSON-LD:
  1 strong candidate — SimplyNUC — + 1 marginal/noisy one — Medion;
  WooCommerce: 1 confirmed — GEEKOM). Both are designed and documented in
  `docs/STAGE5_RECON.md` Part 5, ready to build once one more OEM confirms.
  Per the stage's own rules, **did not implement either engine** this pass.
- No Playwright/Selenium added. Bot-blocked (Framework, Zotac) and
  likely-JS-SPA (Eluktronics) candidates were left disabled rather than
  reached for browser automation.

## Stage 6 — enterprise OEM reconnaissance and the sitemap_jsonld engine (2026-08-07)

Full evidence in **`docs/STAGE6_RECON.md`** (per-source),
**`docs/OEM_PLATFORM_MATRIX.md`** (ecosystem view), and
**`docs/ENTERPRISE_OEM_ARCHITECTURE.md`** (scaling blueprint) — this is a
summary.

- Probed the full mainstream/enterprise tier (Lenovo, ASUS, HP, Acer, MSI,
  Samsung, LG, Fujitsu) plus the remaining Linux/boutique, gaming, and
  mini-PC candidates from the Stage 6 target list (~19 new domains).
- **Built the `sitemap_jsonld` engine** (`src/oem_radar/engines/sitemap_jsonld/`)
  — sitemap index/leaf recursion, per-page fetch, tolerant JSON-LD
  extraction (shared with `oem-radar probe` via the new
  `src/oem_radar/core/jsonld.py`), case-insensitive offer/availability field
  lookup (a real Khadas/Wix Stores quirk), config-driven URL scoping and
  denylist, no vendor-specific branches. 31 tests
  (`tests/test_sitemap_jsonld_engine.py`).
- **Enabled 2 real sources**: `config/oems/simplynuc.yaml` and
  `config/oems/khadas.yaml`. Real fixtures captured for both
  (`tests/fixtures/sitemap_jsonld/`, provenance recorded).
- Confirmed 2 more real candidates **not yet enabled**: Medion (noisy
  mega-retailer catalog, needs `url_include_pattern` scoping) and LG
  (real identity data, no price in the region checked).
- Confirmed the mainstream enterprise tier (Lenovo/MSI/Origin PC:
  bot-blocked; ASUS/HP/Acer/Samsung: inconclusive, category-page JSON-LD
  only) is **not** a quick win — and explicitly did not reach for
  Playwright, since the "does this vendor's own frontend call a public
  JSON/GraphQL API" question hasn't been investigated yet (see
  `docs/ENTERPRISE_OEM_ARCHITECTURE.md` §15).
- Found and flagged (not fixed) a config gap: Star Labs is a real, live
  Shopify store with real Linux laptops, but its catalog is ~70% spare
  parts that the current denylist doesn't cover — left disabled rather
  than enable with a known noise problem.

## Stage 7 — the platform expansion (2026-08-07)

Full detail in **`docs/STAGE7.md`** — this is a summary.

- Finished the Stage 6 backlog: Star Labs (denylist fix), Medion (URL
  scoping), LG (pricing-enabled US region) all enabled with real fixtures.
- **Built the `woocommerce_store_api` engine** after confirming 3 real
  candidates (GEEKOM, NovaCustom, Pine64) via the probe tool. Enabled all
  three. Found and fixed a real denylist false-positive along the way
  (generic "keyboard" term matched a real Pine64 laptop's regional-variant
  title).
- **Resumed mainstream-OEM recon with actual evidence, not root-page
  guesses**: confirmed Lenovo/MSI block even direct product-page fetches;
  confirmed ASUS ships real data in a Nuxt payload serialized as an
  un-parseable minified JS function call (genuinely requires JS execution,
  not a guess); **confirmed Samsung has real, reachable Product JSON-LD
  with real pricing** on `/buy/` pages — the strongest unclaimed opportunity
  on the table, blocked only on a discovery-strategy investment (no
  sitemap found yet), not on JS rendering. Samsung was deliberately **not**
  enabled this stage — see `docs/STAGE7.md`'s "Architectural decisions."
- **Upgraded `oem-radar probe`** into a fuller reconnaissance assistant:
  framework detection (Next.js/Nuxt), GraphQL/Magento/Adobe-Commerce/
  Salesforce-Commerce hints, sitemap-compression flag, a JSON-LD
  data-completeness score, and technical (explicitly not editorial)
  engine/effort recommendations.
- **Consolidated genuine duplication** across all four engines into
  `core/textutil.py` (`strip_html`, `contains_any`, a shared availability-
  string parser) — deliberately did *not* merge the engines' non-product
  denylist term lists, which stay local and decoupled by design.
- **Added `oem-radar coverage`** — platform-wide metrics (coverage by
  engine, fixture coverage, health, signals), reusing existing analytics
  rather than duplicating metric math. Explicitly reports "not tracked"
  for average run duration rather than fabricating a number.

## Stage 8 — the Fortune 500 offensive (2026-08-07)

Full detail in **`docs/STAGE8.md`** — this is a summary.

- **Samsung enabled.** Its Galaxy Book category page embeds a full, real
  `ItemList` of `Product` nodes (real sku/price/availability) — no sitemap
  needed. Built a new reusable `category_jsonld` engine to parse this shape,
  generalizing the pattern `dell` pioneered (see
  `docs/ENTERPRISE_OEM_ARCHITECTURE.md` §9's own stated trigger: a second
  confirmed OEM with the same shape justifies extraction).
- **Lenovo confirmed compatible with the same engine, deliberately not
  enabled.** Real ItemList data exists on curated `/buy/us/en/<slug>` pages
  — but only when fetched with a browser-spoofed User-Agent; the project's
  actual, honest crawler UA gets HTTP 403 on the identical URL. Enabling
  would require impersonating a browser to defeat Lenovo's bot detection.
  Left disabled on principle.
- **Found and fixed a real, platform-wide identity bug**: `resolve_prior`'s
  coarse `model_key` fallback could merge two different real SKUs sharing a
  model_key and tier word. Discovered live-testing Samsung (two "Galaxy
  Book6 Ultra" configs at different RAM/price), fixed with a vendor-SKU
  disagreement guard, regression-tested.
- **Phase 2-5 recon: zero new enables**, all evidence-backed:
  - Real internal Lenovo APIs found (loyalty points, delivery estimates,
    price-preview) but none are a catalog surface.
  - Axiomtek has real Product JSON-LD, but only on 1 of 8 sampled product
    pages — inconsistent template coverage, below the bar for production.
  - Qotom, BOXX, Velocity Micro, Winmate: real sitemaps and product pages,
    zero JSON-LD — confirmed not a fit for any current engine.
  - System76: real product pages, zero JSON-LD (live price-configurator UI,
    same blind-spot class as ASUS).
  - Several candidates (TUXEDO, Slimbook, Insurgo, Advantech, Neousys,
    Supermicro, Portwell) hit "wrong/stale entry URL" or genuine
    infrastructure issues (broken TLS cert, intermittent 500s, DNS failure)
    — not technical dead ends, just needing a human to supply the right URL.
- **Phase 6**: wrote `docs/DISCOVERY_ARCHITECTURE.md` — concluded discovery
  should stay a per-engine method, not become a first-class plugin system;
  every candidate discovery mechanism this stage either mapped onto one
  already built or wasn't confirmed to exist on any real platform.
- **Phase 7**: extended `oem-radar coverage` with average crawl duration
  (from existing `crawler_runs` timestamp columns — no schema change needed,
  correcting a Stage 7 assumption), collector/engine stability, per-day
  product/alert rates, and a false-positive-rate alias.
- **Phase 8**: wrote `docs/OEM_ECOSYSTEM_MAP.md` — a flat, evidence-graded
  planning table covering every OEM probed through Stage 8.
- **Phase 9**: found and extracted one genuine duplication (`dell` and
  `category_jsonld` both normalized `offers` list-or-dict identically) into
  `core/textutil.py::first_offer` — declined to extract anything else
  (denylists, CPU-extraction regex, discovery mechanics all stayed local,
  per established policy).
- **Phase 10 (scale review)**: see `docs/STAGE8.md` — dashboard queries are
  already `LIMIT`-bounded (don't degrade with OEM count), config loading is
  linear and cheap at current scale, the per-domain serial fetcher remains
  the one real concern flagged since the original `HANDOFF.md` and still
  not urgent at 27 OEMs.

## Unresolved / known technical debt

- `docs/archive/HANDOFF_2026-07.md` (formerly `docs/HANDOFF.md`) is stale
  and was not rewritten — archived Stage 10, kept as historical record.
- ~~Samsung: real, confirmed-reachable Product JSON-LD, no discovery
  mechanism~~ — **resolved Stage 8**: enabled via the new `category_jsonld`
  engine. See `docs/STAGE8.md`.
- Lenovo: real, confirmed-compatible data via the same engine, but blocked
  on a UA-based bot filter the project won't spoof past — see
  `config/oems/lenovo.yaml` and `docs/STAGE8.md`.
- ASUS confirmed to require JS execution for its product data (Nuxt SSR
  payload serialized as a function call, not parseable JSON) — a real,
  evidence-backed blind spot, not a hypothesis.
- Acer/HP remain genuinely inconclusive (timeouts) — not confirmed blocked,
  not confirmed reachable; needs a retry from a different network. Stage 9
  reproduced the identical Acer symptom a third time and narrowed HP's to
  "catalog paths only, root is clean" — see `docs/STAGE9.md` Phase 5.
- **New Stage 9 gap**: `sitemap_jsonld`, `woocommerce_store_api`, and
  `category_jsonld` have zero real rows in `data/radar.db`'s
  `crawler_runs` — strong test/fixture coverage, no real production
  mileage yet. See `docs/COLLECTOR_ECONOMICS.md`.
- No engine handles gzip-compressed sitemaps (seen at Dynabook, Stage 5) —
  not needed by any enabled source yet, deferred.
- A batch of WooCommerce candidates from Stage 7 Phase 2 read as
  network-level failures from this sandbox (Advantech, Neousys, Winmate,
  Portwell, Juno Computers, Insurgo) — genuinely unresolved, not confirmed
  dead ends.
- **Fixed in passing (found via live-smoke-testing the new engine)**:
  `providers/discord/ConsoleNotifier` (used by `oem-radar run --dry-run`)
  printed star-rating characters (★) via a plain `print()`, which raised
  `UnicodeEncodeError` on a Windows console using the default `cp1252`
  codepage — confirmed unrelated to `sitemap_jsonld` itself (would happen
  identically for any engine's dry-run output with enough events, on this
  same console; the pipeline's per-product error isolation caught every
  instance, so no snapshot/event was ever lost — only the console line
  failed to print). Fixed with a small `_safe_print()` helper that falls
  back to `errors="replace"` instead of crashing.
- Deploy examples (Linux) assume an installed package; Windows scripts
  assume `PYTHONPATH=src` — pick one convention if Linux deployment becomes
  real.
- `oem-radar review confirm|split` CLI command mentioned as a gap in the old
  HANDOFF.md was never built — superseded by the web review workflow.
- A large batch of Stage 5/6 owner probes still pending — see
  `docs/STAGE6_RECON.md` and `docs/STAGE5_RECON.md` Part 6 for the specific
  next command per source.

## Immediate next steps

See `docs/STAGE10_PROPOSAL.md` for the full argued case;
`docs/OEM_ATLAS.md` for the flat per-OEM planning table (supersedes
`docs/OEM_ECOSYSTEM_MAP.md`). Concrete next actions, ranked:

1. **A human devtools pass on ASUS** — the one Fortune-500 OEM that's
   reachable and not silently stalling, just client-rendered (Nuxt). No
   automated probe can find a public API call the frontend itself makes;
   a person watching the Network tab for 30 minutes can. Highest expected
   value of any single action currently available.
2. **Re-sample Axiomtek more widely** (20-30 pages, not 8) to settle
   whether its 1-of-8 real-JSON-LD hit rate was an unlucky sample or the
   real ceiling for that catalog.
3. **Run `sitemap_jsonld`/`woocommerce_store_api`/`category_jsonld`
   sources for real** — `docs/COLLECTOR_ECONOMICS.md` found these three
   engines have zero real rows in `data/radar.db`; every future
   economics/benchmark analysis will keep saying "unmeasured" for them
   until this changes.
4. **Get real entry URLs from a human for TUXEDO, Slimbook, Insurgo,
   Supermicro Edge, Advantech, Neousys, Portwell** — confirmed "wrong
   door," not "door is locked."
5. ~~Consider archiving/trimming `docs/HANDOFF.md`~~ — **done Stage 10**,
   moved to `docs/archive/HANDOFF_2026-07.md`.

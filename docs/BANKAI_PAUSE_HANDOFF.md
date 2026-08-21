# BANKAI pause handoff

## Repository and production

- **GitHub head:** `8917b68` on `codex/bankai-config-availability`.
- **Production status:** unchanged. No BANKAI experimental collector is in the
  production source allowlist, product runner, Discord path, or production
  scheduler.
- **Production DB:** `data/radar.db`; SQLite integrity check `ok`, foreign-key
  check clean, migrations `1` through `7` present.
- **Experimental isolation:** the Lenovo and ASUS DBs contain only
  `regional_sitemap_*` tables. They have no `change_events` or notification
  tables; production candidates/events/outbox are therefore unaffected.
- **Last full offline suite:** 529 passed (one pre-existing pytest-cache
  warning).

## Experimental soak

`OEM Radar Experimental Sitemap Soak` is installed locally on Windows, enabled
with a six-hour (`PT6H`) cadence and `IgnoreNew` overlap policy. It invokes the
portable Python wrapper through `scripts/run_experimental_sitemap_soaks.cmd`.
State and telemetry are isolated in `data/experimental/`; every pass appends a
compact record to `soak-runs.jsonl`. The production `OEM Radar Hourly Crawl`
task remains separate and unchanged.

### Lenovo

- **Status:** EXPERIMENTAL / SOAKING.
- **Regions:** US, CA, UK, AU, SG, HK, MY.
- **Baseline:** 6,349 laptop/desktop URLs.
- **Live runs currently retained:** 4 successful runs per region.
- **Deltas / candidates:** 0 / 0.

### ASUS

- **Status:** EXPERIMENTAL / SOAKING.
- **Regions / shards:** Global `global1`, China `cn1`, India `in1` bounded seed
  shards only.
- **Baseline:** 119 product URLs.
- **Live runs currently retained:** 4 successful runs per region.
- **Deltas / candidates:** 0 / 0.

### PSREF, Acer, JD

- **PSREF:** EXPERIMENTAL corroborating evidence only; no alerts or Discord.
- **Acer:** RESEARCH_ONLY. Official robots roots advertise sitemap paths, but
  sitemap/store retrieval repeatedly timed out with the honest user agent.
- **JD:** RESEARCH_ONLY. No unique discovery value beyond official surfaces has
  been demonstrated.

## Golden benchmark

- **Frozen corpus:** [EDITORIAL_BENCHMARK_2026_08.md](EDITORIAL_BENCHMARK_2026_08.md)
- **Qualifying events:** 50.
- **Historical editorial recall:** 0/50.
- **Current-source ceiling:** 6/50.
- **Source/region gap:** 44/50.

**Most important learning:** OEM Radar's dominant editorial-recall problem is
source/region coverage, not the semantic diff engine.

## Resume triggers

Resume development only if one occurs:

1. Lenovo produces a real sitemap delta.
2. ASUS produces a real sitemap delta.
3. Either experimental soak fails repeatedly.
4. Experimental state needs migration because the Windows host is going away.
5. A deliberate decision is made to resume source expansion.

For the first Lenovo/ASUS delta: inspect it, identify the product, classify
`HIT` / `INTERESTING` / `NOISE` / `BUG`, decide whether it is genuinely new or
merely newly indexed, record Radar first-seen, inspect regional/mirror behaviour
and corroborating official evidence, then assess editorial usefulness. Do not
change the collector merely because the first delta appears.

## Deferred priorities — do not start while paused

1. Evaluate real Lenovo/ASUS deltas.
2. Decide whether review-only candidate delivery is justified.
3. Continue Acer official discovery-contract research.
4. Evaluate HP for a cleaner high-yield official source.
5. Revisit JD only if unique discovery value is demonstrated.

## Hetzner migration requirement

The active soak depends on this Windows host and Task Scheduler. Before this
host is retired, migrate the isolated state (`data/experimental/`) and run the
portable command on Hetzner or another Linux host:

```sh
python3 scripts/run_experimental_sitemap_soaks.py
```

No Hetzner deployment was performed. This migration is required to preserve
the experimental baselines and lead-time observation history.

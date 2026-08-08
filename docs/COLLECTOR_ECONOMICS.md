# Collector Economics

**Status: Stage 9 Phase 7 analysis (2026-08-07), updated Stage 10
(2026-08-07) with real production runs for the three previously-unmeasured
engines.** Every number below is either a static repo measurement (lines
of code, test count, fixture count — counted directly, not estimated) or
a query against the real local `data/radar.db`. Where the data doesn't
cover a claim, that gap is stated explicitly rather than filled with a
plausible-looking number — per this project's "never fabricate metrics"
rule.

> **2026-08-08 cutover note**: every "real runtime signal" table below
> describes **Epoch 1**, the database archived (not deleted) during the
> Database Reset & Soak Archive operation — see `docs/DATABASE_LIFECYCLE.md`
> and `docs/SOAK_ARCHIVE_2026-08.md`. The live `data/radar.db` was reset
> the same day and re-baselined; its numbers no longer match this
> document. The static engine-cost table (LOC/tests/fixtures) is
> unaffected — that describes the code, not the database — but every
> table sourced from `crawler_runs`/`change_events` is now historical.
> The Epoch 2 baseline crawl (20/21 sources ok, 0 sent notifications,
> Medion ~70min matching this document's ~69min almost exactly) is
> recorded in `docs/CURRENT_STATUS.md`, not restated here, so this
> document doesn't need re-verification every time the database resets.

## Stage 10 update: the three-engine gap is closed

Stage 9 flagged that `sitemap_jsonld`, `woocommerce_store_api`, and
`category_jsonld` had zero rows in `crawler_runs` — strong test coverage,
no real runtime history. Stage 10 ran one representative source per
engine's real enabled OEMs (SimplyNUC/Khadas/LG/Medion for
`sitemap_jsonld`; GEEKOM/NovaCustom/Pine64 for `woocommerce_store_api`;
Samsung for `category_jsonld`) against the real database, via the normal
`oem-radar run` runner — not dry-run, not synthetic. See "Real runtime
signal, all five engines" below for the numbers. This section's original
caveat (below) is preserved as the honest record of what was true when
Stage 9 wrote it.

## Original caveat on the runtime data (Stage 9, now partially resolved)

`data/radar.db` is this project's real local database, but it was **not**
a mature production fleet history as of Stage 9. It held crawler-run
history for only 10 of the 21 currently-enabled sources (9 `shopify`
OEMs + `dell`), accumulated over three dev-era days (2026-08-02 through
2026-08-04) — almost certainly manual/debugging re-runs during earlier
stages, not a steady scheduled cadence. **Stage 10 confirmed there is
still no scheduled task running this crawler on a cadence anywhere** —
`Get-ScheduledTask` on this machine shows no OEM Radar task registered.
Every row in `crawler_runs`, old and new, is from a manual invocation.
That remains true after Stage 10's runs — Stage 10 added real history,
it did not add a scheduler.

## Engineering cost per engine (static measurement — covers all 5)

| Engine | Implementation LOC | Dedicated tests | Fixture files | Enabled OEMs today | LOC / enabled OEM | Tests / enabled OEM |
|---|---|---|---|---|---|---|
| `shopify` | 322 | 16 (`test_shopify.py` + `test_stage5_shopify_expansion.py`) | 8 | 12 | 27 | 1.3 |
| `dell` | 282 | 8 (`test_dell.py`) | 2 | 1 | 282 | 8.0 |
| `sitemap_jsonld` | 289 | 32 (`test_sitemap_jsonld_engine.py`) | 13 | 4 | 72 | 8.0 |
| `woocommerce_store_api` | 211 | 27 (`test_woocommerce_engine.py`) | 7 | 3 | 70 | 9.0 |
| `category_jsonld` | 230 | 25 (`test_category_jsonld_engine.py`) | 4 | 1 (+1 confirmed-compatible, disabled by policy) | 230 | 25.0 |

Reading this honestly: `LOC / enabled OEM` and `tests / enabled OEM` both
reward **reuse**, not raw engine size — `dell` and `category_jsonld` look
expensive per-OEM only because each currently has one enabled OEM. That
is exactly the shape the project's own architecture predicts (§2 of
`docs/ENTERPRISE_OEM_ARCHITECTURE.md`): those numbers are expected to
fall sharply the moment either engine picks up a second enabled OEM,
because the engine code itself does not grow — only a config file and a
fixture capture would. `shopify`'s 27 LOC/OEM is the concrete proof this
already happens: it is the most reused engine and has by far the best
per-OEM ratio.

## Real runtime signal, all five engines (Stage 10)

| Source | Engine | Status | Duration | Products discovered | Snapshots written | Skipped (non-product) | Events |
|---|---|---|---|---|---|---|---|
| samsung-galaxybook | `category_jsonld` | ok | 0.6s | 12 | 12 | 0 | 12 |
| khadas-sitemap | `sitemap_jsonld` | ok | 477s (~8.0min) | 78 | 49 | 18 | 57 |
| lg-us-gram-sitemap | `sitemap_jsonld` | ok | 1,111s (~18.5min) | 182 | 167 | 0 | 365 |
| medion-gaming-sitemap | `sitemap_jsonld` | ok | 4,143s (~69.1min) | 692 | 692 | 0 | 692 |
| simplynuc-sitemap | `sitemap_jsonld` | ok | 954s (~15.9min) | 137 | 130 | 7 | 130 |
| geekom-wc | `woocommerce_store_api` | ok | 4.9s | 77 | 75 | 2 | 81 |
| novacustom-wc | `woocommerce_store_api` | ok | 22.2s | 275 | 6 | **269** | 6 |
| pine64-wc | `woocommerce_store_api` | ok | 19.8s | 213 | 2 | **211** | 2 |

**Every run in this table is a real first-ever baseline crawl** (`baseline_quiet: true` — real events recorded, zero sent to Discord; this
project's real webhook was deliberately excluded from the config used for
these runs so nothing hit the live channel, per this project's standing
rule against unannounced externally-visible actions). All 8 succeeded.

**The bulk-inline vs. per-page-fetch architecture claim, now verified with
real wall-clock time, not just request counts**: `category_jsonld` and
`woocommerce_store_api` (bulk-inline — discovery IS the data) finished in
under 25 seconds every time. `sitemap_jsonld` (per-page fetch — discovery
finds URLs, then the pipeline fetches every product page individually
under the real per-domain rate limiter) took 8-69 minutes depending on
catalog size, dominated entirely by Medion's 692-page catalog. This is
exactly the tradeoff `docs/ENTERPRISE_OEM_ARCHITECTURE.md` §3 describes
in the abstract — Stage 10 is the first time it's been measured in real
wall-clock minutes rather than asserted.

**NovaCustom and Pine64's real 97-99% skip rate is correct, documented
behavior, not a bug** — confirmed by reading `config/oems/novacustom.yaml`'s
own comment, written before this run: *"category_include/category_exclude
+ non_product_terms scope it to the 6 real current SecurityTitan/[...]
models"* — the config predicted exactly 6 real products, and the real run
produced exactly 6. This is a genuinely valuable finding: it's live proof
the `non_product_terms`/`category_include` scoping mechanism (Stage 7)
works correctly at production scale against a real WooCommerce Store API
response, not just against fixtures.

**An operational finding from running this batch**: a bash-level timeout
wrapper killed an early khadas/lg attempt's shell without killing the
underlying crawl process, leaving the run lock and a `crawler_runs` row
orphaned at `status='running'` — plus two pre-existing stuck rows from
earlier stages. All four were corrected to `failed` with an explanatory
`run_errors` entry (`"Run process was killed by an external test-timeout
wrapper before completion (tooling error, not a real production
failure)"`) rather than left to silently skew this document's or any
future health/economics query.

## Real runtime signal, shopify + dell (Stage 9, unchanged this stage)

| Source | Real crawler runs | Successful (`ok`) | Real change events | Events / successful run |
|---|---|---|---|---|
| acemagic-shopify | 4 | 3 | 83 | 27.7 |
| gmktec-shopify | 3 | 2 | 85 | 42.5 |
| kamrui-shopify | 2 | 2 | 111 | 55.5 |
| beelink-shopify | 3 | 3 | 60 | 20.0 |
| bosgame-shopify | 3 | 3 | 54 | 18.0 |
| minisforum-shopify | 2 | 2 | 53 | 26.5 |
| aoostar-shopify | 3 | 3 | 36 | 12.0 |
| chuwi-shopify | 3 | 3 | 34 | 11.3 |
| nipogi-shopify | 2 | 2 | 18 | 9.0 |
| **dell-us-laptops** | 3 | **0** | 0 | n/a |

**Dell's real finding**: all 3 real runs in this history failed, and
`run_errors` records why: `FetchError('https://www.dell.com/en-us/shop/
dell-laptops/sr/laptops: HTTP 403')` on all three — the exact same URL
this project's own fixture (`tests/fixtures/dell/dell_laptops_listing.html`)
proves the engine parses correctly once it has a real response. This is
evidence of a **network/environment-level block from this project's
current egress**, not a parsing defect — the same distinction Stage 7-9
have drawn repeatedly for Lenovo/MSI/Acer. It does mean Dell's real,
measured economics in this specific environment today are "0 for 3," and
that should not be quietly smoothed over.

**Shopify's real finding**: 25 successful runs, 534 real change events,
9.0-55.5 events per successful run depending on OEM. This is the
project's only engine with enough real runtime history to say anything
evidence-based about signal density — and even this comes with a
calibration caveat: these are dev-era re-runs over 3 days, not a mature
weekly/daily production cadence, so absolute events-per-run is likely
inflated relative to steady state (re-running against a catalog that
hasn't naturally changed yet tends to produce fewer new diffs over time,
not more — an early-history number like this should be read as "proof
the pipeline generates real signal," not as a durable forecast).
One more real, checkable number from the same data: of 534 events, 289
(54%) are `Severity.BREAKING` — high enough to be worth a specific,
separate look before trusting it as steady-state (see "open question"
below), rather than treating it as background evidence for this
document's actual question.

## Which engine has the highest return on engineering effort?

Answered per the two kinds of evidence this stage actually has, kept
separate rather than blended into one fake composite score:

- **On engineering leverage (LOC/tests per OEM, measurable for all 5
  engines): `shopify`.** 12 real enabled OEMs off one 322-line engine and
  16 tests is the best-proven reuse ratio in the project, and it is real
  production history, not a projection — the same engine, unmodified,
  has now onboarded OEMs across three separate stages (original batch,
  Stage 5's VAIO/Morefine/Star Labs, and zero code changes needed since).
- **On real signal generation, now measurable for all 5 engines (Stage
  10)**: every engine successfully produced real snapshots and events on
  its first real run. `category_jsonld` and `woocommerce_store_api` are
  the cheapest in wall-clock time (bulk-inline, seconds not minutes).
  `sitemap_jsonld` costs real per-domain-rate-limited minutes proportional
  to catalog size — Medion's 692-page catalog took over an hour for one
  crawl. This is a genuine, newly-measured operating cost this document
  didn't have data for before Stage 10: a `sitemap_jsonld` OEM with a
  large catalog is measurably more expensive to run repeatedly than a
  bulk-inline OEM of the same product count.

**The honest overall answer**: `shopify` still has the best-evidenced
*engineering* ROI (most reuse, least code per OEM). But Stage 10 adds a
new axis this document didn't have before: **operating cost**, where
`category_jsonld`/`woocommerce_store_api` (seconds per crawl) clearly beat
`sitemap_jsonld` (minutes-to-over-an-hour per crawl, scaling with catalog
size) — a real tradeoff for whoever schedules these sources' `min_interval`
in production, not a defect in `sitemap_jsonld` itself.

## Stage 11 Track 5: production soak analysis, all five engines

Real query against `data/radar.db`'s full `crawler_runs`/`change_events`
history (Stage 3 through Stage 11). Sample sizes vary hugely — reported
honestly, no p95 fabricated from 3 runs.

| Engine | Runs (ok/failed) | Failure rate | Duration median | Duration p95 | Catalog size median | Events median |
|---|---|---|---|---|---|---|
| `shopify` | 23 ok / 2 failed | 8.0% | 24.2s | **115.1s** (n=23, meaningful sample) | 41 | 1 |
| `sitemap_jsonld` | 4 ok / 2 failed | 33.3% | 1,032s (~17.2min) | *n=4 — too small for p95, not computed* | 159.5 | 247.5 |
| `woocommerce_store_api` | 3 ok / 0 failed | 0% | 19.8s | *n=3 — too small for p95, not computed* | 213 | 6 |
| `category_jsonld` | 1 ok / 0 failed | 0% | 0.6s | *n=1 — single data point, not a distribution* | 12 | 12 |
| `dell` | 0 ok / 3 failed | 100% | *no successful runs* | *n/a* | *n/a* | *n/a* |

**The most useful real finding in this table**: shopify's event-count
distribution is heavily skewed — **10 of 23 real runs produced zero new
events**. Sorted real event counts: `[0,0,0,0,0,0,0,0,0,0,1,1,11,17,18,
34,35,43,53,60,64,82,111]`. This is the first real evidence (not a
projection) that a mature, repeatedly-crawled source goes quiet at
steady state — exactly what `docs/ENTERPRISE_OEM_ARCHITECTURE.md`'s
architecture assumes but couldn't previously prove. `sitemap_jsonld`'s 4
real runs are all first-ever baseline crawls (Stage 10) — its median/p95
numbers describe "first crawl of a new source," not steady state, and
must not be read as a forecast of what a second Medion crawl would cost.

**Failure rate context**: `dell`'s 100% and `sitemap_jsonld`'s 33.3% both
resolve to real, already-diagnosed causes, not engine defects —
`dell-us-laptops` is a real `HTTP 403` from this environment (see above);
`sitemap_jsonld`'s two failures are the Stage 10 tooling-timeout orphans,
corrected in the DB and explained in `docs/STAGE10.md`, not real crawl
failures.

**Noise/review data**: `alert_reviews` has **zero rows** — no alert in
this project's history has ever been manually reviewed through the
dashboard. `noise_rate`/review-based signal-quality metrics are therefore
genuinely unmeasurable, stated as a gap rather than estimated.

## Medion performance investigation (Stage 11)

Stage 10 measured Medion's one real crawl at ~69 minutes for 692
products. Stage 11 investigated whether this is a caching gap or a
structural cost.

- **Conditional GET is already implemented and already active.**
  `core/fetch.py::HttpFetcher` supports `If-None-Match`/`If-Modified-Since`
  against an on-disk cache, and `cli.py::_build_fetcher` already points it
  at `data/http_cache` for every non-dry-run crawl — no new code needed.
- **Medion's crawl was its first-ever baseline** — there is nothing to
  condition against on a first crawl by definition; every one of its
  requests was a genuine cache-miss. Testing real conditional-GET savings
  would require a *second* Medion crawl, which weekly-scale operational
  cadence (24h `min_interval`) doesn't call for during this stage.
- **Real validator coverage, checked against all 1,173 cached responses
  in `data/http_cache`** (dominated by Stage 10's `sitemap_jsonld` crawls
  — Medion, LG, SimplyNUC, Khadas combined): **335 (28.6%) carry a real
  `ETag`**, **147 (12.5%) carry a real `Last-Modified`**. This means even
  a perfectly-exploited conditional-GET cache would only skip re-fetching
  roughly a third of pages on a repeat crawl — most product pages these
  vendors serve simply don't offer a cache validator at all. The
  remaining request cost is **structural** (the per-page-fetch
  architecture itself), not a caching bug.
- **`max_products: 700` is appropriate** — Medion's real catalog (692) is
  safely under the cap, no truncation occurring.
- **Medion's 24h `min_interval` is operationally sufficient** — a
  ~69-minute crawl consumes under 5% of a 24-hour window.

**Decision: no optimization implemented.** Per this stage's own
instruction ("if conditional fetch already works effectively, document
that and do nothing") — it already works exactly as designed, the
remaining cost is inherent to fetching 692 real pages respectfully, and
no code change is justified by this evidence. Aggressive parallelization
was not considered, per the explicit constraint against it.

## Open questions this data surfaced (not resolved here)

- **Severity concentration, now confirmed across the whole database, not
  just shopify.** Of 1,300 total real events in `data/radar.db` after
  Stage 10's runs, 701 (54%) are `new_product`/severity-5 — because most
  of Stage 10's new runs were first-ever baseline crawls, and a baseline
  is definitionally "every product is new." This is expected for a
  first crawl, not evidence of a broken severity classifier — but it
  means every metric in this document that touches "average severity" or
  "alert yield" is currently dominated by one-time baseline noise rather
  than steady-state signal. Re-running these same 5 sources a second time
  (once their catalogs have had a chance to actually change) would be the
  real test of whether the severity distribution normalizes the way
  shopify's did — this document takes no position on that outcome yet.
- The original Stage 9 question (whether shopify's 54% breaking-severity
  share reflected over-triggering vs. genuine catalog volatility) remains
  open, now folded into the broader question above.

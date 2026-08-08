# Stage 8 — The Fortune 500 Offensive

Ten phases, run against `docs/CURRENT_STATUS.md`, `docs/OEM_ROADMAP_2027.md`,
`docs/ENTERPRISE_OEM_ARCHITECTURE.md`, and `docs/OEM_PLATFORM_MATRIX.md` as
authoritative starting state (21 sources → this stage; 5th engine built).
Objective, per the stage prompt: capture the highest-value remaining OEM
ecosystems while preserving every architectural principle established so
far. Optimize for capability gaps, not collector count.

## Test count

316 → **349** passed, 0 failed. Breakdown: +25 for the new `category_jsonld`
engine (Samsung + Lenovo fixtures), +1 identity-resolution regression test,
+7 platform-metrics tests, +16 total new test functions net of the metrics
test-file additions counted separately above (see per-phase sections).

## New OEMs enabled this stage (1) — and one deliberately not

- **Samsung** (`category_jsonld`, new engine) — real category-page `ItemList`
  JSON-LD with real sku/price/availability, no sitemap needed.
- **Lenovo** — confirmed real, engine-compatible data (64 SKUs across 3
  curated landing pages), **not enabled**: blocked on User-Agent-based bot
  detection that this project will not spoof past. Config, fixtures, and
  tests exist and are kept as a documented dead end.

This is a smaller enabled-count than any prior stage, on purpose — Phase 3
through 5's real finding was that most remaining candidates fail on data
quality or reachability, not that they were unexplored.

## Phase 1: Samsung discovery strategy

Read the prior finding correctly first: Stage 7 had already confirmed real
`Product` JSON-LD with real pricing on Samsung's `/buy/` product-detail
pages — the gap was *discovery* (no working sitemap). Investigating category
pages directly (not re-probing what Stage 7 already proved) found the
answer immediately: `samsung.com/us/computers/galaxy-book/` embeds a real,
complete `ItemList` — 12 items, each a full `Product` node with
`offers.price`/`offers.availability`/`name`/`image`/`url`. The category page
doesn't just *link to* the catalog, it *is* the catalog. No sitemap, no
per-product fetch, needed at all.

This is structurally the same shape `dell` already used (a listing page
embedding an `ItemList` of `Product` nodes) — and per
`docs/ENTERPRISE_OEM_ARCHITECTURE.md` §9's own stated trigger ("if a second
OEM is ever confirmed with the same shape, that is the trigger to extract a
third reusable engine — not before"), Samsung was that second OEM. Built
`category_jsonld` (`src/oem_radar/engines/category_jsonld/`):

- **Discovery**: bulk-inline (one fetch per configured `category_urls`
  entry), same contract as `shopify`/`woocommerce_store_api`.
- **Shared mechanism**: `core/jsonld.py::extract_page_products()` — new,
  handles two real shapes found this stage (see below), used only by this
  engine; `dell`'s own private `_from_jsonld` was deliberately left alone
  (see Phase 9).
- **Real-world quirk handled**: Samsung's nested `Product` items have no
  `sku`/`mpn` field — the real Samsung model code (e.g. `NP960UJH-XG7US`) is
  only present as a `-sku-XXXXXX` URL suffix, extracted via a
  source-configurable `sku_url_pattern` regex rather than a hardcoded
  assumption (the next platform to use this engine may not use the literal
  string "sku" as its separator).
- Fixtures: `tests/fixtures/category_jsonld/samsung_galaxy_book_category.html`
  (trimmed real capture — head + the 3 real JSON-LD blocks). 25 tests total
  for the engine (Samsung + Lenovo cases combined).

**A real cross-OEM bug was found and fixed validating this live.** Running
the new source end-to-end against the real Samsung page produced spurious
`component_changed`/`spec_changed`/`price_changed` diff events *within a
single first crawl* — impossible on a genuine baseline. Root cause:
`SqliteStore.resolve_prior`'s coarse `model_key` fallback (tokens up to the
first digit-bearing word, e.g. `"galaxy-book6"`) merged two genuinely
different products — "Galaxy Book6 Ultra (16", 64 GB)" and "...(16", 32 GB)"
— because they share both the coarse key and the `"ultra"` tier word, and
the existing `_same_product()` tier-word guard doesn't check config-only
differences like RAM. Both listings carry real, distinct vendor SKUs
(`NP960UJH-XG7US` vs `NP960UJG-KG2US`) that the vendor-SKU-first lookup
*should* have caught — but that lookup only fires when an *existing row*
already shares the exact SKU, and the coarse-fallback path that ran instead
never checked whether the two SKUs disagreed. Fixed with a targeted guard:
if both sides carry a real, non-empty vendor SKU and they differ, the coarse
match is skipped (`src/oem_radar/providers/sqlite/__init__.py`,
`resolve_prior`). Regression test:
`tests/test_sqlite_store.py::test_resolve_prior_distinct_vendor_skus_never_merge`.
This is not Samsung-specific — Lenovo's real fixture data hits the exact
same pattern (`tests/test_category_jsonld_engine.py::test_lenovo_same_model_name_different_skus_stay_distinct`),
and any future OEM with multiple SKUs sharing a display name would have hit
it too.

## Phase 2: enterprise API reconnaissance

Investigated XHR/REST/GraphQL/embedded-API surfaces for Lenovo, HP, Acer,
MSI, ASUS — not just JSON-LD, per the stage's explicit instruction.

- **Lenovo**: root category page (`/laptops/`) returns real content (not a
  challenge page) with the project's honest crawler UA — a change from
  Stage 7's blanket "confirmed blocked," worth noting precisely: *that*
  page isn't blocked, direct PDP fetches still are. Found a real internal
  JS config object listing genuine API paths (`/product/getProductPoints`,
  `/v1/home/materialPoints`, `/price/batch/preview/get`,
  `/api/ups/getDeliveryDate`) — all back-office (loyalty, delivery
  estimation, price preview), none a catalog/search surface. No product
  links present in the static HTML of either the category page or a
  "ThinkPad deals" listing page — the visible catalog is client-rendered.
  Separately found the real `/buy/us/en/<slug>` curated-landing-page shape
  described in Phase 1 — genuinely useful, but gated on UA (see above).
- **ASUS**: `/deals/laptops/` (a plausible bulk listing page) carries zero
  JSON-LD — consistent with, not contradicting, Stage 7's Nuxt-payload
  finding.
- **HP, Acer**: both timed out on root and category fetches again, at a 40s
  timeout — unchanged from Stage 7, still genuinely inconclusive.
- **MSI**: root fetch returned HTTP 403 directly — consistent with the
  existing `BLOCKED_BOT` classification.

No GraphQL endpoint, public search API, or catalog REST surface was found
for any of the five. The enterprise tier's "does the frontend call a public
API" question remains open for HP/Acer only because they couldn't be
reached at all this stage — for Lenovo/ASUS/MSI it's now answered (no, or
blocked).

## Phase 3: JSON-LD ecosystem expansion

Axiomtek, Qotom, BOXX, Velocity Micro, Advantech, Neousys, Portwell,
Winmate — checked with real sitemap + real product-page fetches, not
root-page guesses.

| OEM | Sitemap | Product-page JSON-LD | Verdict |
|---|---|---|---|
| Axiomtek | Real, 1,348 URLs, 364 product-shaped | Real on 1 of 8 sampled pages | **Confirmed-real-but-below-production-bar** — inconsistent template coverage |
| Qotom | Real, 2,575 URLs | None on 1 sampled page | Not a fit |
| BOXX | Real, 342 URLs | None on 2 sampled pages | Not a fit |
| Velocity Micro | Real, 184 URLs | None on 2 sampled pages | Not a fit |
| Winmate | Real, 2,470 URLs | None on 2 sampled pages | Not a fit |
| Advantech, Neousys | No sitemap found (root, `/en/`, robots.txt) | — | Genuinely undetermined discovery |
| Portwell | TLS cert chain fails verification | — | Broken infra, not a block |

Axiomtek deserves the fuller explanation given in
`docs/OEM_ECOSYSTEM_MAP.md`: the one real hit (`aie810-onx`, a genuine
`Product` node with real `sku`/`mpn`/`name`/`offers`) sits in the same
`edge-ai-gpu-computing/nvidia-jetson-system/` subcategory as three sibling
products that were checked and have *zero* JSON-LD — the template isn't
applied consistently even within one product family, let alone the whole
catalog. Enabling on an 8-sample, 1-hit rate would mean a collector that
silently misses the overwhelming majority of the real catalog. Left
disabled; a wider sample (20-30 pages) is the concrete next step if this is
revisited.

## Phase 4: Linux ecosystem

System76, TUXEDO, Slimbook, Purism (already `DISABLED_LOW_VALUE`, unchanged),
Insurgo, Juno Computers.

- **System76**: real product pages fetched for 4 models (adder-pro,
  darter-pro, lemur-pro, oryx-pro) — zero JSON-LD on any of them. System76's
  storefront is a live price-updating configurator UI; this is the same
  general blind spot as ASUS (client-rendered data), not a new pattern.
- **TUXEDO**: no sitemap at any tried path; root navigation is entirely
  informational pages (support, downloads, policies) with no direct laptop
  model links; robots.txt confirms a PrestaShop-style storefront
  (`index.php?module=...` paths) whose actual shop entry point wasn't
  located this pass.
- **Slimbook**: probe caught a 200 on `sitemap.xml` once; a direct retest
  returned HTTP 500. Server-side flakiness, not a block — genuinely
  unresolved.
- **Insurgo**: `shop.insurgo.ca` fails DNS resolution entirely. Likely a
  stale/wrong subdomain from whatever source suggested it — needs a human
  to supply the actual current storefront URL.
- **Juno Computers**: HTTP 418 (a deliberate "I'm a teapot" anti-bot
  status) — a new, distinct blocked-signature worth recording alongside the
  403/Akamai/Cloudflare signatures already known.

Zero enables. Every failure this phase is either "needs the right URL" or
"needs JS execution" — no new engine work indicated.

## Phase 5: industrial computing

OnLogic, Supermicro Edge, Kontron (Axiomtek/Neousys/Portwell/Advantech
already covered in Phase 3, not re-probed).

- **OnLogic**: Next.js app; its sitemap has only 51 URLs, and every one is a
  locale variant of a "product-finder" *tool* page, not a single actual
  product-detail page. The real catalog isn't in the discoverable sitemap
  at all — a different failure mode than "requires JS to parse," it's "the
  static discovery surface doesn't include products."
  `oem-radar probe`'s own `estimated_implementation_effort` correctly
  flagged this as "High — requires a public API check before any code."
- **Kontron**: Nuxt-hydrated (same framework signature as ASUS), zero
  JSON-LD at the root.
- **Supermicro Edge**: the specific `/en/products/system/edge` URL 404s —
  wrong path, not evidence about the platform; needs the real current URL.

Zero enables, consistent with Phase 3/4's pattern.

## Phase 6: discovery architecture

Full design review in `docs/DISCOVERY_ARCHITECTURE.md`. Went through all
eight discovery ideas the stage prompt listed (sitemap, robots, category
crawl, JSON feed, Store API, GraphQL, support index, search API, RSS)
against this stage's real evidence. Conclusion: **discovery stays a method
on each engine, config-driven per source — not a first-class plugin
system.** Four of the eight ideas map onto mechanisms already built
(sitemap, category crawl — which is exactly what `category_jsonld` is,
Store API, robots-as-a-sitemap-pointer); the other four were genuinely
investigated this stage (JSON feed, GraphQL, support index, search API) and
found not to exist on any real platform checked. Extracting a shared
discovery-plugin interface now would produce four single-consumer plugins —
pure ceremony. The document names the specific, falsifiable condition that
would change this answer: a future 5th+ engine whose natural discovery
mechanism is the *same* as an existing engine's, wrapping a *different*
parse.

## Phase 7: platform observability

Extended `oem-radar coverage`/`core/metrics.py` — every new number computed
from data that was already real and already stored, nothing fabricated:

- **`average_crawl_duration_seconds`**: computed from `crawler_runs`'
  existing `started_at`/`finished_at` ISO timestamp columns
  (`julianday(finished_at) - julianday(started_at)`). Stage 7's own docs
  assumed a new schema column would be needed to compute this honestly —
  that assumption was wrong; both columns already existed and are always
  populated. **No migration, schema still v5.**
- **`collector_stability`**: share of enabled sources whose most recent run
  succeeded.
- **`engine_stability`** (new function, `compute_engine_stability`):
  per-engine share of sources whose most recent run succeeded — needs the
  OEM config joined against `crawler_runs`, so it's a new function rather
  than an addition to the existing health-metrics query.
- **`new_products_per_day` / `changed_products_per_day` / `alerts_per_day`**:
  computed over the DB's *real* event-timestamp span (not an assumed fixed
  window) — a database with 3 days of history correctly reports a 3-day
  average, not a 30-day one.
- **`false_positive_rate`**: an alias for the existing `noise_rate` already
  computed by `feedback_analytics.compute_summary` — not recomputed
  separately, so it can never disagree with numbers `oem-radar` already
  prints elsewhere.
- **Deliberately not added**: probe-attempt success/failure rate. Probe
  results (`oem-radar probe`) are never persisted anywhere — reporting a
  rate here would mean inventing a number. Per the stage's explicit
  instruction ("only report metrics supported by real data"), this is
  correctly absent rather than approximated.

7 new tests in `tests/test_metrics.py` (16 total in that file, up from 9).

## Phase 8: OEM ecosystem map

`docs/OEM_ECOSYSTEM_MAP.md` — a flat table covering every OEM probed
through Stage 8, grouped by confidence tier (confirmed/confirmed-not-a-fit/
confirmed-blocked/confirmed-requires-JS/confirmed-but-below-bar/
inconclusive/wrong-target/undetermined) rather than by engine or brand
tier. Supersedes `docs/OEM_PLATFORM_MATRIX.md` as the day-to-day planning
reference; the matrix stays as the deeper narrative record.

## Phase 9: architectural review

Audited all 5 engines for genuine duplication (not aesthetic
inconsistency). Found exactly one real instance: `dell` and the new
`category_jsonld` both carried an identical two-line "`offers` may be a
list or a dict, take the first" normalization. Extracted to
`core/textutil.py::first_offer()`, used by both. Explicitly did **not**
extract:

- Non-product denylist term lists — stay local per established policy
  (mechanism vs. policy, `docs/PLUGIN_GUIDE.md`).
- CPU/GPU-extraction regex (`dell`'s prose-based, `category_jsonld`'s
  URL-slug-based) — different input shapes, not the same code.
- Discovery mechanics — see Phase 6; nothing new duplicated there.
- `dell` itself onto `category_jsonld` — see
  `docs/ENTERPRISE_OEM_ARCHITECTURE.md` §9's Stage 8 update for the full
  reasoning; the short version is that the extraction trigger ("a second
  OEM with the shape") is a different question from "retrofit the first
  OEM onto the new code," and only the first was actually asked by the
  architecture doc's own stated rule.

## Phase 10: scale review

Checked with real evidence, not projection, at the current real scale (28
descriptors, 21 enabled sources, 5 engines, a 2.4MB/396-snapshot/
534-change-event real database):

- **Dashboard**: every query in `dashboard/data.py` already carries a
  `LIMIT` (checked directly — recent events, runs, stories, review history
  are all bounded to 10-100 rows). Dashboard cost doesn't grow with total
  OEM count.
- **Config loading**: `load_oem_configs()` is a single linear pass over
  `config/oems/*.yaml`, currently 28 files, fast at any scale this project
  will realistically reach.
- **Database**: SQLite, 2.4MB at 21 real enabled sources across several
  weeks of accumulated runs. No pressure signal at all yet.
- **The per-domain serial fetcher** remains the one real, still-unresolved
  scaling question, flagged since the original `HANDOFF.md`. Unchanged
  assessment: not hurting yet at 27 configured OEMs, becomes worth fixing
  when total crawl wall-clock time starts to matter operationally.
- **Nothing else breaks first.** Fixtures, logging, feedback, analytics,
  and configuration all scale linearly with OEM count by construction —
  none of them do anything O(n²) or unbounded with the number of sources.

Full detail folded into `docs/ENTERPRISE_OEM_ARCHITECTURE.md`'s "Scale
check" section rather than duplicated here.

## Architectural decisions

- **Built the 5th engine only after the same evidence bar the first four
  cleared** — a second confirmed OEM with the "category page embeds full
  product data" shape, matching the architecture doc's own pre-stated
  trigger for that specific case.
- **Declined to spoof identity to defeat bot detection**, even for a
  fully-proven-compatible, fully-real data source (Lenovo). Codified as a
  permanent addition to `docs/OEM_ROADMAP_2027.md`'s "never build" list,
  not a one-off judgment call.
- **Fixed a real cross-OEM correctness bug found by shipping a new source
  honestly** (running Samsung end-to-end, not just unit-testing it) rather
  than working around it with source-specific configuration.
- **Declined to enable Axiomtek** despite having real, verified Product
  JSON-LD, because the coverage rate found was too sparse to trust in
  production — a data-quality bar, not just a data-existence bar.
- **Declined to build a discovery-plugin abstraction** despite the stage
  prompt explicitly asking the question, because the evidence gathered
  answering Phase 6 didn't support it.

## Remaining unknowns

- Whether Acer/HP are actually reachable from a different network — still
  unknown after two stages of timeouts.
- Whether Axiomtek's JSON-LD coverage improves with a wider sample, or
  whether 1-of-8 is close to the real ceiling.
- The real current storefront URLs for TUXEDO, Insurgo, and the correct
  path for Supermicro Edge — none of these were "probed and found blocked,"
  they were "probed at a URL that turned out to be wrong."
- Whether any enterprise-tier OEM exposes a genuine public catalog API —
  checked for Lenovo/ASUS/Kontron/OnLogic this stage, found none; HP/Acer
  never got far enough to check.

## Future opportunities

See `docs/OEM_ROADMAP_2027.md`'s Stage 8 update at the top of that
document for the forward-looking version of this section — this stage
corrected that document in place rather than duplicating its content here.

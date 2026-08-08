# Stage 7 — The Platform Expansion

**2026-08-07.** Builds on Stage 6's proof that reusable engines work
(`docs/STAGE6_RECON.md`, `docs/ENTERPRISE_OEM_ARCHITECTURE.md`). This stage
finished the Stage 6 backlog, built a second reusable engine, resumed
mainstream-OEM reconnaissance with real evidence, upgraded the probe into
something closer to a reconnaissance assistant, consolidated genuine
duplication across all four engines, and added platform-wide metrics.

## Test count

298 (start of stage) → **316** (end of stage). Breakdown of additions:
11 (Star Labs/Medion/LG) + 27 (woocommerce_store_api engine) + 18 (probe
Phase 4) + 9 (textutil) + 9 (metrics) — some phases' tests landed on top of
running totals; see the individual test files for exact scope.

## New OEMs enabled this stage (9)

| OEM | Engine | What changed |
|---|---|---|
| Star Labs | shopify | Config-only: expanded `non_product_terms` denylist (spare parts — mainboards, batteries, displays, input covers) confirmed empirically against the real fixture. 19 real listings kept out of 111 raw. |
| Medion | sitemap_jsonld | `url_include_pattern` scopes the 6,265-URL mixed retailer catalog to the ERAZER gaming notebook/desktop lines only (~680 of 6,265 URLs). Deliberately excludes the larger entry-level/multimedia lines for operational-cost reasons — see "Deliberately not maximized" below. |
| LG | sitemap_jsonld | Re-probed on the US consumer site (`lg.com/us`) instead of the India business site tried in Stage 6 — real pricing found there. `url_include_pattern` scopes 6,220 URLs down to 182 real gram-laptop product pages. |
| GEEKOM | woocommerce_store_api | Re-enabled — the engine that was missing in Stage 5/6 now exists. |
| NovaCustom | woocommerce_store_api | New. Security-focused Linux/coreboot laptop maker (NL); `category_include`/`category_exclude` scopes a 275-item catalog dominated by refurbished/spare-parts listings down to 6 real current products. |
| Pine64 | woocommerce_store_api | New. Open-hardware community brand; scoped from 213 items (phones/tablets/SBCs/accessories) to 2 real current Pinebook Pro laptop SKUs. |

## New engine: `woocommerce_store_api`

Built after **3 independently confirmed real candidates** (GEEKOM,
NovaCustom, Pine64) crossed the same bar `sitemap_jsonld` crossed in
Stage 6 — see Phase 2 evidence below. Generic, descriptor-driven, zero
vendor conditionals: `src/oem_radar/engines/woocommerce_store_api/`.

Key design points:
- **Bulk-inline discovery** (like `shopify`, unlike `sitemap_jsonld`): the
  Store API returns full product records per page, so no per-product fetch
  is needed.
- **Minor-unit pricing handled correctly**: `prices.price` is a string in
  minor units, scaled by `prices.currency_minor_unit` — GEEKOM's is `0`
  (whole dollars), NovaCustom/Pine64's is `2` (cents). A hardcoded ÷100
  would have silently mispriced GEEKOM by 100x. Regression test:
  `test_geekom_zero_minor_unit_pricing`.
- **`category_include`/`category_exclude`**: config-driven category
  scoping, the WooCommerce analog of `sitemap_jsonld`'s
  `url_include_pattern` — same principle, no code duplicated between them
  (deliberately; see Phase 5).
- **A real false positive found and fixed during this stage**: the first
  denylist draft included "keyboard" (meant to filter standalone keyboard
  accessories) and it incorrectly matched Pine64's real product
  `"14″ PINEBOOK Pro LINUX LAPTOP (UK Keyboard)"`. Removed from the
  built-in list; kept as a source-scoped `non_product_terms` entry for
  NovaCustom where it can't collide with anyone else's catalog. This is
  now a permanent regression test
  (`test_pine64_real_laptop_with_keyboard_in_title_not_filtered`) and a
  documented lesson for future denylist terms across every engine: generic
  input-device words are not safe defaults.

27 tests: `tests/test_woocommerce_engine.py`. Fixtures + provenance:
`tests/fixtures/woocommerce/`.

## Phase 2 evidence: WooCommerce candidates probed

Using the Stage 6 probe tool against a fresh batch (industrial, mini-PC,
Linux boutique, workstation vendors):

| Candidate | Result |
|---|---|
| NovaCustom | **Confirmed** — real Store API, 275 products |
| Pine64 | **Confirmed** — real Store API, 213 products |
| Protectli, Puget Systems | WooCommerce hint (theme/assets) but **no working Store API route** |
| Axiomtek, Qotom, BOXX Technologies, Velocity Micro | `static_jsonld` guess — not pursued this stage (Phase 2 was WooCommerce-scoped; worth a `sitemap_jsonld` follow-up) |
| CWWK | **Shopify** (bonus find, not pursued — Phase 1/2 already had a full slate) |
| Advantech, Neousys, Winmate, Portwell | Inconclusive/unreachable |
| Juno Computers, Insurgo, KDE Slimbook, Topton | Unreachable (DNS/timeout) from this network |

## Phase 3: mainstream OEM deep reconnaissance — answered with evidence

The instruction was explicit: don't stop at category pages, and answer
"can we reach these without browser automation" with evidence, not theory.

| OEM | What was actually checked | Finding |
|---|---|---|
| Lenovo | Direct fetch of a real product URL (not just root) | **Confirmed blocked** — HTTP 403 on the product page itself, same as root |
| MSI | Direct fetch of a real product URL | **Confirmed blocked** — HTTP 403 on the product page itself |
| Acer | Direct fetch of a real product URL | Read-timeout, consistent with Stage 6's root-probe timeout — likely silently dropping non-browser traffic rather than actively 403ing |
| ASUS | Real product page fetched; searched for `__NEXT_DATA__`/`__NUXT__`/Apollo/API-string markers | **Real data exists but isn't statically parseable**: the page ships `window.__NUXT__=(function(a,b,c,...){...})(...)`  — a minified Nuxt SSR payload serialized as a JS *function call* with positional single-letter parameters, not JSON. Reconstructing it requires executing the JS (or a bespoke, fragile de-minifier) — genuinely different from "just find the JSON," and correctly falls outside static/API-only reach |
| HP | Direct fetch of a real product URL | Read-timeout |
| Samsung | Real product `/buy/` page fetched | **Confirmed real, usable Product JSON-LD**: real SKU (`NP960QHA-KG1US`), real price ($1999.99 USD), real availability. Samsung is genuinely reachable without browser automation — the gap is a *discovery* mechanism (no working sitemap found in this pass; `robots.txt` serves an HTML fallback, not a real robots file, and the standard `/us/sitemap.xml` path returned only 7 unrelated URLs). Category-page link scraping is the concrete next step, not JS rendering |

**The evidence-based answer to Phase 3's question**: partially yes.
Lenovo/MSI are confirmed hard-blocked (no static path exists). ASUS is
confirmed to require JS execution for its product data specifically (not
a hypothesis — the payload format itself proves it). Samsung is confirmed
**reachable** without any browser automation — real JSON-LD, real pricing
— and just needs a discovery-strategy investment, not an engine or a
Playwright justification. Acer/HP remain genuinely inconclusive (timeouts,
not confirmed blocks) and need a retry from a different network before
either "blocked" or "reachable" can be claimed.

**Samsung was not enabled this stage** despite the positive finding —
building a reliable discovery strategy (category-page crawling across
every Galaxy Book series page, since no sitemap was found) is real
engineering work distinct from what was budgeted for Phase 1/2 of this
stage, and per the stage's own "optimize for capability, not collector
count" framing, a rushed, fragile discovery mechanism would undermine the
finding rather than capitalize on it. Documented as the strongest
near-term opportunity in `docs/OEM_ROADMAP_2027.md`.

## Phase 4: probe upgrades

`src/oem_radar/core/probe.py` now additionally reports (18 new tests,
`tests/test_probe_phase4.py`):

- **Framework detection**: Next.js (`__NEXT_DATA__`), Nuxt (`__NUXT__`),
  generic React hints.
- **GraphQL hint** (string-presence check — deliberately simple, a
  probe-level flag not a full endpoint fingerprint).
- **Magento / Adobe Commerce / Salesforce Commerce hints** — string-marker
  based (`Magento_`, `requirejs-config.js`, `demandware`, `dwsid`, etc.).
- **Sitemap compression flag** (`.gz` sitemap URLs — a real limitation
  found at Dynabook in Stage 5; the flag now makes that limitation visible
  at probe time instead of failing silently later).
- **JSON-LD richness score** (0-100): how complete a page's `Product`
  JSON-LD is (name/sku/mpn/offers/image/brand presence), averaged across
  every Product node found. Explicitly documented as a **data-completeness
  measure, not an editorial-value judgment** — no static probe can know
  whether an OEM is newsworthy.
- **`public_api_count()`**: how many distinct confirmed/hinted data APIs
  were found (Shopify JSON, WC Store API, GraphQL hint, JSON-LD presence).
- **`estimated_implementation_effort()`**: Low/Medium/High/Blocked/Unknown,
  derived purely from which existing engine (if any) already fits and how
  complete the data is — never a guess about how hard a *new*, unseen
  platform's bespoke parser would be.
- **`collector_recommendation()`**: a technical suggestion (which engine,
  or `NEEDS_OWNER_PROBE`/`BLOCKED_BOT`), explicitly not an editorial
  recommendation.

`oem-radar probe <url> [--json]` prints all of this in the reconnaissance-
assistant style requested (platform/framework, JSON-LD richness label,
GraphQL hint, public API count, recommended engine, estimated effort).

## Phase 5: engine maturity review

Reviewed all four engines (`shopify`, `dell`, `sitemap_jsonld`,
`woocommerce_store_api`) for genuine duplication. Extracted exactly two
things, both pure boilerplate with zero policy content:

- **`core/textutil.py`**: `strip_html()` (three engines had byte-identical
  `_TAG_RE`/`_WS_RE`/`_strip_html` trios), `contains_any()` (the substring-
  match mechanism behind every engine's denylist check), and
  `parse_schema_availability()` (the InStock/OutOfStock/PreOrder string
  mapping that `dell` and `sitemap_jsonld` had each hand-rolled slightly
  differently — `dell`'s version only recognized "InStock," silently
  losing OutOfStock/PreOrder signal that now works correctly after the
  consolidation).

**Deliberately NOT extracted**: the non-product denylist *term lists*
themselves. Each engine's `_DEFAULT_NON_PRODUCT` stays local — Star Labs'
"mainboard"/"heatsink" vocabulary has nothing to do with Pine64's, and
sharing the lists would couple engines that should stay independent (this
was already the explicit design decision documented in `sitemap_jsonld`'s
module docstring in Stage 6; Phase 5 just applied the same reasoning
consistently rather than revisiting it). This is the "do not over-engineer,
only refactor where multiple engines genuinely benefit" instruction applied
literally: the *mechanism* benefits from sharing, the *policy* does not.

9 tests: `tests/test_textutil.py`. Full regression run after every engine
edit — no behavior changes except the Dell OutOfStock/PreOrder fix, which
had no existing test coverage either way (new, correct behavior; not a
silent regression).

## Phase 6: platform metrics

New `oem-radar coverage [--json]` CLI command, backed by
`src/oem_radar/core/metrics.py` — deliberately **not** a dashboard change
(the stage explicitly says don't redesign the dashboard). Reports:

- **Coverage**: OEM descriptor count, enabled/disabled source counts,
  engines in use with per-engine OEM lists, and a status breakdown parsed
  from each descriptor's `# support_status:` comment (best-effort — files
  without the comment show as `UNDOCUMENTED` rather than guessed).
- **Fixture coverage**: real fixture-file counts per engine directory.
- **Health**: run counts (ok/failed), run failure rate, current
  healthy/degraded/failed collector counts, average catalog size. One
  metric explicitly reported as **not tracked** rather than approximated:
  average run duration — `crawler_runs` has no wall-clock column, so
  claiming a number would be fabrication, not a metric.
- **Signals**: reuses `core.feedback_analytics.compute_summary()` verbatim
  (same no-duplicated-metric-math rule the dashboard follows) plus a total
  change-event count.

Real `oem-radar coverage` output against the live `data/radar.db` at the
end of this stage:

```
=== Coverage ===
  OEM descriptors: 26  (loaded: 26)
  Enabled sources: 20   Disabled: 6
  Engines in use: dell, shopify, sitemap_jsonld, woocommerce_store_api
    dell: 1 source(s) — Dell
    shopify: 12 source(s) — ACEMAGIC, AOOSTAR, Beelink, Bosgame, Chuwi,
      GMKtec, KAMRUI, MINISFORUM, Morefine, NiPoGi, Star Labs, VAIO
    sitemap_jsonld: 4 source(s) — Khadas, LG, Medion, SimplyNUC
    woocommerce_store_api: 3 source(s) — GEEKOM, NovaCustom, Pine64
  Status breakdown (from descriptor `# support_status:` comments):
    UNDOCUMENTED: 10  LIVE_VALIDATED: 10  BROKEN: 3
    NEEDS_OWNER_PROBE: 2  BLOCKED_BOT: 1

=== Fixture coverage ===
  dell: 2   shopify: 8   sitemap_jsonld: 13   woocommerce: 7

=== Health ===
  Runs recorded: 28  (ok: 23, failed: 3)
  Run failure rate: 0.1071
  Collectors currently: healthy=8 degraded=0 failed=0
  Average catalog size: 38.4

=== Signals (feedback analytics) ===
  Total change events: 534
  Reviewed: 0  Unreviewed: 534
```

The `UNDOCUMENTED: 10` is honest, not a bug — those are the original
Stage 3/4 descriptors (GMKtec, Minisforum, Beelink, AOOSTAR, Chuwi,
Bosgame, NiPoGi, ACEMAGIC, KAMRUI, Dell) written before the
`# support_status:` comment convention existed. `20 enabled + 6 disabled =
26` reconciles exactly with the descriptor count, and the 6 disabled are
the AYANEO/Firebat/GPD/Kingnovy/Peladn/Trigkey backlog from Stage 5-6.

9 tests: `tests/test_metrics.py`, using temporary config/DB fixtures (never
the real `config/oems/`, so these tests stay correct as the real directory
grows).

## Architectural decisions

- **Samsung not enabled despite confirmed real data** — see Phase 3 above.
  Confirming reachability and building a responsible discovery mechanism
  are different amounts of work; conflating them would have meant either
  rushing a fragile source or silently skipping the finding. Neither is
  acceptable — it's documented instead, with a concrete next step.
- **Medion scoped to gaming-only, not "all PC categories"** — even after
  `url_include_pattern` scoping to every PC-ish category prefix
  (convertible/einsteiger/multimedia/gaming notebooks and PCs), the result
  was 2,261 URLs — larger than every other source in the platform
  *combined*. Fetching that every ~12h is not "respectful crawling," it's
  a de facto denial-of-service risk against a real production site for
  marginal signal (entry-level SKUs churn slowly and are lower editorial
  density than gaming-line launches). Scoped further to gaming lines only
  (~680 URLs, `min_interval: 24h`, `max_products: 700` as an explicit
  safety cap) — a deliberate, documented trade-off between "prove the
  capability" and "don't build something irresponsible."
- **`woocommerce_store_api` mirrors `shopify`'s bulk-inline pattern, not
  `sitemap_jsonld`'s per-page pattern** — because the Store API genuinely
  is a bulk endpoint, unlike a sitemap. Choosing the pattern per the
  platform's actual shape, not defaulting to whichever engine was built
  most recently.
- **`textutil.py` extraction stopped at mechanism, not policy** — see
  Phase 5. This is the single most important "don't over-engineer" call
  this stage made.

## Remaining unknowns

- Whether Acer/HP are genuinely blocked or just slow/rate-limited from this
  network — needs a retry, ideally from a different network, before either
  conclusion is safe to write down as fact.
- Whether ASUS's Nuxt payload is consistent across all product pages (only
  one was checked) — the finding ("requires JS execution") is solid, but
  the *scope* of that finding (every ASUS page? just this template?) isn't
  fully mapped.
- Whether Samsung's `/buy/` pages are consistently structured across every
  Galaxy Book model, or whether the one checked was a lucky/unlucky sample.
- Whether any of the "inconclusive/unreachable" WooCommerce industrial
  candidates (Advantech, Neousys, Winmate, Portwell, Juno Computers,
  Insurgo) would resolve on a retry — several read as network-level
  failures from this sandbox specifically, not confirmed platform findings.

## Future opportunities

See `docs/OEM_ROADMAP_2027.md` for the full strategic view. Immediate
next-stage candidates in priority order: (1) Samsung discovery-strategy
work (highest-confidence win sitting on the table), (2) Axiomtek/Qotom/
BOXX/Velocity Micro `sitemap_jsonld` follow-up (probed this stage, not yet
deep-checked), (3) a retry pass on the "inconclusive" WooCommerce
industrial candidates from a different network.

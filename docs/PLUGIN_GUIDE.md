# PLUGIN_GUIDE.md

Two extension paths, in order of how often you'll use them.

## Path 1: Add an OEM (YAML only — the common case)

If the OEM runs Shopify or WooCommerce, you write no code. Create `config/oems/<name>.yaml`:

```yaml
manufacturer:
  name: GMKtec
  aliases: [GMK, "极摩客"]
  country: CN

sources:
  - id: gmktec-shopify
    engine: shopify                # registered engine name
    base_url: https://www.gmktec.com
    min_interval: 6h               # ADR-1: run skips this source if crawled more recently
    discovery: [products_json, sitemap]   # strategies, union of results
    currency_default: USD
    category_map:                  # vendor collection → normalized category
      mini-pcs: mini_pc
      handhelds: handheld
    spec_hints:                    # optional regex/JSON-path nudges for messy fields
      cpu_from_title: true
```

Run `oem-radar validate` — it checks the descriptor against the engine's declared config schema without touching the network. Then `oem-radar run --source gmktec-shopify --dry-run` to see what would be stored/notified. That's the whole procedure; core, DB, notifier, and every other OEM are untouched.

How do you know which platform a store runs? `oem-radar probe <url> [--json]` (`src/oem_radar/core/probe.py`, upgraded Stage 5, 7, and again Stage 9) fingerprints it deterministically: HTTP status/redirect chain, Shopify `/products.json` (with a sample product count), Shopify theme hint (`cdn.shopify.com`), a **live check** of the WooCommerce Store API rather than just guessing from body text, sitemap/robots.txt discovery (index vs. leaf, product-URL heuristic, `.gz` compression flag), JSON-LD `Product` node count **and a 0-100 data-completeness richness score**, framework detection (Next.js/Nuxt), GraphQL/Magento/Adobe-Commerce/Salesforce-Commerce hints, and a bot/challenge heuristic. It also prints a technical `collector_recommendation()` and `estimated_implementation_effort()` — explicitly derived from observable signals only, never a claim about an OEM's editorial/newsworthiness value, which no static probe can determine. **Stage 9** turned the plain field dump into a reconnaissance-analyst report: a 0-100 `confidence()` score, plain-language `evidence()` lines each traced to an observed field, a 0-100 `discovery_quality()` score with an itemized deduction list (every point lost cites a specific reason — anti-bot gate, missing sitemap, partial JSON-LD, JS-hydration with no server data), `known_risks()`, `missing_information()`, `recommended_fixture_count()`/`recommended_engineer_time()`, and a `should_pursue()` verdict + cited reason. Every one of these is evidence-backed only — never guessed — and editorial value is still deliberately absent from all of them. Do not set `enabled: true` on an HTTP 200 alone — see `docs/STAGE5_RECON.md`/`docs/STAGE7.md` for real examples of stores that looked promising (a sitemap with "product" in some URL) but had no actual structured product data on inspection.

For a platform-wide view instead of one storefront, `oem-radar coverage [--json]` (Stage 7, `src/oem_radar/core/metrics.py`) reports OEM/engine counts, fixture coverage, collector health, and signal metrics — always live-computed from `config/oems/` and the database, never a stale snapshot.

## Path 2: Add an engine (code — for platforms and oddballs)

An engine implements the `SourceEngine` protocol (`core/interfaces.py`):

```python
from oem_radar.core.interfaces import SourceEngine, Fetcher, ProductRef, FetchedDocument
from oem_radar.core.models import NormalizedProduct, RawProduct, ValidationIssue
from oem_radar.core.registry import engines

@engines.register("topton")
class ToptonEngine:
    config_schema = ToptonConfig          # pydantic model; validates the YAML source block

    def discover(self, fetcher: Fetcher) -> Iterable[ProductRef]: ...
    def parse(self, doc: FetchedDocument) -> RawProduct: ...
    def normalize(self, raw: RawProduct) -> NormalizedProduct: ...
    def validate(self, product: NormalizedProduct) -> list[ValidationIssue]: ...
```

Rules that keep the architecture honest:

- **No I/O except through the injected `Fetcher`.** The fetcher gives you politeness, caching, conditional GETs, and — in tests — canned fixtures for free. An engine that imports `requests` fails review.
- **No database, no Discord, no AI.** Return values only.
- **`normalize` maps into the shared model; put everything else in `raw_data`.** Never invent values: unknown stays `None`, and `confidence` should reflect how much of the listing you actually understood.
- **`validate` reports, it doesn't reject.** Issues lower confidence; the core decides what to do (a listing failing validation because of an unrecognized CPU string is high-value, not garbage — see DIFF_ENGINE.md on known-hardware flags).
- **Discovery strategies are separate registered classes** (`discovery.register("sitemap")`) so engines share them; an engine declares which strategies it supports.
- **Two discovery patterns exist — pick per the platform's actual shape, not by habit.** *Bulk-inline* (`shopify`, `dell`, `woocommerce_store_api`, `category_jsonld`): `discover()` embeds full product data in `ProductRef.inline_payload`, and the pipeline skips the per-product fetch — use this when the platform has a real bulk catalog endpoint. *Per-page fetch* (`sitemap_jsonld`): `discover()` returns bare refs with no `inline_payload`, and the pipeline fetches each URL itself before `parse()` — use this when discovery (a sitemap) and product data (the individual page) are genuinely separate. Don't force a bulk-endpoint platform into the per-page pattern or vice versa.
- **Share mechanism, not policy, across engines** (Stage 7). `core/textutil.py` has `strip_html()`, `contains_any()`, and `parse_schema_availability()` — pure boilerplate every engine needs. The non-product denylist *term lists* themselves stay local to each engine's file, deliberately not shared: one vendor's spare-parts vocabulary has nothing to do with another's, and sharing the list would silently couple engines that should stay independent. If you find yourself duplicating logic across engines, ask whether it's mechanism (share it) or policy (keep it local).

### Engine tests (required per engine)

Fixtures live in `tests/fixtures/<engine>/` as captured real responses (JSON/HTML), goldens in `tests/goldens/<engine>/`. Minimum suite: discovery finds the expected refs from fixture responses; parse+normalize matches stored golden JSON (`assert_goldens` — a change in engine output fails loudly; accept deliberately with `UPDATE_GOLDENS=1 pytest`); validate flags the deliberately broken fixture (`assert_validate_flags`); config schema rejects a malformed block (`assert_config_rejected`). The shared harness in `tests/engine_harness.py` provides all four given routed fixture responses, so a new engine's test file is ~20 lines — see `tests/test_review_now_list.py` for usage.

### Before building a new engine

Don't build a reusable engine for a single vendor. The bar (set in Stage 5,
see `docs/STAGE5_RECON.md` Part 4) is **at least 3 confirmed real
candidates** — verified with an actual product-page/API fetch, not just a
promising-looking sitemap or `wp-content` string in the homepage HTML.

Five engines exist as of Stage 8: `shopify`, `dell` (deliberately
vendor-specific — see `docs/ENTERPRISE_OEM_ARCHITECTURE.md` §9 for why),
`sitemap_jsonld` (built Stage 6 once SimplyNUC, Khadas, Medion, and LG
independently confirmed real schema.org `Product` JSON-LD across four
structurally different platforms — see `docs/OEM_PLATFORM_MATRIX.md`),
`woocommerce_store_api` (Stage 7, built after GEEKOM/NovaCustom/Pine64
confirmed a working `/wp-json/wc/store/v1/products` endpoint), and
`category_jsonld` (Stage 8, built after Samsung confirmed the second real
"category page embeds a full ItemList of Products" shape — see
`docs/ENTERPRISE_OEM_ARCHITECTURE.md` §9's Stage 8 update). See
`docs/ENTERPRISE_OEM_ARCHITECTURE.md` for the full architecture this
feeds into, including the scaling plan toward 50-100+ collectors.

### Reusable-engine checklist (Stage 6-7)

Every reusable engine (not `dell`-style bespoke ones) must, without any
`if vendor == ...` branch inside the engine itself:

- support fixtures, deterministic tests, and offline replay
- support pagination/index-recursion where the platform has it
- degrade gracefully on malformed responses (skip, don't crash — see
  `core/jsonld.py`'s tolerant JSON-LD walker)
- support retries (via the injected `Fetcher` — engines never implement
  their own retry logic)
- normalize into the shared `NormalizedProduct`/`ChangeEvent` contract
  (this is what makes dashboard/feedback/analytics compatibility automatic
  — see `docs/ENTERPRISE_OEM_ARCHITECTURE.md` §13)
- push all vendor-specific behavior into the source's YAML config
  (denylist terms, URL include/exclude patterns, currency) rather than
  engine code

## Path 3 (rare): new provider

Storage, notification, and AI backends implement `SnapshotStore`, `Notifier`, `Summarizer` respectively, register under a name, and get selected in `radar.yaml` (`notifier: discord`, `store: sqlite`, `summarizer: anthropic`). Same rules: config-schema declared, no cross-imports.

## Source support status (required)

Every descriptor must be classified. Allowed values:

`LIVE_VALIDATED` · `LIVE_PARTIAL` · `CANARY` · `NEEDS_OWNER_PROBE` · `BLOCKED_JS` · `BLOCKED_BOT` · `BROKEN` · `DISABLED_LOW_VALUE`

Do not set `enabled: true` without live proof (or real sanitized fixtures + tests) and a status other than the blocked/broken set.

## Fixture rules

- Capture real responses (`/products.json`, catalog HTML, etc.).
- Sanitize: truncate long HTML, strip query noise where safe, no credentials/PII.
- Store under `tests/fixtures/` with source + date in comments or docs.
- Never invent catalog JSON to green a test.

## Acceptance criteria (enablement)

1. Discovery returns relevant products from fixture and live probe.
2. Unexpected zero-product runs are **failed**, not success.
3. Stable identifiers across fixture re-runs.
4. Accessories filtered via non-product denylist.
5. Malformed product does not abort the whole source.
6. Source failure does not abort other collectors.
7. Baseline quiet on first crawl.
8. Removal grace unchanged.
9. Real fixtures + tests present.
10. Documented available/missing signals in `docs/OEM_COVERAGE.md`.
11. Change events carry evidence metadata when available (`collector_engine`, `catalog_count`, …).
12. Health reflects degraded/failed on catalog collapse.
13. No fake confidence from “parse returned an object.”

## Collector health

Configured under `collector_health` in `radar.yaml`. Catalog collapse is **not** a mass `product_removed` event.

## Canary promotion

New sources may ship as `CANARY`: collect + persist; avoid flooding the primary Discord channel when a canary channel/config exists. Promotion to `LIVE_VALIDATED` is **manual** after multiple successful runs.

## Feedback suggestions

Stage 3 may *propose* rules. They must **not** be applied automatically to collectors. Implementation is a separate human change.

## Collector health runtime wiring

`collector_health` in `radar.yaml` is loaded into `RadarConfig.collector_health` and
passed by `run_all()` into every `run_source(..., health_cfg=...)`. Direct unit-test
calls to `run_source` without `health_cfg` use safe defaults.

Thresholds must satisfy `0 <= min < warn <= 1`. Failed runs never become the
last-good catalog baseline and never emit mass `product_removed` events.

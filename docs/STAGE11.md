# Stage 11 — The Evidence Bar

> **Superseded in part by `docs/STAGE11_1.md` (2026-08-08).** The
> reconnaissance, the trigger evaluation and the `EvidenceSource`
> abstraction below all stand. The *event* plumbing did not: this stage
> emitted a `change_events` row per evidence item, which put 1,544
> unopenable rows (44.6% of the alert stream) into the product-alert feed
> and buried the actual hardware discoveries. Schema v7 moved them into
> `evidence_events`. Read the two documents together; where they conflict,
> Stage 11.1 is current.

**Written 2026-08-08.** Stage 10 found a real, striking lead (Lenovo
PSREF) but explicitly declined to build `EvidenceSource` on one OEM and
one evidence type — the pre-committed trigger wasn't met. Stage 11's
mandate: determine, with real evidence, whether PSREF is a reusable
source class or a one-off — and only implement if the trigger fires.

## Track 1 — Lenovo PSREF deep reconnaissance

Fully characterized `psref.lenovo.com/api/ph/ProductCategoryTree`: 1,544
real products, real `Withdraw` status field (952 discontinued / 592
current — a genuine current-vs-historical split), CDN-cached but no
conditional-GET support, byte-identical on repeat calls. The central open
question — does one `ProductKey` represent a sellable configuration or a
coarser family, and is there a per-product spec/MTM endpoint — could
**not** be resolved via static analysis: 9 real endpoint-name guesses
against a real ProductID, all 404. Flagged for a human DevTools session,
not further guessing. Full writeup: `docs/PSREF_RECON.md`.

## Track 2 — a second OEM

Found one: **HP**. Reading `support.hp.com`'s own Angular bundle text
revealed a real `wcc-services` API family; live-tested
`prodcategory/getProductCategoriesBySeoName` returned 18 real laptop
sub-brand categories with stable `oid`/`uid` identifiers, confirmed
stable across repeat calls. ASUS/MSI/Acer/Dell were also checked — no
comparable enumerable catalog surface found for any of them (Dell's
support API is service-tag-oriented, a genuinely different kind of
surface, not a catalog). Full evidence table: `docs/ALTERNATE_SOURCE_MATRIX.md`.

## Track 3 — Lenovo multi-evidence test

Checked support/download/pcsupport (all still 403, same UA-gating already
declined) and news.lenovo.com (real, WordPress-based, but explicitly
excluded by this stage's own rule against counting a newsroom feed).
Lenovo has exactly 1 confirmed evidence type, not 3 — Trigger B not met.

## The trigger decision

**Trigger A (2 OEMs) met: Lenovo + HP.** Trigger B (1 OEM + 3 types) not
met for either. Per the stage's own pre-committed rule, this justified
implementation — see `docs/ALTERNATE_SOURCE_MATRIX.md` for the full
evaluation, locked in *before* any code was written.

## Track 6 — the architecture question, answered

Neither confirmed surface produces full product entities (no price, no
confirmed specs) — both give identity + taxonomy + status. This is
supporting evidence, not an alternate product catalog, so `EvidenceSource`
was built as a real sibling protocol to `SourceEngine`, not a variant of
it. Full reasoning: `docs/EVIDENCE_ARCHITECTURE.md`. Built: `EvidenceItem`/
`EvidenceKind`/`EvidenceProvenance` models, the `EvidenceSource` protocol,
an additive schema v6 migration (`evidence_items`/`evidence_links`), a
small separate pipeline (`core/evidence_pipeline.py`), and the first real
implementation (`evidence_sources/lenovo_psref/`, 13 tests against a real
trimmed fixture). Conservative identity correlation (exact SKU/MPN/model/
alias, no fuzzy matching) caught and fixed a real bug in its own test
suite: comparing evidence identity against `products.canonical_model`
(a coarse key) would have linked "ThinkPad X1 Carbon Gen 12" and "ThinkPad
X1 Yoga Gen 9" as the same product — the same class of failure Stage 8
found and fixed in `resolve_prior` itself. Fixed before it shipped.

Run once against live `psref.lenovo.com`: 1,544 real evidence items
persisted into the real `data/radar.db`, all correctly unlinked (no
tracked Lenovo storefront products exist to correlate against). A repeat
run produced zero new events, proving the dedup/idempotency logic against
real data, not just fixtures. (The accompanying `SUPPORT_ARTIFACT_ADDED`
rows this stage wrote into `change_events` were the regression Stage 11.1
corrected — see `docs/STAGE11_1.md`.)

**Deliberately not built**: CLI/config wiring (evidence sources aren't
storefronts — forcing them into the same YAML schema before a second
implementation exists would be premature), Discord delivery (no real
production experience yet to calibrate noise-suppression policy against),
and a second real implementation for HP (the trigger needed 2 *confirmed*
OEMs, not 2 *built* integrations).

## Track 4 — ASUS

No owner DevTools capture was performed this stage — deliberately. This
project's own browser tooling could technically load and inspect ASUS's
page, but the stage's instruction ("do not automatically execute the page
JS") reads as a constraint on the investigating agent, not only on OEM
Radar's collector code. Status: `PENDING_OWNER_ACTION`, alongside PSREF's
own per-product endpoint (same class of gap, same fix). See
`docs/OWNER_PROBE_BACKLOG.md`.

## Track 5 — production soak analysis

Real numbers across all 5 engines from `data/radar.db`'s full history —
see `docs/COLLECTOR_ECONOMICS.md`. Headline finding: shopify's real
event-count distribution is **10-of-23 runs producing zero new events** —
the first real proof (not a projection) that a mature source goes quiet
at steady state. `sitemap_jsonld`/`woocommerce_store_api`/`category_jsonld`
sample sizes (4/3/1 successful runs) are explicitly too small for a real
p95 and none was fabricated.

## Medion

Investigated whether the ~69-minute, 692-product crawl reflects a caching
gap. It doesn't: conditional GET (`If-None-Match`/`If-Modified-Since`) is
already implemented and already active via `data/http_cache`, but only
28.6% of cached `sitemap_jsonld` responses carry a real `ETag` (12.5%
`Last-Modified`) — most of the cost is structural (per-page fetch over a
large real catalog), not a caching bug. `max_products: 700` and 24h
`min_interval` are both already appropriate. **No optimization
implemented** — the existing mechanism already works as designed, per
this stage's own "if it works, document that and do nothing" instruction.

## Opportunistic enables

None. No reconnaissance target this stage cleanly fit an existing engine
with zero architecture change, and the stage's own 2-enable cap was never
approached — collector count stayed exactly 21, as intended.

## Final state

419 tests passing (up from 383). Schema v6. `EvidenceSource` exists as a
real, tested, production-proven subsystem with exactly one real
implementation — built because the evidence justified it, not because the
idea was appealing, and scoped to the smallest slice that could prove the
mechanism works end-to-end against live data.

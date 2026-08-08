# Evidence Architecture — v0.1

**Written Stage 11 (2026-08-08), implemented this stage after the
pre-committed trigger fired.** This document exists because the trigger
fired, not because the idea was appealing — see `docs/ALTERNATE_SOURCE_MATRIX.md`
for the evidence and `docs/STAGE10.md`/`docs/STAGE11.md` for why Stage 10
deliberately did not build this a stage earlier.

## The central question this stage was built to answer

Should Lenovo PSREF and HP's product-category API be represented as a
`SourceEngine` (full product entities, the existing pipeline) or a new,
sibling `EvidenceSource` concept? **Answer: `EvidenceSource`.** Reasoning:

Both confirmed surfaces (`docs/PSREF_RECON.md`, `docs/ALTERNATE_SOURCE_MATRIX.md`)
give identity + taxonomy + status — a real product name, a stable
identifier, and (for PSREF) a current/discontinued flag. **Neither gives
price, confirmed specs, or availability** — the fields
`NormalizedProduct` and this project's entire diff/severity/story
pipeline are built around. Forcing PSREF's `Withdraw`/`ProductKey` pair
into `NormalizedProduct` would mean either inventing values for every
other field forever (violating "never invent a value," the single most
load-bearing rule in `docs/ARCHITECTURE.md`) or leaving most of
`NormalizedProduct` permanently `None` — a shape no `SourceEngine` has
ever had, and a shape the diff engine's `price_changed`/`spec_changed`/
`component_changed` rules have nothing to key off of.

**This is exactly the distinction Stage 11 asked to be drawn explicitly**:
an alternate product catalog (full entities) belongs in `SourceEngine`;
supporting evidence (identity/status/document facts) does not. PSREF and
HP's confirmed data, as of this stage, are the latter. If a future
DevTools session confirms a real per-product spec endpoint for either
(the single most-flagged open question in `docs/PSREF_RECON.md`), *that*
finding could justify a real `SourceEngine` for it — a different
question, to be asked with different evidence, not assumed now.

## What was built (the smallest useful vertical slice)

- **`core/models.py`**: `EvidenceKind` (9 values, deliberately narrow —
  `SUPPORT_ENTRY`, `BIOS`, `FIRMWARE`, `DRIVER`, `MANUAL`, `SPEC_SHEET`,
  `PRODUCT_DATABASE`, `PRESS_RELEASE`, `OTHER`), `EvidenceProvenance`
  (`OFFICIAL_PRODUCT_DATABASE`, `OFFICIAL_SUPPORT`,
  `OFFICIAL_DOCUMENTATION`, `OFFICIAL_NEWSROOM`, `OFFICIAL_REGIONAL`,
  `HUMAN_CAPTURED`), `EvidenceItem`, `EvidenceRef`, `EvidenceDocument`.
- **`core/interfaces.py`**: the `EvidenceSource` protocol
  (`discover`/`fetch`/`extract`, mirroring `SourceEngine`'s shape
  deliberately — same review discipline, same bulk-inline-or-per-page
  freedom — without inheriting from it or sharing its contract).
- **`core/evidence_pipeline.py`**: `run_evidence_source()` — a small,
  separate pipeline (discover → fetch/extract → persist → conservative
  link → event). Deliberately **not** merged into
  `core/pipeline.py::run_source`: no snapshot/diff/severity-rule
  machinery applies to a fact that has no price or spec to diff.
- **`providers/sqlite/schema.sql` + migration v6**: `evidence_items`
  (append-or-update, deduped on `(source_id, external_id)`, a
  `content_hash` distinguishing a real change from a re-observation) and
  `evidence_links` (`evidence_item_id` → `product_key`, nullable —
  unlinked is a valid, expected, non-error state).
- **`evidence_sources/lenovo_psref/`**: the first real implementation,
  against the confirmed `ProductCategoryTree` endpoint. Real fixture
  (trimmed real capture), 13 tests.
- **Events**: `evidence_events` (schema v7). See the correction below —
  v0.1 wrote these into `change_events` and that was wrong.
- **Dashboard**: a top-level "Evidence" tab with its own filters, and a
  first-class detail page at `/evidence/{id}` (provenance, source,
  kind, timestamps, linked products, raw identifiers, raw payload). No
  graph UI, no redesign.
- **Real proof**: run once against live `psref.lenovo.com` into the real
  `data/radar.db` — 1,544 real evidence items persisted, all correctly
  `unlinked` (Lenovo has no tracked storefront products in this DB to
  correlate against — the expected, correct result, not a bug). A repeat
  run produced 0 new events (`unchanged`), proving the dedup/idempotency
  logic works against real data, not just fixtures.

## Correction (Stage 11.1): evidence is not a product alert

v0.1 emitted a `change_events` row per evidence observation, reusing
`ChangeType.SUPPORT_ARTIFACT_ADDED`/`_UPDATED`. The reasoning at the time
— "no second alert ecosystem, no enum explosion" — optimized for the
wrong thing. It was cheap in code and expensive in meaning.

What it actually produced, measured on the real DB: **1,544 of 3,465
change_events (44.6%) were evidence**, every one of them with a
synthetic `evidence:<source>:<id>` product key that resolves to no
product, so every card rendered blank and every detail page was a dead
end. Because they were the newest rows, they filled 300 of the 300
visible slots — the product-change stream, the one thing this dashboard
exists to show, was completely buried. They also inflated
`unreviewed_events`, `total_alerts`, and therefore the signal-rate
metrics the feedback loop is built on.

The three real defects, all downstream of one abstraction error:

| Consequence | Why it followed |
|---|---|
| Unopenable cards | `_latest_product_brief()` has nothing to return for a key that names no product |
| Corrupted metrics | every alert counter treats a `change_events` row as an alert |
| Buried signal | evidence outnumbered product changes and sorted newest-first |

An evidence observation says *an official source lists this*. A change
event says *a product this radar tracks has changed*. Those are
different claims with different consumers, so they get different tables:
`evidence_events` carries no severity, no notification, no review
outcome — because none of those concepts are meaningful for it. The
`SUPPORT_ARTIFACT_*` enum members remain (they predate Stage 11 and
describe a real *product* event: a support artifact appearing for an
already-tracked product) but nothing emits them today.

`core.models.PRODUCT_CHANGE_TYPES` / `EVIDENCE_CHANGE_TYPES` are now the
single definition of that boundary, so no query can re-list the type
strings and drift.

## Identity correlation — conservative by design, and a real bug it caught

Hierarchy implemented, in order: exact SKU, exact MPN (both matched
against `listings.vendor_sku` — this schema has no separate MPN column,
a documented simplification), exact model string (from the *real*
`NormalizedProduct.model` on each candidate listing's latest snapshot —
**not** `products.canonical_model`), explicit alias. No fuzzy matching
(explicitly out of scope for v0.1).

**A real identity bug was caught writing this stage's own tests**: the
first implementation compared evidence identity against
`products.canonical_model`, which stores `model_key()`'s coarse key —
built for *candidate surfacing* in `resolve_prior`, not confident exact
linking. "ThinkPad X1 Carbon Gen 12" and "ThinkPad X1 Yoga Gen 9" both
key to `thinkpad-x1` (the coarse key stops at the first digit-bearing
token, `x1`), which would have silently linked evidence for one product
to a completely different one. Caught by
`test_resolve_evidence_link_no_fuzzy_partial_model_match`, fixed by
comparing the real, exact `NormalizedProduct.model` string from each
listing's latest snapshot instead. This is the same class of bug Stage 8
found and fixed in `resolve_prior` itself (Samsung's SKU-disagreement
guard) — evidence linking needed the equivalent discipline from day one,
and now has it, with a regression test naming the exact failure mode.

## What was deliberately NOT built

- **No CLI wiring, no `config/oems/` schema for evidence sources.**
  `run_evidence_source()` is a real, tested, directly-callable function —
  proven against live data via a standalone script, not through
  `oem-radar run`. Evidence sources are conceptually distinct from
  storefront sources (Track 6's own framing), and forcing them into the
  same YAML schema/CLI flag surface before a second real implementation
  exists would be exactly the kind of premature generalization this
  project's engine bar exists to prevent.
- **No Discord delivery.** Events are real and persisted
  (`evidence_events`), but nothing enqueues to the notifier yet — and
  after Stage 11.1, nothing should until there is a *promotion* rule
  saying which evidence observation constitutes a product signal. The stage's own
  editorial-signaling guidance (don't alert on routine driver updates;
  do alert on a genuinely new model) needs real production experience
  this project doesn't have for any evidence source yet — exactly the
  gap Stage 9/10 found and closed for the product engines before trusting
  their signal. Wiring delivery before that experience exists would mean
  guessing at noise-suppression policy instead of measuring it.
- **A second real `EvidenceSource` implementation (HP).** The trigger
  needed 2 *confirmed* OEMs, not 2 *implemented* ones — same distinction
  this project has applied to every engine decision (`category_jsonld`
  was built once Samsung *and* Lenovo confirmed the shape; Lenovo itself
  wasn't implemented until the policy question was separately resolved).
  HP's category API is documented and real; building it is a Stage 12
  candidate, not a Stage 11 requirement.

## Provenance discipline

Every `EvidenceItem` carries one of six specific provenance values —
never a generic `OFFICIAL`. Lenovo PSREF is `OFFICIAL_PRODUCT_DATABASE`.
`HUMAN_CAPTURED` exists and is unused so far — reserved for the day an
owner's sanitized DevTools capture (`docs/OWNER_DEVTOOLS_GUIDE.md`)
becomes a real evidence item instead of a one-off finding in a recon doc.

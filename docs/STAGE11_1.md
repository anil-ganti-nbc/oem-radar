# Stage 11.1 — The Regression Fix

**Written 2026-08-08.** No new collectors, no new evidence sources, no new
reconnaissance. Stage 11 shipped three regressions that all trace to one
mistake: the UI was describing a data model that no longer matched the data.
This stage fixes the model, not the symptoms.

Tests: 419 → **444**. Schema v6 → **v7**. Collector count: **unchanged at 21**.

---

## Regression #1 — the OEM dropdown was still incomplete

### Root cause

Two layers, and Stage 10 only fixed the shallower one.

**The layer that was fixed (Stage 10):** the dropdown was built from
`DATA.events` — a `LIMIT 300` window — so an OEM whose changes had been
pushed off the page vanished from the filter. Stage 10 repointed it at
`DATA.manufacturers`.

**The layer that was not:** `manufacturers` is not a registry. It was a
*side effect of crawling*. `ensure_manufacturer()` was only ever called
inside `run_all`'s per-source loop, so an OEM existed in the DB only if a
crawl had reached it. Measured on the real DB: **25 rows against 28
configured OEMs**. Star Labs, Trigkey and VAIO — all present in
`config/oems/`, all enabled or recently added — did not exist as far as the
dashboard was concerned. No JS fix could have shown them; the data was not
there.

Compounding it: with the alert stream 100% evidence (regression #2), every
event card rendered with a blank manufacturer and the change-type filter
collapsed to a single option, which is what made the whole filter row look
broken rather than merely short.

### Fix — one writer, one reader

```
config/oems/*.yaml                     <- the authority
        |
        v
core.runner.sync_oem_registry(store)   <- THE ONLY WRITER
        |
        v
manufacturers table                    <- a projection, nothing more
        |
        v
dashboard.data.collect_oem_registry()  <- THE ONLY READER
        |
        v
render.js oemRegistry()                <- THE ONLY CLIENT-SIDE SOURCE
```

- `sync_oem_registry()` runs at the top of `run_all` (so a crawl registers
  every configured OEM, including ones that run will skip), and at dashboard
  startup in both entry points — `oem-radar dashboard` and
  `launch_dashboard.py`, the `.exe` — via `cli.sync_registry_before_serve()`.
  Best-effort: a locked or read-only DB logs a warning and still opens the
  dashboard.
- `collect_oem_registry()` is the single query. The filter dropdown and the
  Manufacturers tab both consume its output, so they cannot disagree.
- `oemRegistry()` is the single JS accessor. Both manufacturer `<select>`s
  (product filter, evidence filter) are filled from one computed option
  list — there is no second implementation to drift.
- The change-type filter got the same treatment: `DATA.change_types` is an
  unbounded `SELECT DISTINCT`, not a scan of the visible window.

**A real bug this uncovered, in the fix itself:** `ensure_manufacturer()`
never committed. `sync_oem_registry()` does nothing but call it and then
close the store — so every upsert was rolled back on close and the registry
stayed short, silently, with no error anywhere. Caught by writing
`test_registry_is_committed_not_rolled_back_on_close` (a *separate* reader
after close) rather than asserting through the same connection that did the
write. Fixed by committing in `ensure_manufacturer`; registering an OEM is
independent of any crawl transaction.

**Verified on the real DB:** 25 → **28 OEMs**, including all three that were
missing.

---

## Regression #2 — evidence flooding the alert stream

### Root cause

`run_evidence_source()` called `store.record_event()`. That is the whole
bug. Every evidence observation became a `change_events` row — i.e. a
product alert — carrying a synthetic `evidence:<source>:<id>` product key
that names no product.

Measured on the real DB before the fix:

| | count | share |
|---|---:|---:|
| `change_events` total | 3,465 | |
| — evidence | **1,544** | **44.6%** |
| — real product changes | 1,921 | 55.4% |
| Visible window (300 newest) | 300 | **100% evidence** |
| Evidence rows linked to a product | 0 | 0% |

Evidence was the newest data, so it filled every visible slot. The
product-change stream — the entire point of the dashboard — was buried
behind 300 Lenovo PSREF entries. It also inflated `unreviewed_events`,
`total_alerts` and every derived signal-rate metric.

The shortcut was taken for a defensible-sounding reason ("no second alert
ecosystem, no enum explosion — 2 values, not 50"). That optimized for cheap
code at the cost of meaning. An evidence observation says *an official
source lists this*. A change event says *a product this radar tracks has
changed*. Collapsing them made the second claim unfalsifiable.

### Fix

- `evidence_events` (schema v7): `evidence_item_id`, `event_type`
  (`added`/`updated`), `detected_at`, `meta_json`. **No severity column, no
  notification link, no review surface** — a test asserts the column set
  exactly, because the absence is the design.
- `run_evidence_source()` calls `store.record_evidence_event()`. It
  physically cannot reach `change_events` any more.
- `core.models.PRODUCT_CHANGE_TYPES` / `EVIDENCE_CHANGE_TYPES` /
  `EVIDENCE_PRODUCT_KEY_PREFIX` are the one definition of the boundary.
  `dashboard/data.py` builds a single `_PRODUCT_EVENTS_WHERE` predicate from
  them, used by the events query, the summary counters and the type filter —
  so the definition cannot drift between what is shown and what is counted.
- Defence in depth: that predicate excludes evidence-shaped rows *by query*,
  so a DB that hasn't migrated still reads clean. Tested.

---

## Regression #3 — dead cards

### Root cause

Direct consequence of #2. `collect_alert_detail()` calls
`_latest_product_brief(product_key)`, which returns `{}` for a key naming no
product. The alert page then rendered with every field blank and a review
form offering HIT/INTERESTING/NOISE/BUG for an object that has no editorial
claim to rate.

### Fix — evidence as a first-class entity (option B)

Evidence leaves the alert stream **and** gets a real detail page.

- `GET /evidence/{id}` → `collect_evidence_detail()` →
  `render_evidence_page()`. Also `GET /api/evidence/{id}` as JSON.
- The page exposes exactly what the brief asked for: provenance, source,
  evidence type, timestamps (published + observed), linked products (with
  correlation method and confidence), raw identifiers (external ID, SKU,
  MPN, content hash), and the full raw source payload.
- Prev/Next navigation across evidence items; links back to the Evidence
  tab and to the product alert stream.
- Every row in the Evidence tab links there. A test walks every rendered
  row and asserts each resolves — no row can render without a page.
- **No review form**, and the page says why: HIT/NOISE rates whether an
  *alert* earned your attention; an evidence record makes no such claim, and
  routing it through the review queue would corrupt the signal-rate metrics
  that queue exists to produce. `upsert_review()` on an evidence id raises
  (tested) rather than creating an orphan review row.
- Unlinked evidence explains itself instead of showing a blank: linking is
  exact-match only, and a guess would attach an official record to the wrong
  machine.

---

## Database assessment

### Current implementation (as shipped by Stage 11)

Evidence observations were inserted into `change_events` with
`change_type IN ('support_artifact_added','support_artifact_updated')` and
`product_key = 'evidence:<source_id>:<external_id>'`. `evidence_items` and
`evidence_links` were already correct and separate; only the *event* record
was collapsed.

**Pros**

- Zero new tables; one insert path.
- Automatically inherited the existing dashboard list, the review workflow,
  and the notification outbox.
- The `SUPPORT_ARTIFACT_ADDED` enum value already existed (unused, from the
  original M11 roadmap), so it read as reuse rather than invention.

**Cons**

- `change_events` stopped meaning one thing. Every consumer — dashboard
  counters, `feedback_analytics`, the outbox, the review queue — had to be
  taught an exception, or silently produce wrong numbers. All of them
  silently produced wrong numbers.
- 44.6% of the alert stream became rows that cannot be opened, cannot be
  reviewed, and have no product.
- The alert stream is sorted newest-first, and evidence arrives in bulk
  (1,544 rows from one PSREF call), so a single evidence run can bury the
  entire product feed indefinitely.
- `product_key` became a union type — sometimes a real key, sometimes a
  namespaced placeholder — which every downstream join has to know about.
- Severity was fabricated. `Severity.NOTABLE` was assigned to every evidence
  item because the column is `NOT NULL`, not because anything measured it.

**Migration options considered**

| Option | Verdict |
|---|---|
| **A. Leave it; filter in the UI** | Rejected. The UI would be correct and every metric still wrong. This is the "make the dashboard understand every object by pretending" path. |
| **B. Filter in queries, leave rows in place** | Rejected as the *only* measure — but kept as defence in depth. `_PRODUCT_EVENTS_WHERE` exists so an un-migrated DB reads clean. On its own it leaves a permanent trap for the next query someone writes. |
| **C. Delete the evidence rows** | Rejected. Discards real observation timestamps for no benefit. |
| **D. Move them into `evidence_events`** | **Chosen.** |
| **E. Rebuild the DB from scratch** | Rejected. Destroys 1,921 genuine product alerts and all crawl history to fix a table that can be corrected in place. |

**Migration required: YES — and justified.** It is a *move*, not a delete:
every row's `detected_at` and `meta_json` are preserved, keyed to its
`evidence_item` via the natural key parsed out of `product_key`. Nothing is
discarded. The justification is that option A/B alone leaves every alert
metric permanently wrong, and those metrics are what the Stage 9/10 feedback
work is built on.

**Verified on a copy of the real DB before touching the original:**

```
BEFORE  change_events 3465 (1544 evidence)  evidence_events    0   notifications 1921
AFTER   change_events 1921 (   0 evidence)  evidence_events 1544   notifications 1921
        product alerts preserved  1921 -> 1921   OK
        evidence moved, not lost  1544 -> 1544   OK
```

Then applied to `data/radar.db` with `data/radar.db.pre-stage11_1-backup`
taken first. Result matches the dry run exactly.

---

## UI changes

- **All changes** is explicitly *product changes only*, and says so.
- **Evidence** is a separate top-level tab with its own search, OEM filter
  and evidence-kind filter, its own count line, and rows that link to real
  detail pages. Default view is unchanged: Stories first, product changes in
  All changes, evidence never mixed in.
- Stats row separates **Product alerts** from **Evidence records** rather
  than reporting one inflated number.
- The empty state for a filtered OEM now distinguishes "pushed off the
  visible window by a bigger crawl" from "configured but never crawled" —
  the second is now a state a user can actually reach, since disabled and
  never-crawled OEMs appear in the filter.
- Overview nav gains an Evidence crumb.

---

## Regression tests added — `tests/test_stage11_1_regressions.py` (23)

Registry: complete before any crawl · includes disabled-source OEMs ·
idempotent · **committed, not rolled back on close** · independent of the
event window (`limit=0`) · independent of evidence · one JS helper, no
duplicate implementations · change-type filter not window-derived.

Evidence separation: no `change_events` written · excluded from default All
changes · excluded even on an un-migrated DB · summary counters count
products not evidence · migration moves rows without losing them.

Detail pages: every rendered row resolves · exposes all seven required
facts · no review form · links to `/evidence/` not `/alerts/` · route regex ·
unknown id is a clean miss.

Product side unaffected: alerts render and review normally · review workflow
rejects evidence ids · evidence filters are scoped to evidence.

Plus, in `test_evidence_fusion_pipeline.py`: `evidence_events` has no
severity column, `record_evidence_event` rejects unknown types, and the
three Stage 11 tests that asserted `change_events` behaviour now assert the
corrected behaviour.

---

## Stage 12 recommendation

The subsystem is now honest but inert: 1,544 real evidence records that
reach nobody. The open question Stage 11 deferred is now the blocking one —
**what promotes an evidence observation into a product signal?**

Concretely, and in this order:

1. **Wire evidence sources into `oem-radar run`.** They are currently only
   callable from a script. This is now safe to do, because a run can no
   longer flood the alert stream.
2. **Define promotion.** A new PSREF product with no matching tracked
   listing is arguably the most valuable signal this project has — a machine
   that exists officially and is not on any storefront yet. That deserves to
   become a real product alert, via an explicit rule with its own change
   type. A BIOS revision does not. Write the rule before the delivery.
3. **Only then, delivery.** Discord routing for promoted evidence, with the
   noise-suppression policy measured rather than guessed.

Do not implement the HP EvidenceSource first. A second source multiplies
whatever promotion semantics exist; getting those right on one source is
cheaper.

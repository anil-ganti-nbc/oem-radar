# Editorial Recall Audit — BANKAI (initial forensic baseline)

**Status: incomplete benchmark; production sources unchanged.** Written
2026-08-10 from the checked-in system, a read-only inspection of
`data/radar.db`, existing source reconnaissance, and deterministic offline
tests. Notebookcheck is not, and must not become, a Radar discovery source.

## Executive finding

OEM Radar is a robust catalogue-change monitor, but it has **unknown, almost
certainly low editorial recall** for the requested global laptop/mini-PC beat.
The denominator has not yet been assembled from independently reconstructed
primary sources, so a numerical recall claim would be fabricated. The main
structural causes are nevertheless clear:

1. The enabled production set has no enabled Lenovo, ASUS, Acer, HP, MSI, or
   Gigabyte/AORUS product source. Lenovo is deliberately disabled because its
   public listings return 403 to Radar's honest user agent; ASUS is a
   client-rendered Nuxt surface; Acer and HP were inconclusive/timeouts.
2. The system is overwhelmingly catalogue-first. Existing evidence sources
   (notably Lenovo PSREF) are deliberately stored as evidence only and are
   not wired into normal runs or promoted to product candidates.
3. A real generic event-model defect existed: engines retain configuration
   availability, while the diff previously compared only configuration keys.
   Thus an existing SKU moving preorder → in stock could produce no event.

The third cause is corrected in this change. The first two require measured
source work, not speculative scraper activation.

## Golden baseline

Before this change, `python -m pytest -q` completed with **508 passed** and
one non-product `PytestCacheWarning` caused by an existing Windows cache-path
conflict. `config/radar.yaml` confirms the active health policy:

| Policy | Value |
| --- | --- |
| unexpected zero | failure |
| minimum catalogue fraction | 0.35 |
| warn catalogue fraction | 0.70 |

The production SQLite database was read read-only: integrity check `ok`,
729 products, 1,910 product change events, 148 crawler runs, and no current
evidence rows. The database remains unmodified by this audit.

## Architecture and identity audit

The normal path is `cli/crawl_service` → `runner.run_all` → per-source
`pipeline.run_source` → normalized listing/snapshot → semantic diff →
severity rules → Discord outbox. SQLite stores immutable snapshots and uses
listing/product resolution to avoid URL-only identity. The system already
models manufacturer, source, listing, canonical product, configuration,
region (listing-level), snapshot, product change event, notification, review,
and a separate evidence item/link/event.

It does **not** yet model an editorial event as a first-class entity distinct
from a product change. That is why a known product in a new region, a new
official availability state, and a new configuration need carefully scoped
events rather than being treated as `new_product`.

Multi-agent drift found during inspection is documented but not refactored:

- `README.md` still names old modules and old test counts; runtime and current
  stage documents are more authoritative.
- `EvidenceSource` is production-proven in isolation but intentionally not in
  `run_all`; Stage 11.1 correctly separated it from the alert stream after a
  prior implementation polluted product metrics.
- Linux deployment examples assume an installed package while Windows scripts
  use `PYTHONPATH=src`. This is a real portability handoff item, but unrelated
  to the recall miss and not changed here.

## Event capability matrix

| Event type | Status | Evidence |
| --- | --- | --- |
| New product/new URL | Supported | normalized snapshots + `new_product` |
| Known family + new SKU/configuration | Partial | configuration keys are recorded; event is generic `spec_changed` |
| CPU/GPU/RAM/display changes | Supported | semantic component/spec diff |
| New region/retailer | Partial | region is recorded, but no dedicated regional-availability event |
| Announced → preorder | Supported when source exposes configuration availability | corrected generic diff |
| Preorder → available / unavailable → available | Supported when source exposes configuration availability | corrected generic diff |
| Price absent → price present | Partial | price-set diff exists; no dedicated editorial classification |
| Meaningful commercial bundle | Partial | description/configuration change only |
| Support/spec page before store launch | Evidence only | PSREF pipeline; no promotion policy |
| Regional product-page appearance/model aliases | Partial | resolver has regional-variant concepts, but no active mainstream regional source |
| Renamed/rebadged product | Partial | resolver/aliases can surface candidates; needs real corpus validation |

## Sources and regional blind spots

The enabled sources are primarily US/global storefront/catalogue engines. The
checked-in reconnaissance establishes these important gaps rather than
authorizing a workaround:

| OEM / region | Current state | Editorial implication |
| --- | --- | --- |
| Lenovo US | disabled: honest-UA 403 | high-yield mainstream gap; do not spoof |
| Lenovo PSREF | official evidence, not production-wired | potentially early model database evidence; promotion needs measurement |
| ASUS global/US | client-rendered Nuxt | source gap pending a lawful, stable public endpoint |
| Acer | repeated timeout/inconclusive | region/source gap not yet classified |
| HP | support category API confirmed, no product event source | evidence candidate, not promoted |
| MSI | hard 403 | source gap |
| Dell US | disabled after persistent 403 | source failure, intentionally not re-enabled |
| China (major OEMs) | no production CN source | region gap; JD/Tmall/Weibo require evidence and stability analysis |

## Confirmed known-miss status

The AOOSTAR mini-PC, ASUS Ryzen AI 9 H 465, Acer Ryzen 5 6600H, ASUS
Chromebook CX15, and 2026-08-10 Lenovo/ASUS/Acer examples are retained as
**unclassified benchmark leads**, not asserted facts. This repository does
not contain their source chains or offline captures, and no production
decision was made from a headline alone. The required next research pass must
record each article's primary source, timestamp, region, Radar state/event,
and source accessibility before assigning CAUGHT/LATE/CATCHABLE/SOURCE_GAP/
REGION_GAP/CAPABILITY_GAP/FILTERING_GAP/SOURCE_FAILURE/OUT_OF_SCOPE/AMBIGUOUS.

## Change implemented

`core.diff.diff()` now emits one `availability_changed` event for an existing
configuration whose non-unknown availability changes. The payload identifies
the stable configuration key and before/after availability. A transition to
`unknown` is deliberately silent because it normally means extractor data
loss, not a trustworthy commercial transition. Existing configuration-key
add/remove behavior is preserved.

This directly covers the event-model part of preorder opening, preorder →
available, and unavailable → available without changing source enablement,
health policy, deduplication, migrations, or Discord thresholds.

## P0/P1 remediation plan

1. **P0 — Build the real benchmark/replay corpus.** Reconstruct at least 50
   qualifying stories from primary sources, store only offline minimized
   fixtures and metadata outside the production DB, then calculate recall.
2. **P1 — Candidate promotion policy for official product databases.** Wire
   configured evidence sources only into experimental runs, and promote only
   new, current, official product-database records with a conservative
   candidate type and no automatic Discord delivery. Prove precision before
   production enablement.
3. **P1 — Regional availability identity.** Add a dedicated candidate for a
   known product first appearing in a new region, backed by exact model/SKU
   evidence. Do not conflate it with a new global product.
4. **P2 — Newsroom and regional source evaluation.** Prioritize sources only
   where the benchmark demonstrates yield; investigate ASUS China/Lenovo CN
   and regional retailer feeds before social scraping.
5. **P3 — social and marketplace discovery.** Consider only after a measured
   latency advantage and legal/operational review.

## Production status

**PRODUCTION SAFE:** the diff fix is additive, has deterministic regression
tests, and preserves source/health/notification policy.

**NOT PROMOTED:** no new source, regional surface, PSREF promotion, retailer,
social feed, Notebookcheck integration, migration, or production database
mutation.

**REQUIRES SOAK:** the configuration-availability event should be evaluated
through the existing review outcomes before tuning its notification severity.

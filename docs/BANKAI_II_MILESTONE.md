# BANKAI II — evidence-candidate milestone

The 50 rows in `EDITORIAL_BENCHMARK_2026_08.md` remain the frozen golden corpus. This document records implementation and reconnaissance after that audit; it does not revise any row or classification.

## Replay accounting

| Stage | Replayable editorial recall | Delta | Newly catchable |
|---|---:|---:|---|
| Frozen baseline | 0/50 | — | — |
| Existing enabled-store inspection | 0/50 | 0 | 0 independently useful alerts |
| PSREF review-only candidates | 0/50 | 0 | no historical publication timestamp / snapshot proving a corpus event |
| Regional availability candidates | 0/50 | 0 | no verified historic regional first-seen observation |

This deliberately does not count a current database record as proof that Radar would have caught a historical launch. Doing so would turn surviving catalogue inventory into a false replay result.

## Six current-source failures

The frozen `FILTERING_GAP` classification is retained. Production run records establish the more specific operational cause:

| Source | First successful run | Discovered / snapshots / events | Baseline events | Outbox state | Forensic classification |
|---|---|---:|---:|---|---|
| Chuwi | 2026-08-08 11:11 UTC | 30 / 20 / 20 | 20 | all suppressed | BASELINE_SUPPRESSED |
| GMKtec | 2026-08-08 11:11 UTC | 76 / 66 / 55 | 55 | all suppressed | BASELINE_SUPPRESSED |
| Minisforum | 2026-08-08 11:14 UTC | 51 / 47 / 47 | 47 | all suppressed | BASELINE_SUPPRESSED |
| Bosgame | 2026-08-08 11:10 UTC | 37 / 34 / 32 | 32 | all suppressed | BASELINE_SUPPRESSED |

The initial products completed fetch/discovery -> normalization -> resolution -> snapshot -> diff -> event -> Discord outbox. `baseline_quiet` marked every event `baseline: true`; the notifier recorded a `suppressed` outbox row rather than sending it. There is no observed extractor, identity, severity, or delivery failure in those initial runs. Minisforum later produced normal non-baseline events, confirming its post-onboarding delivery path can operate.

No retroactive alert is created: the database does not retain a mapping from these six independent articles to an exact historical listing snapshot, so claiming six catches would be unverifiable.

## Implemented experimental path

`EvidenceCandidate` is a review-only, deterministic output of the evidence pipeline. It supports `NEW_MODEL_EVIDENCE` for a current official product-database item with no exact product link, `NEW_CONFIGURATION_EVIDENCE` only where evidence carries an exact SKU, and `REGIONAL_PRODUCT_EVIDENCE` only where an exact known-product link and explicit region are both present.

Candidates are stored in associated `evidence_events.meta_json`, never `change_events`, never the notification outbox, and never normal catalogue health metrics. Withdrawn PSREF records cannot generate candidates. Repeating the same external ID is deduplicated by the evidence store, preventing repeat regional-candidate noise.

## Honest-access reconnaissance (2026-08-10)

Requests used the declared `OEMRadar/2.0` user agent and did not attempt a browser challenge, credential, or anti-bot bypass.

| Channel | Result | Decision |
|---|---|---|
| Lenovo US/CA/UK/AU/SG/MY/HK conventional sitemap paths | branded 404 responses | RESEARCH_ONLY; no presumed sitemap contract |
| Lenovo PSREF `ProductCategoryTree` | HTTP 200, public structured JSON | EXPERIMENTAL evidence source |
| ASUS global sitemap | HTTP 200 | RESEARCH_ONLY until product-only discovery, locale semantics, and fixtures are validated |
| ASUS India store sitemap | HTTP 403 | RESEARCH_ONLY; do not bypass |
| Acer sitemap | request timeout | RESEARCH_ONLY; failure isolated |
| JD | redirected to global homepage; no official-store identity validated | RESEARCH_ONLY; no marketplace crawl |

The evidence establishes only PSREF as a viable experimental candidate input. It does not establish a safe live regional Lenovo, ASUS, Acer, or JD discovery contract.

## Promotion state

- `PRODUCTION_READY`: existing production collectors only; no new BANKAI II source has been promoted.
- `EXPERIMENTAL`: Lenovo PSREF evidence candidates (no alerts or production metric impact).
- `RESEARCH_ONLY`: Lenovo regional storefronts, ASUS regional endpoints, Acer regional surfaces, JD official-store discovery.
- `HETZNER`: no deployment access or deployed commit was supplied; no server, scheduler, or production DB was touched.

## PSREF live-validation soak (2026-08-10)

An isolated temporary SQLite database was used for two consecutive live public
PSREF passes. The first pass discovered and stored 1,545 evidence items but
created only four candidates: ThinkPad X13 Detachable Gen 1, ThinkBook Plus G7
Auto Twist, ThinkCentre neo 50q Gen 7, and ThinkCentre neo 50a 24 Gen 7. The
second pass found all 1,545 unchanged and produced zero candidates. Both passes
created zero `change_events` and zero notifications.

The feed itself explains the filtering result: 952 records had `Withdraw=1`,
589 were current but `IsNewProduct=0`, and only four were current with
`IsNewProduct=1`. The official new flag therefore suppresses the 593-record
catalogue flood, but it is **not a publication timestamp**. The candidate
sample is too small and includes apparently old product identities, so no
HIT/INTERESTING/NOISE/BUG outcome or precision rate is claimed yet.

`scripts/psref_experimental_soak.py` provides a repeatable isolated pass. It
defaults to `data/experimental/`, is not in the normal runner or scheduler,
and has no notifier. Candidate records include source, type, model, exact
identity when exposed, first observation (the evidence event), novelty reason,
and deterministic dedup key.

## Baseline-quiet recovery design

The selected design is **C: review-only baseline candidates**, gated by a
source-provided `published_at` timestamp within 14 days. Missing, malformed,
naive, future, or old timestamps stay completely quiet. The pure, deterministic
implementation in `core/onboarding.py` neither changes the product pipeline
nor persists or delivers anything; integration awaits a real source with a
reliable timestamp and a separate candidate-review store.

## Revised Lenovo / ASUS reconnaissance

Lenovo's root `robots.txt` advertises a public sitemap index. That index links
official country shards, including CA, HK, MY, SG, GB, and US. The six sampled
shards returned HTTP 200 and contained 1,294–2,843 `/p/` product URLs each,
but none supplied `lastmod`. This is a viable **experimental baseline-then-
delta** discovery contract: establish a region-scoped URL baseline, then fetch
and verify only future new URLs. It must not be treated as dated launch data on
the initial import.

ASUS's public sitemap index contains 11,594 locale shards. Sample global,
China, and India shards returned HTTP 200 and include product URLs (72, 133,
and 44 laptop-path URLs respectively), but no `lastmod`. It is a promising
research-only baseline/delta input, not yet a candidate collector; category
filtering, product identity extraction, and locale-mirror deduplication need
fixtures before implementation.

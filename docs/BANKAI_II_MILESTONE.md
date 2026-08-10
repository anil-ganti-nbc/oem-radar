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

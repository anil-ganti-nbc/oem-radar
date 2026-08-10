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

## Lenovo regional sitemap delta collector

`experimental/lenovo_sitemap_delta.py` is a separate SQLite-backed collector,
not a source engine. It begins at seven benchmark-supported country shards
(US, CA, UK, AU, SG, HK, MY), accepts only laptop and desktop `/p/` URLs, and
normalizes query strings and trailing slashes. Its first successful regional
pass records a baseline only. Later successful passes compare URLs against the
region's retained known set; removals are ignored, and an empty or less than
35%-of-prior sitemap is a failed pass that cannot replace the baseline.

New URLs alone are not launches. Only those URLs are fetched; an explicit
Product JSON-LD identity (preferably an SKU) becomes a review-only candidate.
Same-run regional mirrors with the same SKU emit one candidate and are counted
as suppressed mirrors. An identity already known in another region becomes
`regional_page_appearance`, not a global product launch. There is no normal
database, `change_events`, notification, or Discord code path.

`scripts/lenovo_regional_sitemap_soak.py` runs the isolated collector on a
chosen cadence. Synthetic capability coverage is demonstrated for two frozen
Lenovo event types: a new-model regional product page and a regional first
appearance with explicit Product JSON-LD. This is mechanics coverage only,
not historical replay evidence.

### Live delta soak (2026-08-10)

Two consecutive polite live passes completed against all seven P0 regions.
The first established 6,349 laptop/desktop URLs and fetched no product pages.
The second completed with zero URL deltas, zero new-page fetches, zero
candidates, zero mirror suppressions, and zero region failures. Both passes
had exactly zero normal change events and notifications. This establishes only
that the contract is stable over the observed interval; it is not yet evidence
that Lenovo appends launches quickly enough for editorial lead time.

## ASUS regional sitemap delta collector

ASUS reuses the isolated experimental-store and successful-baseline semantics,
but has its own URL filtering and identity extraction. The first bounded scope
is **Global, China, and India**, using only each locale's first product shard
as a deliberately small seed. It accepts laptop/notebook/desktop/mini-PC paths
and excludes review, tech-specification, support, and marketing paths.
Identity prefers the public embedded SKU, then a normalized model heading / OG
title; URLs are only locators. Simultaneous same-SKU locale pages collapse to
one candidate.

Two live passes completed cleanly: the first baseline recorded 119 product URLs
and the second saw zero URL deltas, zero fetched pages, zero candidates, zero
failures, zero normal events, and zero notifications. This is not full ASUS
coverage: the index contains many shards and no lastmod; expanding scope awaits
observed candidate quality and locale-dedup evidence.

Both experiments can be run manually with their `*_soak.py` scripts. A
six-hour opt-in Windows task is provided in
`scripts/install_experimental_sitemap_soak_task.ps1`; invoking it with no
argument is a dry run, and it never changes the production hourly task. State
lives only under `data/experimental/` in separate Lenovo and ASUS databases.

## Shared-core decision

Lenovo and ASUS now share the experimental SQLite baseline, successful-run,
partial-collapse, first-seen, URL-delta, and candidate-dedup mechanics. The
OEM-specific sitemap topology, URL filtering, and page identity parsing remain
separate. This is sufficient shared core for two proven OEMs; a wider
`RegionalSitemapSource` refactor is deferred until a third OEM requires it.

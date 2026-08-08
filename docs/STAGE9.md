# Stage 9 — The Discovery Revolution

**Written 2026-08-07.** Stage 9's mandate was different from every prior
stage: not "find more real OEMs," but "make the platform better at
deciding what's worth building next than a human eyeballing a list."
Concretely, that meant investing in the *decision layer* — reconnaissance
intelligence, discovery quality scoring, benchmarking, and economics —
rather than adding collectors. Zero new engines were built. Zero new OEMs
were enabled. That is the expected, correct shape of this stage, not a
shortfall — see `docs/STAGE10_PROPOSAL.md`'s thesis for why.

## Phase 1 — Discovery framework re-check

Re-asked Stage 8's own question: should discovery become an independent,
engine-agnostic subsystem? The extraction trigger from
`docs/DISCOVERY_ARCHITECTURE.md` (a fifth engine reusing an existing
discovery mechanism with a different parser) still hasn't fired — no new
engine was built this stage at all. Addendum added to the existing doc
rather than a new one, since the answer and its reasoning are unchanged;
what's new is that Stage 9's actual discovery work (Phases 2-4, 6 below)
proved the leverage was in decision-quality, not code reorganization —
itself evidence for the "not yet" conclusion.

## Phase 2-4 — `oem-radar probe` becomes a reconnaissance analyst

`core/probe.py`'s `ProbeResult` gained a full evidence-backed report
layer: `confidence()` (0-100, tied to what evidence was actually
observed — a bulk API confirms platform identity far more than a bare
JSON-LD hint does), `evidence()` (plain-language lines, each traceable to
a specific field the probe measured), `known_risks()`,
`recommended_next_step()`, `missing_information()`,
`recommended_fixture_count()`, `recommended_engineer_time()`, and
`should_pursue()` (a bool + a cited reason). `discovery_quality()`
(Phase 3) is a 0-100 score with an itemized deduction list — every point
lost cites the specific observed evidence (anti-bot gate, missing
sitemap, JS-hydration with no server data, partial JSON-LD richness).
Nothing here is estimated from the OEM's brand/market position —
`cmd_probe`'s printed report says so explicitly ("not determined by a
static probe — requires human judgment"), consistent with the standing
principle (Stage 5-7) that editorial value is not something a static
fetch can measure. All of it is covered by `tests/test_probe_stage9.py`
(16 new tests, offline, deterministic).

## Phase 5 — Enterprise investigation: policy vs. engineering

Re-probed Lenovo, MSI, ASUS, Acer, and HP live, with the project's honest
UA, specifically to classify *why* each is inaccessible rather than just
confirm *that* it is. Findings (`docs/ENTERPRISE_OEM_ARCHITECTURE.md`
§16, folded into `docs/OEM_ATLAS.md` §5):

- **Lenovo** — policy-blocked only; the engineering question was already
  answered (Stage 8).
- **MSI** — hard technical block, fast 403 + challenge signature,
  unchanged since Stage 7.
- **ASUS** — reachable, Nuxt-hydrated, zero server data. Not blocked —
  a rendering gap whose only known fix (Playwright) is off-limits; the
  actually-missing step (a human checking devtools for a public API call)
  has never been done.
- **Acer** — silent read-timeout, now reproduced identically across three
  stages (7, 8, 9) at increasing timeouts (20s/25s/40s). Persistent
  enough to stop calling it "maybe unlucky network."
- **HP** — new finding this stage: the *domain root* is a clean 200 with
  no bot markers; only the catalog path times out, at both 20s and 60s.
  This narrows Stage 7/8's "the whole domain times out" into something
  more specific — a soft-throttle scoped to shop-shaped paths, not a
  general connectivity failure.

No collector was built for any of these — the deliverable was diagnosis,
per the phase's own instruction.

## Phase 6 — Discovery benchmark suite

`core/benchmark.py::benchmark_discovery()` runs a real engine's
`discover()`/`normalize()`/`validate()` against real captured fixtures
and measures time, requests, products found, duplicate refs, identity
quality, and validation-pass rate (a proxy for category/discovery
quality — a ref that fails `validate()` is exactly the false-positive
class discovery should avoid). `tests/test_discovery_benchmark.py`
benchmarks one real fixture per engine (Samsung, GMKtec, GEEKOM, Dell,
Khadas) and regenerates `docs/DISCOVERY_BENCHMARKS.md` on demand
(`UPDATE_BENCHMARK_DOC=1`). A real, honest artifact of this: Khadas's
validation pass rate came out 0.5 (1 of 2 real captured fixtures) because
one of the two captured pages is deliberately an accessory — exactly the
kind of result that proves the benchmark is measuring something real, not
producing a vanity number.

## Phase 7 — Collector economics

`docs/COLLECTOR_ECONOMICS.md` computed real per-engine LOC/tests/fixtures
(all 5 engines) and queried `data/radar.db` for real runtime signal
(shopify + dell only — the other three engines have zero rows in
`crawler_runs`, a real gap this document states rather than fills).
Found, live: `shopify` has the best-evidenced engineering ROI on both
axes this stage can measure. Found, unexpectedly: Dell's only 3 real runs
in local history all failed with a real `HTTP 403` from `dell.com` —
distinguished from a parsing defect using the same fixture that proves
the engine parses correctly, and using `run_errors`' captured message,
not assumption.

## Phase 8 — Engine/abstraction audit

Every shared helper (`core/textutil.py`, `core/jsonld.py`) was checked
against real consumer counts via a direct grep sweep, not memory. Zero
dead code found — every public function in `core/*.py` has at least one
real call site elsewhere in `src/oem_radar`. One function
(`extract_page_products`, one real consumer) was seriously considered for
demotion out of `core/` and deliberately kept, with the reasoning written
down (`docs/ENTERPRISE_OEM_ARCHITECTURE.md` §17) rather than either
reflexively splitting it or reflexively leaving it unexamined.

## Phase 9 — The OEM Atlas

`docs/OEM_ATLAS.md` consolidates every OEM this project has ever probed,
across Stage 3-9, into one document: engine, blocker, policy-vs-
engineering classification, and ranked future opportunity. Supersedes
`docs/OEM_ECOSYSTEM_MAP.md` as the canonical per-OEM reference.

## Phase 10 — The Stage 10 proposal

`docs/STAGE10_PROPOSAL.md` argues for three specific next moves (a human
devtools pass on ASUS, a wider Axiomtek sample, and real production
mileage for the three under-run engines) and explicitly rules out a new
engine, a discovery plugin system, Playwright, and further automated
Acer/HP probing — all with evidence gathered this stage, not asserted.

## Final state

370 tests passing (up from 349), 5 engines unchanged, 21 enabled sources
unchanged — Stage 9 added zero collectors on purpose. What changed is
what the platform can tell an engineer about a URL before they write a
line of code, and what it can now tell itself about its own economics and
abstractions.

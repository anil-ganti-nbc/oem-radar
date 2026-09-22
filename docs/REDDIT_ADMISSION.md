# Reddit discovery admission

Status: implemented for review; delivery blocked; no runtime promotion.

The shared primitive owns retrieval and transport representation only. Domain
classification, baseline, evidence, health, and delivery remain consumer-owned.
No new Clank, service, scheduler, or Motherclank responsibility is introduced.

## Repository evidence (2026-09-08)

- OEM Radar main `6e5b068`: `core/evidence_pipeline.py` and
  `providers/sqlite` already persist evidence separately from product changes.
  Community observations must use that boundary, never `NEW_PRODUCT`.
- Free Game Tracker main `011b89f`: `newsroom/models.py::NewsEvent` requires
  promotion terms; `database.py::sync_events` deletes absent offers;
  `notify.py` sends directly from the current diff. These are unsuitable for
  durable, unverified discovery observations. No durable outbox exists there.
- Semiconductor Intelligence's existing Reddit pilot is open PR #5,
  `reddit-pilot-m0-hardware`, not merged main. Preserve its source-local
  baseline/admission behavior; do not overwrite or implicitly promote it.
- Architecture main `e9c4a2b`: canonical v0.1/v0.2 and Fleet Laws preserve
  domain ownership, first-seen/novelty separation, provenance, observer-only
  supervision, and explicit promotion gates.
- Standards Clank: ratified STD-DATA-COM-002 requires read-side baseline
  exclusion; STD-OPS-COM-001/002 require honest invocation/outcome and yield
  distinctions. Empty standards directories are not implementations.

Initial community scope is GamingLaptops and MiniPCs for OEM Radar,
FreeGameFindings for Free Game Tracker, and GamingLeaksAndRumours for an
explicit gaming-rumour owner. No additional community is enabled.

Reddit publication time dates the submission, not a product launch or the
linked article. A permalink identifies an observation. Outbound links and
crossposts are provenance/relationship evidence, never permission to discard
distinct submissions. An unknown upstream original source stays unknown.


# Reddit discovery admission — review handoff

This change admits retrieval and durable discovery evidence, with collection
opt-in and editorial delivery structurally blocked. It does not claim live soak,
production promotion, verified Reddit access, or authoritative source resolution.

## Scope and ownership

- OEM Radar: r/GamingLaptops and r/MiniPCs through native evidence_items,
  evidence_events, crawler_runs, run locking, and its existing fetcher.
  Community provenance is explicit; no product model, NEW_PRODUCT, or outbox entry.
- Free Game Tracker: r/FreeGameFindings is domain-coherent. The recovered
  r/GamingLeaksAndRumours work is preserved separately pending an operator
  ownership decision; this OEM tranche does not claim it for FGT. Discovery is
  separate from offers.
- Semiconductor Intelligence PR #5 merged on 2026-09-09 from implementation
  head `5f843d8abce24a64315620296a5ca47044906cd7` as merge
  `a9a202ad82d6365890d49a34de75dceeac329762`. Its r/hardware source remains
  unregistered, polling remains disabled, and live soak has not started. Watch
  and other consumers can import the primitive later; no extra communities are
  enabled by this change.

## Why a discovery table is necessary in Free Game Tracker

At base 011b89f, NewsEvent requires promotion terms, sync_events deletes absent
items, and notify.py sends from transient RunDiff. None can represent an
unverified leak with durable history. The additive discovery_observations and
invocation/outcome discovery_runs tables reuse the same database, session scope,
Alembic runner and newsroom.lock. They are domain discovery records, not a
second Reddit delivery/baseline service. Existing giveaway semantics stay intact.
There is no durable outbox in this repository; delivery cannot be admitted by
merely unmuting or toggling collection. Building a new notifier was out of scope.

## Shared primitive

clank_reddit is an importable, dependency-free Atom transport package. The
canonical copy is oem-radar/src/clank_reddit; consumers pin adopted bytes by
version and SHA-256 in docs/REDDIT_TRANSPORT.json. This follows existing fleet
code-reuse practice without a new repo, runtime or installation service. Change
the canonical copy first; each consumer must explicitly adopt the new version,
update its manifest, and rerun tests in its own tranche. Semantic policy never
belongs in this package.

One bounded /new/.rss page is fetched per intake. HTTP failures, malformed feeds,
unexpected identity/scope, and empty Reddit listings fail closed. No short-circuit
cursor assumes feed ordering. Reordered/pinned posts are reconciled against
persistent observation IDs. Retrieval does not fetch arbitrary outbound links.
The HTTP transport remains consumer-owned; actual access requires a manual probe.

## State, novelty and duplicates

- First successful intake establishes the source baseline. Failure cannot admit
  a source. Baseline status stays attached to a record across edits and restarts.
- Every submission keeps its own identity. Repeated IDs do not replay; two posts
  linking the same article remain two pieces of evidence. Related URL keys remove
  only known tracking parameters and expose possible relationships, never assert
  that VideoCardz and another publisher are independent original sources.
- FGT exposes related observation IDs in its current view. These are hints, not
  cross-Clank merges or semantic duplicate decisions. No Reddit alerts are sent,
  so repeated aggregator links cannot multiply notifications during admission.
- Reddit timestamps date the submission. Linked-article publication and original
  source remain unknown unless present in evidence. Raw entry representations,
  outbound URLs, authors, run IDs and revision context are retained.
- FGT classification v1 distinguishes giveaway claims, game-rumour claims and
  unclassified/non-domain posts. Claims remain unverified. Keyword classification
  is deliberately conservative and needs real soak/editorial review before any
  delivery or broader claim of coverage.
- FGT's default discovery query excludes baseline and unclassified records.
  Explicit history inspection includes them without calling them novel.
- OEM evidence remains outside the product novelty stream at all times.

## Manual validation and rollback

Defaults are disabled: OEM radar.yaml reddit_discovery_enabled=false;
FGT NEWSROOM_ENABLE_REDDIT_DISCOVERY=false. To test after review, use an isolated
lane/database and the existing manual GUI collection controls, with collection
opted in. OEM uses reddit_min_interval_s (default 1800) and native source_due.
The existing hourly run fetches one admitted community per invocation,
alternating GamingLaptops and MiniPCs from the newest crawler_runs row
for those source keys. A failed or unfinished row still advances the turn.
No second scheduler is involved.
FGT shows both discovery sources in its existing source registry. Opening either
GUI/evidence view does not fetch Reddit. No scheduler was created or enabled.

Before any existing database upgrade, take a SQLite Connection.backup() snapshot
and verify PRAGMA integrity_check. The FGT migration is additive. Disable intake
and revert code for rollback while retaining discovery tables/evidence; its
schema downgrade deliberately refuses to delete evidence. Never reset a baseline
or remove runtime state to make a rollback work. This task used temporary test
DBs only; existing local and remote runtime DBs were not migrated.

Live soak, operator evidence review, and a durable/authorized delivery path are
still required before notification admission. Neither config flag grants it.
Do not deploy to Hetzner from this local work.

Coverage limit: the bounded 100-entry listing is not a historical backfill.
A long source gap can exceed its horizon; missing coverage must not be inferred
as no activity. Recovery/backfill and higher recall require a separate measured
admission increment. The existing r/hardware pilot is not expanded here.

## Validation performed locally

At implementation head `ec45c050942c6026ef56c9e3c434d386f380ed73`,
the targeted suite passed 14 tests and both required GitHub checks passed
(Linux tests/collection and Windows). Scoped Ruff and format checks passed. A
local full-suite repeat passed 670 tests with 1 skipped and encountered 3
Windows sandbox `DuplicateHandle` environment failures; an earlier same-code
run before the style-only formatting commit passed 673 tests with 1 skipped.
The repository-wide advisory Ruff scan retains 163 inherited findings.
Tests used Python 3.14 and temporary databases. GitHub CI targets Python 3.12.
Both built wheels contain byte-identical clank_reddit code. No live Reddit
collection, production database migration, deployment, or notification occurred.

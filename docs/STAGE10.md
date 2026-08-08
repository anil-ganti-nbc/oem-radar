# Stage 10 — The Blind-Spot Offensive

**Written 2026-08-07.** Stage 9 concluded there are currently zero known
OEMs simultaneously reachable, valuable, and blocked only by a missing
engine. Stage 10's mandate followed directly: close the remaining
uncertainty through human-assisted reconnaissance, production
validation, and alternate-evidence investigation — not by building more
collectors. `EvidenceSource` (the "Evidence Fusion" subsystem) was
explicitly gated behind real proof, not built speculatively.

## Track 1 — Production mileage

`sitemap_jsonld`, `woocommerce_store_api`, and `category_jsonld` had
strong test/fixture coverage but zero real rows in `data/radar.db`'s
`crawler_runs` (Stage 9's `docs/COLLECTOR_ECONOMICS.md` finding). Stage
10 ran all eight representative sources (Samsung, Khadas, LG, Medion,
SimplyNUC, GEEKOM, NovaCustom, Pine64) for real, using the normal
production runner (`oem-radar run`) against the real database, with a
Discord-webhook-free config copy so notifications queued as pending
rather than posting to the real channel — no dry-run, no fake history,
no bypassed validation. Every source's first crawl correctly triggered
`baseline_quiet` (real events recorded, zero sent). All 8 succeeded.

**Real results** (full table in `docs/COLLECTOR_ECONOMICS.md`): the
bulk-inline engines (`category_jsonld`, `woocommerce_store_api`) finished
in seconds (0.6s-22s). The per-page-fetch engine (`sitemap_jsonld`) took
8-69 minutes depending on catalog size under the real per-domain rate
limiter — Medion's 692-product catalog was the long pole. This is the
first time this project has measured that architectural tradeoff
(`docs/ENTERPRISE_OEM_ARCHITECTURE.md` §3) in real wall-clock minutes
instead of asserting it in the abstract. A bonus real finding: NovaCustom
and Pine64's Store API returns mostly non-laptop listings (269/275 and
211/213 correctly filtered as non-products) — exactly matching
`config/oems/novacustom.yaml`'s own pre-written comment predicting "6 real
current" models, live proof the `non_product_terms`/`category_include`
scoping mechanism works at production scale, not just against fixtures.

**Operational finding along the way**: two crawler_runs rows were found
stuck in `running` state from a tooling mistake early in this stage (a
bash-level timeout killed the wrapper script but not the underlying
crawl process, leaving the run lock and DB row orphaned) plus two
pre-existing stuck rows from earlier stages. All four were corrected to
`failed` with an explanatory `run_errors` entry rather than left to skew
future health/economics statistics silently. The first correction pass
introduced a second, smaller data-hygiene bug worth naming honestly: two
of the stuck rows had `started_at` timestamps from Aug 3-4 but were
stamped `finished_at='now'` (Aug 7), producing multi-day fake durations
that inflated `oem-radar coverage`'s average-crawl-duration metric to
~17,321s. Caught by actually reading the coverage output after the fix,
not assumed correct — corrected a second time to `finished_at=started_at`
(an explicit 0s placeholder, with the `run_errors` message updated to say
the real duration is unknown, not zero). Final average crawl duration:
**210.5s**, no longer distorted.

## Track 2 — ASUS human DevTools reconnaissance

Built `docs/OWNER_DEVTOOLS_GUIDE.md` — a step-by-step, no-engineering-
background-required procedure for capturing a sanitized record of
whatever public data endpoint (if any) a JS-hydrated storefront's
frontend calls. Built `oem-radar sanitize-har` (`core/har_sanitize.py`,
12 tests) to strip cookies, `Authorization`/CSRF/API-key headers, bearer
tokens, and session-shaped query/body fields from an owner's HAR export
before it's stored or shared, without requiring a HAR-analysis
subsystem.

**No actual owner DevTools capture was performed this stage.** This
project's own agent tooling includes a browser pane capable of rendering
pages and inspecting network traffic, and the option of using it directly
for this investigation was considered and deliberately declined: the
instruction was explicit that this is human-assisted reconnaissance, and
"do not automatically execute the page JS" reads as a constraint on the
investigating agent, not only on OEM Radar's collector codebase. ASUS
therefore remains classified `BLOCKED_JS` with the same evidence as
Stage 7/9 — reachable, Nuxt-hydrated, zero server-rendered product
data — and the guide is ready for whenever a human runs it.

## Track 3 — Axiomtek wide sample

Resolved decisively. A reproducible, stratified 31-page sample (up from
Stage 8's 8) across all 5 real Axiomtek catalog categories found Product
JSON-LD on 4 pages — **12.9%**, essentially identical to Stage 8's 12.5%.
Against a threshold defined *before* sampling (≥80% strong, 50-79%
partial, <50% reject), this is a clean, confident **reject** — not an
"almost." See `docs/AXIOMTEK_WIDE_SAMPLE.md`. No bespoke parser was
written.

## Track 4 — Alternate official evidence surfaces

Investigated Lenovo, HP, ASUS, MSI, and Acer's support/spec/documentation
surfaces as potential routes around their blocked or JS-hydrated
storefronts. Full findings in `docs/ALTERNATE_SOURCE_RECON.md`.

**Headline finding**: Lenovo's PSREF (`psref.lenovo.com`) exposes a real,
unauthenticated JSON API (found via reading its own published JS bundle
text, not executing it) returning 1,544 real products with stable
identifiers — completely independent of the blocked storefront, no
policy exception required. HP, ASUS, MSI, and Acer's alternate surfaces
were each blocked, JS-shell-gated, or (ASUS's Download Center)
inconclusive.

**The EvidenceSource trigger, defined before evaluating**: 2 OEMs with
useful enumerable data, or 1 OEM + 3 materially distinct evidence types.
Result: 1 OEM (Lenovo), 1 confirmed type. **Trigger not met.** Per the
stage's own instruction, this means stopping at reconnaissance and
documentation — `EvidenceSource` was not implemented, no schema changed,
no `docs/EVIDENCE_ARCHITECTURE.md` was written (writing one would
misrepresent a decision that was never made). See
`docs/ENTERPRISE_OEM_ARCHITECTURE.md` §18 for the architectural
reasoning.

## Bonus: a real dashboard bug, found by actually using the dashboard

Stage 10's own production runs exposed a real dashboard bug: the OEM
filter dropdown (`dashboard/render.py`) was populated from the
events *currently visible* in the (deliberately bounded, 300-row) recent-
events window rather than from the full manufacturer list. Once Stage
10's runs added ~1,000 fresh baseline events across two OEMs (LG,
Medion), those two OEMs alone filled the entire visible window, and the
OEM dropdown silently shrank to just those two — even though the real
database has 24 manufacturers. Fixed: the dropdown now lists every real
manufacturer, and picking one whose events have been paged out shows a
clear explanation instead of a misleading empty result. Also confirmed,
by reading the code and the real severity-rule config rather than
guessing: the "everything is 5 stars" and "filters don't seem to do
anything" observations were not bugs — `radar.yaml` hardcodes
`new_product` to severity 5, and Stage 10's runs were, correctly, almost
entirely first-ever baseline `new_product` events. Regression test:
`tests/test_dashboard.py::test_oem_filter_survives_events_being_paged_out`.

## OEM Radar Dashboard.exe

Also built during this stage (a direct user request, not part of the
original Track list): `launch_dashboard.py` + `build_dashboard_exe.cmd`
produce a standalone, double-click-to-launch `OEM Radar Dashboard.exe` in
the project root via PyInstaller — no separate Python install required.
Verified against a real build (schema.sql needed explicit `--add-data`
bundling; everything else is pure-Python and bundles automatically).
Rebuilt once, as `OEM Radar Dashboard (updated).exe`, to carry the OEM-
filter fix above without overwriting a copy the user had open live.

## Owner-probe backlog and small decisions

- `docs/OWNER_PROBE_BACKLOG.md` — a concise, per-OEM checklist (exact URL
  needed, what to check, command to run after) for TUXEDO, Slimbook,
  Insurgo, Supermicro Edge, Advantech, Neousys, and Portwell, replacing
  ad hoc re-probing of known-stale URLs.
- Gzip sitemap support: investigated whether any real candidate needs it
  (`docs/GZIP_SITEMAP_DECISION.md`). Only Dynabook was ever cited against
  this gap, and Dynabook's real blocker is stale content, not
  compression. **Left deferred** — no real consumer exists.
- `docs/archive/HANDOFF_2026-07.md` — the stale pre-feedback-system
  handoff doc, archived (moved, not deleted) now that
  `docs/CURRENT_STATUS.md` has been the live source of truth for five
  stages.

## Final state

See `docs/CURRENT_STATUS.md` for exact test counts and the closing
checkpoint report for full production-run numbers. Collector count is
unchanged at 21 enabled sources — Stage 10 succeeded by closing
uncertainty, not by adding collectors, exactly as its own definition of
success asked for.

# Enterprise OEM Architecture

**Status: blueprint, written Stage 6 (2026-08-07), updated Stage 7
(2026-08-07).** This document is the scaling plan for OEM Radar as it grows
from ~20 collectors today toward 50, then 100+. It does not replace
`docs/ARCHITECTURE.md` (the original design and its ADRs) — it extends it
for scale. Where the two conflict, the ADRs in `ARCHITECTURE.md` win;
nothing here overrides a standing architectural decision without saying so
explicitly.

The single organizing idea: **OEM Radar has never had an "OEM problem." It
has had, and will keep having, a small, closed set of *platform* problems.**
Twenty collectors today reduce to four engines (`shopify`, `sitemap_jsonld`,
`woocommerce_store_api`, and one deliberately isolated `dell`). The
evidence in `docs/OEM_PLATFORM_MATRIX.md` says the remaining candidates
reduce to the same families plus, at most, one or two more — not one
engine per OEM. Everything below is written to keep that ratio from
getting worse as OEM count grows, not to add ceremony for its own sake.

## 1. OEM ecosystem map

See `docs/OEM_PLATFORM_MATRIX.md` for the full, evidence-derived table.
Summary of the shape:

```
                    ┌─────────────────────────────────────┐
                    │         OEM Radar core               │
                    │  (pipeline, diff, store, notify,      │
                    │   feedback, dashboard — unchanged      │
                    │   regardless of OEM count)             │
                    └───────────────▲───────────────────────┘
                                    │  SourceEngine protocol
        ┌───────────────┬──────────┴──────────┬────────────────┐
        │                │                     │                │
   ┌────▼────┐    ┌──────▼───────┐      ┌──────▼──────┐   ┌─────▼─────┐
   │ shopify │    │sitemap_jsonld│      │    dell     │   │  (future) │
   │ engine  │    │   engine     │      │   engine    │   │ woocommerce│
   └────┬────┘    └──────┬───────┘      └──────┬──────┘   └───────────┘
        │                │                      │
   9 boutique OEMs   2 enabled, 2         1 OEM, isolated
   + VAIO/Morefine    confirmed-not-      deliberately
                       yet-enabled              │
                       (Medion, LG)        (see §9)
```

Every box under "core" is engine-count-invariant: the dashboard, feedback
system, health monitor, and automation stack do not grow in complexity as
OEMs are added, because they only ever see the shared `NormalizedProduct`/
`ChangeEvent` contract (`core/models.py`). This is already true today and
is the property this whole document exists to protect.

## 2. Engine map

| Engine | OEMs today | What it needs from a source | What it explicitly does NOT do |
|---|---|---|---|
| `shopify` | 12 (9 original + VAIO, Morefine, Star Labs) | A `/products.json` endpoint | No per-vendor branches; all filtering is `non_product_terms` config |
| `sitemap_jsonld` | 4 (SimplyNUC, Khadas, Medion, LG) | A sitemap (optionally an index) + `Product` JSON-LD on detail pages | No per-vendor branches; scoping is `url_include_pattern`/`url_exclude_pattern` config, denylist is `non_product_terms` config |
| `woocommerce_store_api` (Stage 7) | 3 (GEEKOM, NovaCustom, Pine64) | `/wp-json/wc/store/v1/products` (paginated) | No per-vendor branches; scoping is `category_include`/`category_exclude`/`non_product_terms` config |
| `category_jsonld` (Stage 8) | 1 enabled (Samsung), 1 confirmed-compatible-not-enabled (Lenovo) | A category/listing page whose HTML embeds a full `ItemList` of `Product` JSON-LD (nested-in-item or standalone-sibling — both real shapes seen) | No per-vendor branches; category page selection is `category_urls` config, SKU fallback is `sku_url_pattern` config |
| `dell` | 1 (Dell) | A static HTML catalog page with an embedded `ItemList` of `Product` JSON-LD | Deliberately not generalized — see §9 for why this is the one sanctioned exception, and why it stayed unmerged even after `category_jsonld` was built for the same general shape |

Adding a **13th Shopify OEM**, a **5th sitemap_jsonld OEM**, or a **4th
woocommerce_store_api OEM** should be — and today, verifiably is — a YAML
file plus a fixture capture. Adding a **5th reusable engine** should only
happen when a new platform family crosses the same "≥3 confirmed real
OEMs" bar the first three crossed. That bar is not a formality: Stage 6
found four platforms that *looked* like sitemap+JSON-LD candidates from
the outside (Razer, Eurocom, Falcon Northwest, ASRock Industrial) and had
zero real structured data on inspection; Stage 7 found the same pattern
again in the WooCommerce space (Protectli/Puget Systems had WooCommerce
hints but no working Store API) and, going the other direction, confirmed
a genuinely new opportunity (Samsung: real reachable JSON-LD data,
currently blocked only on a discovery-strategy investment, not on the bar
at all). The bar exists because both failure modes — false positives *and*
missed real opportunities — are real and have now been observed firsthand
across two stages.

## 3. Data flow

Unchanged from `docs/ARCHITECTURE.md`'s pipeline (`discover → fetch → parse
→ normalize → validate → resolve → snapshot → diff → score → outbox`) —
every engine, including both built this project and any built in the
future, is a plug into that exact same seven-stage pipeline. The one
degree of freedom engines have is **where the per-product fetch happens**:

- **Bulk-inline** (`shopify`, `dell`): `discover()` does one or a few
  requests and returns `ProductRef`s that already carry the full product
  payload (`inline_payload`). The pipeline skips the per-product fetch
  entirely. Cheapest in requests; only works when the platform has a bulk
  catalog endpoint.
- **Per-page fetch** (`sitemap_jsonld`): `discover()` is cheap (a handful of
  sitemap requests) but returns bare `ProductRef`s with no inline payload.
  The pipeline (`core/pipeline.py::run_source`) then fetches every product
  URL itself before calling `parse()`. More requests, but works on
  platforms with no bulk endpoint — which is most of them, per the platform
  matrix.

No third pattern has been needed. If a future platform family requires
something structurally different (e.g. a paginated REST API where a
"discover" pass and a "fetch full record" pass are the same call but with
different query params — WooCommerce's Store API is like this), it still
fits the bulk-inline shape: `discover()` pages through the API and inlines
each page's already-complete records.

## 4. Collector lifecycle

A source moves through exactly these states, and the state is visible in
one place — the descriptor's leading comment plus `enabled:` — not spread
across code:

```
NEEDS_OWNER_PROBE
      │  oem-radar probe <url> [--json]
      ▼
 (platform identified) ──────────────┐
      │                              │
      ▼                              ▼
BLOCKED_BOT / BLOCKED_JS / BROKEN   real fixture captured,
      │                              engine parses it correctly
   dead end unless a written          │
   Playwright justification           ▼
   is produced (see §13)        LIVE_VALIDATED, enabled: true
                                       │
                                       ▼
                              CATALOG_WARN/FAILURE_THRESHOLD
                              (runtime health, automatic —
                               see docs/OEM_COVERAGE.md and
                               CollectorHealthConfig)
```

`CANARY` and `LIVE_PARTIAL` are valid resting states, not just transitions
— see `docs/PLUGIN_GUIDE.md`'s status taxonomy. A source can sit at
`LIVE_PARTIAL` indefinitely (Medion, LG) if it has real confirmed data but
isn't scoped/complete enough to enable responsibly yet. That is a
deliberate, indefinite park, not a TODO.

## 5. Discovery strategy

Discovery strategies are per-engine, not per-OEM, and stay that way:

- `shopify`: `products_json` (bulk), optionally `sitemap` (catches
  unlisted/hidden listings — flagged `hidden=True` in `ProductRef`).
- `sitemap_jsonld`: sitemap index recursion (bounded by `max_sitemaps`),
  URL include/exclude regex, product-URL dedup. See §9 of
  `docs/STAGE6_RECON.md` for why "a sitemap with plausible product URLs"
  alone is not suficient evidence to enable a source — the sitemap only
  proves discovery works, not that the pages carry usable data.
- `dell`: static catalog HTML page(s), one JSON-LD `ItemList` per category.

**At 50+ collectors**, the discovery layer's only new work should be
*config* growth (more descriptors), never new discovery *code*, unless a
genuinely new platform family is confirmed via the same evidence bar. If
this stops being true — if engineers find themselves writing one-off
discovery code per OEM even inside an existing engine — that is the signal
the engine's config surface is too narrow and needs a new config knob, not
a new `if`.

## 6. Normalization strategy

Both reusable engines normalize into the exact same `NormalizedProduct`
(`core/models.py`) — this is non-negotiable and is what keeps the diff
engine, story detection, dashboard, and feedback system engine-agnostic.
Two normalization principles proven necessary this stage:

- **Never invent a value.** Unknown stays `None`/empty; `confidence`
  reflects how much of the listing was actually understood (see
  `sitemap_jsonld`'s confidence penalties for missing SKU/price).
- **Never trust vendor branding blindly.** `sitemap_jsonld` cross-checks
  JSON-LD's `brand.name` against the configured `manufacturer` and emits a
  non-fatal warning on mismatch (real example found this stage: SimplyNUC's
  own JSON-LD says brand `"SNUC"`, not `"SimplyNUC"`) instead of either
  overriding the configured manufacturer or silently ignoring the
  discrepancy. This is a template for future platform quirks: **surface as
  a validate() issue, never as a silent decision.**

## 7. Identity strategy

Per-engine, but converging on the same shape everywhere: `product_key =
f"{source.id}:{ref.handle or ref.url}"` (`core/pipeline.py`). Each engine
picks the strongest stable handle available on its platform:

- `shopify`: the Shopify `handle` (URL slug), backed by `vendor_sku` for
  resolution tie-breaking (`SqliteStore.resolve_prior`).
- `sitemap_jsonld`: the last non-empty URL path segment (e.g. `ee-1000`,
  `vim3`), backed by JSON-LD `sku`/`mpn` when present.
- `dell`: the Dell model code (`sku` in the catalog `Product` node).

No engine invents identity from unstable signals (page titles, position in
a listing). This is the one place where a platform's real-world messiness
(URL slug changes on a redesign, a product moved to a new category path)
will eventually cause a `product_removed` + `new_product` pair instead of a
clean rename — a known, accepted blind spot (§14), not a bug to chase for
every possible platform.

## 8. Fixture strategy

Unchanged policy, reinforced at scale by Stage 5/6 practice: every fixture
is a real, captured response, with provenance recorded in a
`PROVENANCE.md` next to it (`tests/fixtures/shopify/PROVENANCE.md`,
`tests/fixtures/sitemap_jsonld/PROVENANCE.md`) — OEM, URL, capture date,
what kind of response, and any real-world quirk the fixture exists to
pin down (e.g. Khadas's `Offers`/`Availability` casing). Hand-written
inputs are permitted **only** for parser-robustness tests (malformed JSON,
truncated XML) and must never be presented as if they were a real vendor
capture — see the convention note at the top of
`tests/test_sitemap_jsonld_engine.py`.

At scale this means: **a PR enabling OEM #51 must include a fixture capture
and a provenance line, or it doesn't merge.** This is already how Stage 5
and Stage 6 operated in practice; formalizing it here just makes it a
checked expectation instead of a habit.

## 9. Failure modes and the Dell exception

Three failure modes, each with a different response:

1. **Platform confirmed, data absent or wrong shape** (Razer, Eurocom,
   Falcon Northwest, ASRock Industrial — real catalogs, zero JSON-LD).
   Response: leave `CANARY`/`DISABLED_LOW_VALUE`. Do not force-fit into an
   existing engine's contract by adding vendor branches.
2. **Platform inconclusive from static probing** (ASUS, HP, Acer, Samsung
   — root/category pages show navigational JSON-LD only). Response:
   `NEEDS_OWNER_PROBE` for a real product-page fetch. Not a Playwright
   trigger by itself — see §13.
3. **Platform outright blocks bots** (Lenovo, MSI, Origin PC, Framework,
   Zotac — 403 + challenge signatures). Response: leave `BLOCKED_BOT`.
   This is the strongest of the three signals that static/API access has
   been genuinely exhausted for that specific source, but it is still a
   per-source finding, not a blanket "the enterprise tier needs
   Playwright" conclusion — Fujitsu and Panasonic in the same tier failed
   for an entirely different, non-technical reason (wrong URL).

**Why Dell stays a bespoke, unmerged engine**: Dell's catalog page embeds
an `ItemList` of `Product` nodes *inside one HTML page* (a listing page),
not one `Product` node per URL discovered via a sitemap. Folding Dell into
`sitemap_jsonld` would require the engine to understand "sometimes a
sitemap entry is itself a list of products" as a general case for a
pattern only one OEM has shown so far. Per Rule Zero, one OEM does not
justify a general case; per "no OEM-specific logic in reusable engines,"
the correct move was to leave Dell as its own tiny, isolated engine rather
than smuggle an `ItemList` special-case into the shared one. If a second
OEM is ever confirmed with the same "listing page embeds an ItemList of
Products" shape, *that* is the trigger to extract a third reusable engine
— not before.

**Stage 8 update**: that trigger fired. Samsung confirmed the same general
shape independently, and `category_jsonld` was built. Dell itself was
**deliberately not migrated onto it** — this is not an oversight, it's the
same isolation principle applied consistently. Dell's `_from_jsonld` also
has a text-anchor fallback path and Dell-specific silicon-extraction regex
tuned over two stages that `category_jsonld` has no equivalent need for;
merging them would mean `category_jsonld` growing a Dell-shaped special
case for a population of one, exactly the outcome this section already
argued against. The trigger for extraction was "a second OEM with the
shape," not "therefore also retrofit the first OEM onto the new code" —
those are different questions, and only the first one was actually asked.
One piece of genuine, non-aesthetic duplication *was* found and fixed
during this stage's Phase 9 review: both engines' identical two-line
`offers`-list-or-dict normalization, extracted to
`core/textutil.py::first_offer`. See `docs/STAGE8.md` §9.

## 10. Maintenance expectations

- **Per-OEM**: a config file (`config/oems/<name>.yaml`) and its fixtures.
  Expected drift: denylist gaps (Star Labs was one such case, fixed
  Stage 7), URL/category-scope gaps (Medion, NovaCustom, Pine64), and
  occasional identity-slug changes on a vendor redesign (§14). None of
  these require engine changes.
- **Per-engine**: `shopify`, `sitemap_jsonld`, and `woocommerce_store_api`
  should see very infrequent changes — the shared JSON-LD parser
  (`core/jsonld.py`) and the shared text/availability helpers
  (`core/textutil.py`, extracted Stage 7 after three engines had
  byte-identical HTML-stripping code) are the kind of code that, once
  correct, rarely needs to change again regardless of how many new OEMs
  use it. A change to either module should be rare enough that it's worth
  pausing on when it happens. Each engine's own denylist *term list*,
  by contrast, is expected to grow occasionally and locally — that's
  normal, not drift to worry about (see §6/§9's note on mechanism vs.
  policy).
- **Per-stage** (recon batches like Stage 5/6): expect roughly 15-25%
  of probed candidates to yield a real, enableable source; the rest split
  between "needs an owner probe" and "confirmed not a fit for any current
  engine." That ratio held across both stages and is a reasonable planning
  assumption for future batches.

## 11. Expansion strategy

1. Exhaust `NEEDS_OWNER_PROBE` candidates first — they are the cheapest
   possible next OEMs (evidence gathering, not engineering).
2. Grow existing engines' OEM count before building new engines. The bar
   for a new engine (§2) exists precisely so this ordering is enforced by
   evidence, not by whichever engine sounds most interesting to build.
3. When a platform family does cross the 3-OEM bar, design first
   (interface sketch + first-OEMs list + edge cases, as Stage 5 did for
   this exact engine before Stage 6 built it), implement second.
4. Never let "we found a promising sitemap" substitute for "we fetched a
   real product page and found real structured data." This is the
   single most expensive mistake to make at scale, because it is the one
   most likely to silently pass casual review — a sitemap with 6,000
   plausible-looking URLs *feels* like evidence.

## 12. Regional strategy

Not yet a solved problem, and this document does not pretend otherwise.
Observed regional behavior so far: HP and Samsung both auto-redirect to a
detected region (`.../in/`) which changes what's on the page; LG's India
business site had no price in its JSON-LD where a US consumer site might.
**Current policy**: each source config pins one region (`base_url` + an
explicit `region`/`currency_default` where the engine supports it, as Dell
does). Multi-region tracking of the *same* OEM is a distinct source per
region (e.g. a hypothetical `dell-us-laptops` + `dell-uk-laptops`), never a
single source that silently follows redirects into whatever region the
crawler's IP happens to geolocate to — that would make snapshots
non-reproducible, violating the immutable-snapshot principle in
`docs/ARCHITECTURE.md`.

## 13. Testing philosophy

Every reusable engine ships with, at minimum, the checklist in
`tests/test_sitemap_jsonld_engine.py` (31 tests) and
`tests/test_shopify.py`/`tests/test_oem_coverage_stage4.py`/
`tests/test_stage5_shopify_expansion.py` for `shopify`: discovery
(including index/nested/duplicate/malformed sitemap handling for
`sitemap_jsonld`), parse/normalize on real fixtures, every JSON-LD shape
variant (object/array/`@graph`/multiple nodes/missing fields/multiple
offers/case-quirks), HTTP-failure isolation (one bad URL doesn't sink the
source), health integration (`UNEXPECTED_ZERO`/catalog-collapse), baseline
quietness, and config wiring. Dashboard/feedback/analytics compatibility is
**not** re-tested per engine — those systems are proven engine-agnostic by
construction (they only ever see `NormalizedProduct`/`ChangeEvent`), and
re-testing that per engine would be exactly the kind of complexity growth
this document exists to prevent.

## 14. Expected signal quality

- **Shopify**: highest — full variant/price/image/availability data,
  proven across 12 OEMs.
- **sitemap_jsonld**: variable by vendor. Confirmed strong (Khadas: real
  price+availability), confirmed structurally-real-but-price-absent
  (SimplyNUC, LG), confirmed noisy (Medion, pending scoping). Expect this
  variance to continue — JSON-LD is a *convention*, not a contract, and
  different platforms implement different subsets of it correctly.
- **Dell**: strong on identity (model codes), weaker on exact silicon
  unless `deep_crawl` is enabled (documented cost/benefit trade-off already
  in `engines/dell/__init__.py`).

## 15. Known blind spots

Stated plainly, not hidden in a changelog:

- **No engine currently handles JS-hydrated product pages.** This affects
  the entire mainstream enterprise tier (Lenovo/ASUS/HP/Acer/MSI/Samsung)
  and is the most consequential blind spot in the platform today, in terms
  of editorial value left on the table. It is explicitly *not* being
  closed by adding Playwright without first exhausting whether any of
  these vendors expose a public JSON API their own frontend calls
  (`fetch()`/GraphQL endpoints visible in browser devtools — a static/API
  investigation, distinct from rendering the page) — that investigation
  has not yet been done and is the correct next step before a Playwright
  justification is even drafted.
- **No engine handles gzip-compressed sitemaps** (`sitemap.xml.gz`, seen at
  Dynabook in Stage 5). `HttpFetcher`/`FetchedDocument` model bodies as
  text; a `.gz` sitemap's raw bytes would need explicit decompression
  support that doesn't exist yet. Not needed by either enabled
  `sitemap_jsonld` OEM today; deferred until a confirmed real candidate
  needs it.
- **Identity is URL/slug-based**, so a vendor redesign that changes URL
  slugs will read as a `product_removed` + `new_product` pair instead of a
  rename, until/unless SKU-based resolution can override it (already true
  for `resolve_prior`'s SKU tie-break, but only when the vendor's SKU is
  actually populated — which several confirmed sources, e.g. SimplyNUC's
  server line, do not do).
- **No cross-region price comparison.** Each source is one pinned region
  (§12); OEM Radar does not yet correlate "this laptop is $200 more in the
  UK than the US" across sources.
- **`sitemap_jsonld`'s brand cross-check is advisory only** — it warns on
  mismatch but never blocks or auto-corrects. This is deliberate (§6) but
  means a genuinely misconfigured `manufacturer:` field in a descriptor
  will keep collecting under the wrong name until a human reads the
  validate() warning.

## Scale check

This document was written against ~14 enabled sources across 3 engines,
updated Stage 7 at ~20, and reviewed again Stage 8 at 21 sources / 5
engines with real evidence instead of projection:

- **`config/oems/`**: 28 descriptor files, linear growth confirmed —
  Samsung and Lenovo each added as one YAML file, no changes to any other
  descriptor.
- **`dashboard/data.py`**: every query already carries a `LIMIT` (checked
  directly this stage — recent events, recent runs, stories, review history
  are all bounded, 10-100 rows). Dashboard query cost does not grow with
  total OEM count, only with how many rows a human is looking at on one
  page. No change needed at 50 or 100+.
- **`core/metrics.py`**: `compute_coverage_metrics` and
  `compute_engine_stability` both do one full pass over `load_oem_configs()`
  — O(descriptor count), currently 28, trivially fast. Would need attention
  only in the thousands-of-descriptors range, far beyond this project's
  realistic ceiling.
- **The per-domain serial fetcher remains the one real, unresolved scaling
  question** — flagged since the original `HANDOFF.md`, unchanged this
  stage because it still isn't hurting at 27 configured OEMs (one slow
  domain delays only that domain's crawl, not the whole run, since crawls
  are per-source invocations). Becomes worth fixing when total crawl wall-
  clock time starts to matter operationally, not before.

At 100+, the same holds: `config/oems/` and `tests/fixtures/` keep growing
linearly, and no file in `core/` or `dashboard/` needs to change because of
OEM count alone — this stage found concrete evidence for that claim rather
than just repeating it.

## 16. Stage 9 Phase 5 — the Fortune 500 tier, re-investigated: policy vs. engineering

Stage 9 re-probed Lenovo, HP, Acer, ASUS, and MSI with the project's honest
declared UA (`core/probe.py::DEFAULT_UA`) — the same identity the collector
would use in production, never a spoofed browser UA — specifically to
answer *why* each is blocked, not just *that* it is. No new collector was
built; the mandate was diagnosis. Findings, live-verified this stage
(2026-08-07):

| OEM | What was observed this stage | Classification | Remaining obstacle |
|---|---|---|---|
| **Lenovo** | `/buy/us/en/*` category pages: real `category_jsonld`-compatible data, 200 with a spoofed browser UA, 403 with the honest UA. `lenovo.com/us/en/laptops/` (direct catalog nav): 403 (Akamai), reconfirmed this stage. | **Policy** (the engine exists and works; the only remaining gap is a refusal to spoof identity) | None technical — this is a decision already made and documented (`config/oems/lenovo.yaml`), not an open question |
| **MSI** | `msi.com/Laptops`: HTTP 403 with a bot-challenge signature, reconfirmed this stage, identical to Stage 7/8. | **Engineering** (no known non-spoof path found — pure technical block) | Whether any MSI subdomain/path exposes a public catalog API is still unknown; no owner-probe evidence either way |
| **ASUS** | `asus.com/us/laptops/`: HTTP 200, zero bot markers, Nuxt framework confirmed (`window.__NUXT__` present), zero Product JSON-LD — reconfirmed this stage, unchanged from Stage 7. | **Engineering, policy-adjacent** (the page is reachable — it's not blocked — but its content is a client-side-rendered payload; the only technique that would read it, Playwright, is explicitly off-limits by policy) | A human devtools check for a public `fetch()`/GraphQL call the Nuxt app itself makes has never actually been done — this is the concrete next step, not "wait for Playwright approval" |
| **Acer** | `acer.com/us-en/laptops` and even the bare root `acer.com/` both read-timeout at 20s, 25s, and 40s, reconfirmed this stage — the third stage in a row (Stage 7, 8, 9) this exact symptom has recurred. | **Engineering, infrastructure-class** (not a hard block — no 403, no challenge page, just silence) | Three-stage persistence makes "unlucky network conditions" less plausible than a standing IP-reputation-based throttle from this project's egress. Needs a probe from a genuinely different network/IP, or an owner-run manual check, before this can move past "inconclusive" |
| **HP** | `hp.com/` (bare root): HTTP 200, zero bot markers, zero framework, zero JSON-LD, no sitemap found, reconfirmed this stage. `hp.com/us-en/shop/laptops` (the actual catalog path): read-timeout at 20s and again at 60s, both this stage. | **Engineering, narrowed this stage** (previously recorded as "the whole domain times out" — that was imprecise; the domain is fine, only catalog-shaped paths stall) | This is new, more specific evidence than Stage 7/8 had: the failure is scoped to shop/catalog URLs specifically, which reads like a silent soft-throttle on paths that look like scraping targets, not a general connectivity problem. Still not a confirmed block (no explicit signature), so stays `Inconclusive`, but a *better characterized* inconclusive than before |

**The general pattern this reveals**: the "enterprise tier is JS-hydrated
and/or bot-blocked" framing from Stage 7/8 (§15's known blind spot) was
correct but coarse. Re-probing with intent to distinguish *why* surfaces
at least three distinct failure classes that each need a different
response, not one:

1. **Hard block, explicit signature** (MSI: fast 403 + challenge markers).
   Nothing to investigate further without a public-API check — the
   platform is actively defending itself and answering that quickly.
2. **Reachable but client-rendered** (ASUS: 200, real Nuxt payload, zero
   server data). Not a block at all — a rendering gap. The correct next
   step is a human checking network calls in a real browser's devtools,
   which is manual reconnaissance work, not automated probing, and hasn't
   been done yet for any of Lenovo/ASUS/HP/Acer/MSI.
3. **Silent stall, no signature** (Acer: total timeout, no error page at
   all; HP: timeout scoped to catalog paths only). This is the *least*
   understood class and the one most likely to be mistaken for "just try
   again" — three stages of reproducing the identical Acer symptom argue
   against that. A silent stall is not evidence of a wrong URL (unlike
   Stage 8's Insurgo/Supermicro findings) and not evidence of a hard block
   either; it needs a different diagnostic (different egress IP) that this
   project's current environment cannot supply.

None of the five are one construction-effort away from being collectors.
Lenovo's gap is closed except for the policy decision already made. The
other four are genuinely blocked on evidence this project cannot generate
from where it currently runs (a devtools-capable human, or a different
network path) — which is a materially different, more honest status than
"needs more engineering."

## 17. Stage 9 Phase 8 — engine/abstraction audit

Every shared helper in `core/textutil.py` and `core/jsonld.py`, plus every
engine's own denylist mechanism, was checked against its real consumer
count (grepped directly across `src/oem_radar`, not asserted from
memory):

| Abstraction | Real consumers | Verdict |
|---|---|---|
| `textutil.strip_html` | 4 engines | Earned |
| `textutil.contains_any` | 4 engines | Earned |
| `textutil.parse_schema_availability` | 3 engines | Earned |
| `textutil.first_offer` | 2 engines (`dell`, `category_jsonld`) | Earned — this is the exact Stage 8 Phase 9 extraction; still justified |
| `jsonld.extract_jsonld_nodes` | 2 consumers (`core/probe.py`, `sitemap_jsonld`) | Earned |
| `jsonld.extract_page_products` | 1 consumer (`category_jsonld`) | **Reviewed, kept** — see below |
| Each engine's `_DEFAULT_NON_PRODUCT` term list | 0 cross-engine consumers, by design | Correctly *not* shared — this is policy, not mechanism (§6/§9); sharing it would silently couple unrelated vendors' vocabularies |

A programmatic sweep (every public top-level function defined in
`core/*.py`, checked for at least one real call site anywhere else in
`src/oem_radar`) found **zero dead code** — every function this project
has built into a shared module is actually called by something. That is
itself a finding: past stages' discipline about only extracting mechanism
that already has ≥2 real consumers (rather than speculatively) has kept
the shared surface small enough that nothing has quietly rotted into an
unused abstraction.

**`extract_page_products` has exactly one consumer today** (`category_jsonld`)
and was the one candidate this audit seriously considered moving out of
`core/jsonld.py` and into the engine module itself, since "≥2 consumers"
is this project's own stated bar for shared code. Decision: **keep it
where it is.** The reason isn't "it might get a second consumer
someday" (the exact reasoning Stage 8/9 have repeatedly rejected
elsewhere) — it's that `extract_page_products` is built directly on top
of `extract_jsonld_nodes`, which already lives in `core/jsonld.py` with
two real consumers, and both functions solve the same class of problem
(walking JSON-LD shapes, not vendor policy). Splitting one JSON-LD-walking
function into `core/` and its sibling into an engine file would separate
two pieces of the same mechanism for no readability gain — the "≥2
consumers" bar exists to prevent *premature* extraction, not to force
already-correctly-placed code back out the moment a second consumer
hasn't shown up yet on a different axis. If `category_jsonld` is ever
retired without a second engine ever needing this function, moving it
inline at that point is a two-minute change — cheap to defer, not cheap
to guess incorrectly now.

No deletions resulted from this audit. That is a real outcome, not a
skipped step: the project's practice of gating new shared code behind a
real second consumer (Stage 6-8) has, empirically, prevented the kind of
speculative-abstraction accumulation this phase was designed to catch.

## 18. Stage 10 — alternate evidence surfaces and the EvidenceSource gate

Stage 10 investigated whether official surfaces *other than* a blocked
storefront (support portals, spec/BIOS/driver databases, documentation)
could route around the Fortune-500 blockers this project has held for
several stages. Full findings in `docs/ALTERNATE_SOURCE_RECON.md`;
summary here because it bears on architecture, not just OEM coverage.

**The headline finding**: Lenovo's PSREF (`psref.lenovo.com`) is a
public, unauthenticated, real JSON API
(`/api/ph/ProductCategoryTree`) returning 1,544 real products with
stable identifiers — found via reading the page's own published
JavaScript bundle text (static analysis of a fetched text file, not
executing it) and confirmed with a plain GET request. This is
independent of the blocked storefront and does not require any policy
exception.

**The architecture question this raises**: should this project build a
sibling `EvidenceSource` interface (alongside `SourceEngine`) for
alternate, non-storefront evidence with fundamentally different
semantics (a spec database entry is not a `NormalizedProduct` — it has
no price, no availability, no offer)? A conceptual sketch was considered
(discover/fetch/extract, an `EvidenceItem` model, a narrow evidence-kind
taxonomy, additive SQLite tables `evidence_items`/`evidence_links`,
reuse of `change_events` for alerts rather than a second alert system).

**Decision: not yet, and the reasoning is the same discipline this
document has applied to every engine decision since Stage 5.** The
pre-committed trigger (2 OEMs with useful enumerable alternate data, or 1
OEM + 3 materially distinct evidence types) was defined *before*
evaluating results, and the real evidence gathered — one OEM (Lenovo),
one confirmed evidence type (a product database), three other candidate
types blocked by the exact same UA-gating already declined as a spoofing
target — does not clear it. Building `EvidenceSource`, a new SQLite
schema, and a parallel alert pathway on the strength of one data point
would repeat the mistake this project's engine bar (§2) already exists
to prevent: architecture built on enthusiasm for a promising find,
instead of on a second independent confirmation. See
`docs/ALTERNATE_SOURCE_RECON.md` for the exact bar and what would need to
change it.

## 19. Stage 11 — the trigger fired: EvidenceSource v0.1

Stage 11 deepened Lenovo PSREF's own reconnaissance (`docs/PSREF_RECON.md`)
and found a **second** OEM: HP's `support.hp.com/wcc-services/prodcategory/
getProductCategoriesBySeoName` — a real, enumerable, stable-identity
product-category API, found the identical way PSREF's was (reading a
fetched JS bundle's own text). This satisfied the 2-OEM trigger §18 set
and left unchanged. See `docs/ALTERNATE_SOURCE_MATRIX.md` for the full
evidence table.

**The architecture question §18 deferred — SourceEngine or EvidenceSource
— was answered concretely, not by default.** Both confirmed surfaces give
identity + status/taxonomy, never price or confirmed specs. Forcing that
into `NormalizedProduct` would mean permanently-`None` fields across the
board, violating "never invent a value" the other direction (leaving
everything empty is its own kind of dishonesty about what the record
actually is). `EvidenceSource` was built instead — a real sibling
protocol (`core/interfaces.py`), not a lesser `SourceEngine`. Full
reasoning and what was/wasn't implemented: `docs/EVIDENCE_ARCHITECTURE.md`.

**Engine map is unchanged — this is not a sixth engine.** `EvidenceSource`
implementations (`evidence_sources/lenovo_psref/`, the only one built)
are a parallel concept, not an addition to the `engines` registry or the
5-engine count anywhere in this project's docs. Adding a real
`EvidenceSource` for HP later would not change the engine count either.

**Real production proof, not just fixtures**: `LenovoPsrefEvidenceSource`
ran once against live `psref.lenovo.com`, persisting 1,544 real evidence
items and events into `data/radar.db`; a repeat run produced zero new
events, proving the dedup logic against real data. See
`docs/COLLECTOR_ECONOMICS.md` for the numbers and
`docs/EVIDENCE_ARCHITECTURE.md` for a real identity bug this stage's own
tests caught and fixed before it could ship — the same class of coarse-
model-key collision Stage 8 found and fixed in `resolve_prior` itself.

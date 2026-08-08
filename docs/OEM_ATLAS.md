# OEM Atlas

**Status: institutional memory, written Stage 9 (2026-08-07).** This is
the single document meant to answer "what do we know about OEM X, and
why did we do what we did about it" without reading five stage reports.
It supersedes `docs/OEM_ECOSYSTEM_MAP.md` as the canonical per-OEM record
(the ecosystem map's confidence-tier tables are folded in below);
`docs/OEM_PLATFORM_MATRIX.md` remains the deeper narrative/evidence log
for platform-level patterns, and `docs/ENTERPRISE_OEM_ARCHITECTURE.md`
remains the architectural rationale document. This atlas is the index
that ties all three, plus every `STAGE*.md`, to one row per OEM.

Every claim below traces to a specific stage's real evidence (a fetch, a
fixture, a probe run) — see the "Stage" column and cross-reference the
named `docs/STAGE*.md` for the original finding if more detail is needed.
Nothing here is re-derived or guessed; this document only reorganizes
what earlier stages already established, plus Stage 9's own new
recon (§5 below).

## 1. Enabled, in production (21 sources / 27 OEMs configured)

| OEM | Engine | Region | Editorial value | Stage enabled |
|---|---|---|---|---|
| GMKtec, Minisforum, Beelink, AOOSTAR, Chuwi, Bosgame, NiPoGi, ACEMAGIC, KAMRUI | `shopify` | Global (CN mfg) | High — mini-PC/handheld category leaders | Stage 3-4.1 |
| VAIO, Morefine, Star Labs | `shopify` | JP / CN / UK | High (VAIO, Star Labs), Medium (Morefine) | Stage 5 / 7 |
| Dell | `dell` (bespoke) | US | High — mainstream brand | Stage 5 |
| SimplyNUC, Khadas | `sitemap_jsonld` | US / HK | Medium-High | Stage 6 |
| Medion, LG | `sitemap_jsonld` | DE / US | Medium (Medion), High (LG gram) | Stage 7 |
| GEEKOM, NovaCustom, Pine64 | `woocommerce_store_api` | CN / NL / community | High (GEEKOM), Medium (others) | Stage 7 |
| Samsung | `category_jsonld` | US | High — major global OEM, Galaxy Book line | Stage 8 |

## 2. Confirmed real, deliberately not enabled (policy, not a technical gap)

| OEM | Engine match | Blocker | Decision |
|---|---|---|---|
| **Lenovo** | `category_jsonld` (confirmed compatible — 64 real SKUs across 3 curated pages) | 200 with a spoofed browser UA, 403 with this project's honest declared crawler UA | **Will not enable.** Identity-spoofing to defeat UA-based bot detection is a permanent "never build" per `docs/OEM_ROADMAP_2027.md`. Reconfirmed Stage 9 with a fresh live probe — status unchanged. **Stage 10 addendum**: an independent, storefront-free signal was found instead — see §5a. |

## 3. Confirmed-not-a-fit (real fetch, no usable structured data)

| OEM | What was checked | Stage |
|---|---|---|
| Razer, Eurocom, Falcon Northwest, ASRock Industrial | Real sitemap + product pages, zero JSON-LD | Stage 5-6 |
| Qotom, BOXX, Velocity Micro, Winmate | Real sitemap + product pages, zero JSON-LD | Stage 8 |
| Protectli, Puget Systems | WooCommerce theme hints, Store API confirmed absent | Stage 7 |
| System76 | Real product pages, live price-configurator UI, zero JSON-LD | Stage 8 |

## 4. Confirmed-blocked (bot/WAF, real signature captured)

| OEM | Signature | Last reconfirmed |
|---|---|---|
| MSI | HTTP 403, Akamai/Cloudflare challenge | Stage 9 (live re-probe) |
| Lenovo (direct catalog nav, distinct from the `/buy/` pages in §2) | HTTP 403, Akamai | Stage 9 (live re-probe) |
| Origin PC, Framework, Zotac | HTTP 403, Cloudflare challenge | Stage 5 |
| Juno Computers | HTTP 418 (deliberate anti-bot status) | Stage 8 |

## 5. The Fortune 500 tier — Stage 9's policy-vs-engineering breakdown

Stage 9 re-probed the five highest-editorial-value blocked/inconclusive
enterprise OEMs specifically to classify *why*, not just confirm *that*
each is inaccessible. Full detail in `docs/ENTERPRISE_OEM_ARCHITECTURE.md`
§16; summary:

| OEM | Failure class | Policy or engineering? | What would actually move this forward |
|---|---|---|---|
| Lenovo | UA-gated (200 spoofed / 403 honest) | **Policy** — decision already made | Nothing technical left to try; this is closed |
| MSI | Hard block, fast 403 + challenge signature | **Engineering** (no known non-spoof path) | A confirmed public catalog API check (none found yet) |
| ASUS | Reachable (200), Nuxt-hydrated, zero server data | **Engineering, policy-adjacent** (rendering gap; Playwright is the only known fix and is off-limits) | A human devtools check for a public `fetch()`/GraphQL call — never actually done |
| Acer | Silent read-timeout, reproduced identically across 3 stages (7, 8, 9) | **Engineering, infrastructure-class** | A probe from a different network/IP, or an owner-run manual check |
| HP | Root reachable and clean; only the catalog path (`/us-en/shop/laptops`) times out, reproduced twice this stage | **Engineering, narrowed this stage** | Same as Acer — this project's current egress can't generate more evidence here |

## 5a-2. Evidence Fusion v0.1 — Stage 11

Stage 11 re-investigated PSREF in depth (`docs/PSREF_RECON.md`) and found
a **second** OEM with the same architectural shape: **HP**'s
`support.hp.com/wcc-services/prodcategory/getProductCategoriesBySeoName`
— a real, unauthenticated, enumerable product-category API (18 real
laptop sub-brands, stable `oid`/`uid` identifiers), found the same way
PSREF was (reading a fetched JS bundle's own text). This satisfied the
pre-committed 2-OEM trigger (`docs/ALTERNATE_SOURCE_MATRIX.md`), and
`EvidenceSource` v0.1 was built — see `docs/EVIDENCE_ARCHITECTURE.md` for
the full architecture decision (alternate catalogs vs. supporting
evidence) and what was/wasn't implemented.

**Real result**: a working `LenovoPsrefEvidenceSource` ran once against
live `psref.lenovo.com`, persisting 1,544 real evidence items and 1,544
real `SUPPORT_ARTIFACT_ADDED` events into `data/radar.db` — all correctly
`unlinked` (Lenovo has no tracked storefront products in this project to
correlate against, the expected result). A repeat run produced zero new
events, proving the dedup logic against real data. HP's confirmed API was
**not** separately implemented this stage — the trigger needed 2
confirmed OEMs, not 2 built integrations, matching how every prior engine
decision in this project has worked.

## 5a. Alternate official evidence surfaces — Stage 10 Track 4

Investigated whether official surfaces *other than* a blocked storefront
(support portals, spec databases, driver/BIOS indexes) could route
around the Fortune-500 blockers. Full detail in
`docs/ALTERNATE_SOURCE_RECON.md`. Headline finding: **Lenovo's PSREF
(`psref.lenovo.com`) exposes a real, unauthenticated, enumerable JSON API**
(`/api/ph/ProductCategoryTree` — found via reading the page's own
published JS bundle text, not executing it) returning **1,544 real
products** with stable `ProductID`/`ProductKey` identifiers, completely
outside the blocked storefront and its UA-gating. HP/ASUS/MSI/Acer's
support surfaces were each blocked, JS-shell-gated, or inconclusive — no
comparable finding for any of them yet.

This is real, striking evidence, but it is **one OEM with one confirmed
evidence type** — short of the pre-committed bar (2 OEMs, or 1 OEM + 3
types) for building an `EvidenceSource` subsystem. Decision: **do not
build it yet** — see `docs/ALTERNATE_SOURCE_RECON.md`'s verdict. PSREF
remains the single most promising unexploited lead in this atlas for a
future stage.

## 6. Confirmed-requires-JS (page ships client-rendered payload, not data)

| OEM | Evidence |
|---|---|
| ASUS | `window.__NUXT__=(function(...){...})(...)` — reconfirmed Stage 9 |
| OnLogic | Next.js; sitemap has only 51 locale-variant URLs of a product-finder tool, no product-detail pages indexed |
| Kontron | Nuxt-hydrated, zero JSON-LD on root |
| System76 | See §3 — configurator UI, not a static-vs-JS question so much as no data model exists statically at all |

## 7. Rejected with decisive evidence (Stage 10 wide sample)

| OEM | Evidence | Verdict |
|---|---|---|
| Axiomtek | Stage 8: 1/8 sampled pages had real Product JSON-LD (12.5%). **Stage 10 wide sample: 4/31 pages across all 5 real catalog categories (12.9%)**, using a reproducible stratified selection (every Nth URL per category, sorted) — see `docs/AXIOMTEK_WIDE_SAMPLE.md`. Pre-committed threshold (defined before sampling): ≥80% strong candidate, 50-79% `LIVE_PARTIAL`, <50% reject. | **Rejected for the generic JSON-LD engine, decisively** — the wide sample confirms Stage 8's ratio wasn't an unlucky small sample; 12.9% is a stable, real ceiling for this catalog, not statistical noise. Parked, not pursued further. Do not write a bespoke Axiomtek parser — see the constraint against building one for a single vendor at 13% coverage. |

## 8. Inconclusive / needs a different diagnostic

| OEM | Failure mode |
|---|---|
| Advantech, Neousys | No sitemap found anywhere checked |
| TUXEDO | No sitemap; nav has no direct model links; robots.txt implies a storefront path not yet located |
| Slimbook | Sitemap intermittently 500s |
| Portwell | TLS certificate chain fails verification — broken infra, not a bot block |
| Insurgo | DNS resolution fails entirely for the known subdomain — likely stale URL |
| Supermicro Edge | Known URL 404s — wrong path, not evidence about the platform |

## 9. Wrong target / stale / structurally broken

Panasonic Toughbook and Fujitsu (corporate sites, not storefronts),
Dynabook (sitemap resolves, content is Windows-8.1-era abandoned),
Purism (~3 real product URLs in a blog-dominated sitemap, no JSON-LD),
Trigkey (real Shopify theme, store suspended — HTTP 402).

## 10. Undetermined (never probed with a real fetch)

TUXEDO's actual storefront path, Shuttle, Maxtang, LattePanda, MeLE,
AYANEO, Firebat, Peladn, GPD, Kingnovy — carried forward unchanged since
`docs/OEM_PLATFORM_MATRIX.md`; no stage has re-probed these yet.

## 11. Architectural decisions this atlas depends on

- **The 3-confirmed-candidate bar for a new engine** (Stage 5) — why
  `category_jsonld` exists but nothing has been built for GraphQL or a
  hypothetical "search endpoint" family yet (zero confirmed real
  candidates for either, per `docs/DISCOVERY_ARCHITECTURE.md`).
- **The Dell exception** (Stage 5, updated Stage 8) — why Dell stays
  bespoke even after `category_jsonld` generalized its shape for Samsung;
  see `docs/ENTERPRISE_OEM_ARCHITECTURE.md` §9.
- **No identity-spoofing, ever** (discovered Stage 8, applied to Lenovo,
  reconfirmed Stage 9) — the single decision blocking the highest-value
  known-real opportunity in the atlas.
- **No Playwright/browser automation** — the standing constraint blocking
  ASUS, OnLogic, Kontron, and System76's configurator, all of which have
  real data behind client-side rendering this project cannot see.
- **Mechanism vs. policy sharing** (Stage 7, re-affirmed Stage 9 Phase 8)
  — why denylist term lists stay per-engine while `strip_html`/
  `contains_any`/`first_offer`/`parse_schema_availability` are shared.

## 12. Future opportunity, ranked by what's actually missing (updated Stage 10)

Stage 10 closed two of Stage 9's four open items with decisive evidence
(Axiomtek: rejected, 12.9% wide-sample coverage; production mileage: see
`docs/COLLECTOR_ECONOMICS.md`) and produced one major new lead (Lenovo
PSREF). What's left:

1. **A human DevTools pass on `psref.lenovo.com` AND ASUS** — both listed
   with exact instructions in `docs/OWNER_PROBE_BACKLOG.md`'s new
   DevTools section. `PENDING_OWNER_ACTION` on both; three stages running
   now confirm no further automated probing will move either forward.
2. **A second real `EvidenceSource` implementation (HP)** — confirmed
   real and enumerable (`docs/ALTERNATE_SOURCE_MATRIX.md`), not yet
   built. The trigger needed 2 confirmed OEMs, not 2 built integrations;
   a natural Stage 12 candidate now that the pattern (`evidence_sources/`,
   the pipeline, the schema) already exists.
3. **Correct entry URLs for Advantech/Neousys/TUXEDO/Slimbook/Insurgo/
   Supermicro** — see `docs/OWNER_PROBE_BACKLOG.md` for the exact ask per
   OEM. Cheap once a human supplies the real current URL.
4. ~~Real production runs for `sitemap_jsonld`/`woocommerce_store_api`/
   `category_jsonld`~~ — **done Stage 10**. ~~Find a second alternate-
   evidence-source OEM~~ — **done Stage 11 (HP)**. See
   `docs/COLLECTOR_ECONOMICS.md` and `docs/ALTERNATE_SOURCE_MATRIX.md`.

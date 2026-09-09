# OEM Coverage Matrix

Last audit: **2026-09-09** (handheld expansion M1 — six staged Chinese
handheld sources, Sixunited classified `NEEDS_ENGINE`, GPD/FEVM holds;
see "Fixture-ready, not yet enabled" and the recon tables below. Prior
audit 2026-08-07, Stage 9 — see `docs/STAGE9.md`, plus
`docs/STAGE8.md`/`docs/STAGE7.md`/`docs/STAGE6_RECON.md`/
`docs/STAGE5_RECON.md` for prior batches and `docs/OEM_ATLAS.md` for the
current flat planning table across all stages — supersedes
`docs/OEM_ECOSYSTEM_MAP.md` — or `docs/OEM_PLATFORM_MATRIX.md` for the
deeper ecosystem narrative). Stage 9 enabled zero new sources on purpose
— see `docs/STAGE9.md`/`docs/STAGE10_PROPOSAL.md`; the enabled-sources table below is
unchanged from Stage 8.
**For a live, always-current count run `oem-radar coverage`** — the table
below is a point-in-time snapshot and will drift as OEMs are added. Status
codes:

`LIVE_VALIDATED` · `LIVE_PARTIAL` · `CANARY` · `NEEDS_OWNER_PROBE` · `BLOCKED_JS` · `BLOCKED_BOT` · `BROKEN` · `DISABLED_LOW_VALUE`

## Enabled sources

| OEM | Source ID | Region | URL | Platform | Engine | Status | ~Catalog | Discovery | Signals | Missing | Fixture | Notes |
|-----|-----------|--------|-----|----------|--------|--------|----------|-----------|---------|---------|---------|-------|
| Dell | dell-us-laptops | US | dell.com | static HTML | dell | LIVE_VALIDATED | model list | catalog HTML | model, CPU, price | GPU sparse | existing | Big-brand engine |
| MINISFORUM | minisforum-shopify | US | store.minisforum.com | Shopify | shopify | LIVE_VALIDATED | — | products_json+sitemap | full Shopify set | — | existing | |
| GMKtec | gmktec-shopify | US | gmktec.com | Shopify | shopify | LIVE_VALIDATED | — | products_json+sitemap | full | — | gmktec_products.json | |
| Beelink | beelink-shopify | US | bee-link.com | Shopify | shopify | LIVE_VALIDATED | — | products_json+sitemap | full | — | existing | |
| AOOSTAR | aoostar-shopify | US | aoostar.com | Shopify | shopify | LIVE_VALIDATED | — | products_json+sitemap | full | — | existing | |
| Chuwi | chuwi-shopify | US | us.chuwi.com | Shopify | shopify | LIVE_VALIDATED | — | products_json+sitemap | full | — | existing | us.chuwi.com only |
| **Bosgame** | bosgame-shopify | US | bosgame.com | Shopify | shopify | **LIVE_VALIDATED** | ~37 | products_json+sitemap | title,CPU,RAM,SSD,price,images | region sparse | bosgame_products_p1.json | Enabled 2026-08-02 |
| **NiPoGi** | nipogi-shopify | US | nipogi.com | Shopify | shopify | **LIVE_VALIDATED** | ~15 | products_json+sitemap | full mini-PC | small catalog | nipogi_products_p1.json | Enabled 2026-08-02 |
| **ACEMAGIC** | acemagic-shopify | US | acemagic.com | Shopify | shopify | **LIVE_VALIDATED** | ~46 | products_json+sitemap | AI/mini-PC | accessories present | acemagic_products_p1.json | **New OEM** 2026-08-02 |
| **KAMRUI** | kamrui-shopify | US | kamrui.com | Shopify | shopify | **LIVE_VALIDATED** | ~60 | products_json+sitemap | mini-PC | accessories possible | kamrui_products_p1.json | Enabled Stage 4.1 2026-08-02 |
| **VAIO** | vaio-shopify | US | us.vaio.com | Shopify | shopify | **LIVE_VALIDATED** | 8 (of 165; 157 are Warranty SKUs, auto-filtered) | products_json+sitemap | model, CPU family, RAM/SSD, price, images | small catalog | vaio_products_p1.json | **New OEM**, Stage 5 2026-08-07 |
| **Morefine** | morefine-shopify | US | www.morefine.com | Shopify | shopify | **LIVE_VALIDATED** | 32 (of 40; 8 filtered — 2 shipping-protection via config, 6 accessories via built-in denylist) | products_json+sitemap | mini-PC, CPU, eGPU docks | — | morefine_products_p1.json | Re-enabled Stage 5 2026-08-07 — old `base_url` (`store.morefine.com`) was stale/unreachable |
| **SimplyNUC** | simplynuc-sitemap | US | snuc.com | WordPress/WooCommerce | **sitemap_jsonld** (new engine) | **LIVE_VALIDATED** | 137 URLs, most real | product-sitemap.xml + JSON-LD `@graph` | model, sku/mpn, description, images | pricing mostly "$0/quote" placeholder across this vendor | simplynuc_product_ee1000.html + 2 more | **New engine + new OEM**, Stage 6 2026-08-07 |
| **Khadas** | khadas-sitemap | Global | www.khadas.com | Wix Stores | **sitemap_jsonld** | **LIVE_VALIDATED** | 78 URLs (SBCs + accessories) | store-products-sitemap.xml + JSON-LD | model, real price/currency/availability | no sku/mpn on products checked | khadas_product_vim3.html + 1 more | **New OEM**, Stage 6 2026-08-07 — real Product JSON-LD but with non-standard `Offers`/`Availability` capitalization, handled via case-insensitive field lookup |
| **Star Labs** | starlabs-shopify | GB | starlabs.systems | Shopify | shopify | **LIVE_VALIDATED** | 19 (of 111; 92 filtered — spare parts, OS licenses, recovery media via an expanded config denylist) | products_json+sitemap | model, CPU-family variants (StarBook/StarFighter/StarLite incl. Privacy editions) | catalog dominated by direct spare-parts sales | starlabs_products_p1.json | **New OEM**, Stage 7 2026-08-07 |
| **Medion** | medion-gaming-sitemap | DE | www.medion.com | Custom (SAP-style) | sitemap_jsonld | **LIVE_VALIDATED** | ~680 (of 6,265; scoped via `url_include_pattern` to ERAZER gaming lines only) | Product sitemap + JSON-LD | model, mpn, real EUR pricing | entry-level/multimedia lines deliberately excluded (see docs/STAGE7.md) | medion_product_erazer_x17805.html | **New OEM**, Stage 7 2026-08-07 — `min_interval: 24h`, `max_products: 700` (largest single source in the platform even after scoping) |
| **LG** | lg-us-gram-sitemap | US | www.lg.com | Custom CMS | sitemap_jsonld | **LIVE_VALIDATED** | 182 (of 6,220; scoped via `url_include_pattern`) | Full US sitemap + JSON-LD | model, real USD pricing | no sku/mpn — identity via URL slug (embeds LG's own model code) | lg_product_14t90q.html | **New OEM**, Stage 7 2026-08-07 — re-probed on the US consumer site after the Stage 6 India business site had identity but no price |
| **GEEKOM** | geekom-wc | TW | www.geekompc.com | WooCommerce | **woocommerce_store_api** (new engine) | **LIVE_VALIDATED** | 77 | Store API, single page | model, price, images, variable-product type | per-variant configs not individually tracked | geekom_products_p1.json | Re-enabled Stage 7 2026-08-07 — the old `BROKEN` note (Stage 4) was wrong; engine simply didn't exist until now |
| **NovaCustom** | novacustom-wc | NL | novacustom.com | WooCommerce | woocommerce_store_api | **LIVE_VALIDATED** | 6 (of 275; scoped via `category_include`/`category_exclude`/`non_product_terms`) | Store API, paginated | model, sku, real EUR pricing, stock | catalog mostly refurb/spare-parts, deliberately excluded | novacustom_products_p1.json + p2 | **New OEM**, Stage 7 2026-08-07 |
| **Pine64** | pine64-wc | HK | pine64.com | WooCommerce | woocommerce_store_api | **LIVE_VALIDATED** | 2 (of 213; scoped to Laptops/Pinebook Pro categories) | Store API, paginated | model, real USD pricing, stock | small catalog but real and on-mission | pine64_products_p1.json | **New OEM**, Stage 7 2026-08-07 — small catalog, high editorial fit (open-hardware community brand) |
| **Samsung** | samsung-galaxybook | US | samsung.com | Custom | **category_jsonld** (new engine) | **LIVE_VALIDATED** | 12 (all real, one curated category page) | Category-page ItemList JSON-LD, bulk-inline | model, real USD pricing/availability, images | no sku/mpn field — identity via URL `-sku-XXXXXX` suffix | samsung_galaxy_book_category.html | **New engine + new OEM**, Stage 8 2026-08-07 |

## Disabled / deferred (re-audited Stage 8, 2026-08-07)

| OEM | Source ID | URL tried | Status | Evidence | Next action |
|-----|-----------|-----------|--------|----------|-------------|
| **Lenovo** | lenovo-buy-landing | lenovo.com/buy/us/en/&lt;slug&gt; | **BLOCKED_BOT (UA-gated)** | Real 64-SKU ItemList catalog across 3 confirmed curated landing pages — parses cleanly with `category_jsonld`. Returns HTTP 200 to a spoofed browser User-Agent, HTTP 403 (`AkamaiGHost`) to OEM Radar's actual declared crawler UA on the identical URL. | None — enabling requires bot-detection evasion (UA spoofing), which this project does not do. Re-probe only if Lenovo's UA policy changes on its own. |

| OEM | Source ID | URL tried | Status | Evidence | Next action |
|-----|-----------|-----------|--------|----------|-------------|
| Trigkey | trigkey-shopify | www.trigkey.com → trigkey.com | BROKEN | Real Shopify theme (`cdn.shopify.com` in body) but store returns HTTP 402 — signature of a suspended/unpaid Shopify store | Re-probe periodically; nothing to fix on our side |
| GPD | gpd-shopify | gpd.hk | **BLOCKED_JS** (re-confirmed 2026-09-09 recon) | Official surface is a JS sitebuilder (plain fetch returns title/meta only); launches route through Indiegogo and resellers. Editorial value high — see config/oems/gpd.yaml comment | Hold. No browser-automation fallback (standing never-build list); revisit only if GPD ships a static or bulk-API surface |
| Peladn | peladn-shopify | peladn.com | NEEDS_OWNER_PROBE | 200, sitemap present, `products.json` returns a JS redirect (not Shopify) | Owner probe from a real browser for the actual listing route |
| Firebat | firebat-shopify | firebat.com | NEEDS_OWNER_PROBE | 200, `products.json` 404, no WC/sitemap/JSON-LD signals | Owner probe |
| Kingnovy | kingnovy-shopify | kingnovy.com, www.kingnovy.com | NEEDS_OWNER_PROBE | Connection timeout from this network both with and without `www.` | Owner probe from a different network |
| AYANEO | ayaneo-shopify | www.ayaneo.com | RESOLVED 2026-09-09 — retargeted | 200, no Shopify/WC/sitemap/JSON-LD signals found (custom JS app; 502 to plain fetches) | Superseded: descriptor now points at the verified official Shopify store shop.ayaneo.com — see "Fixture-ready, not yet enabled" |

## Fixture-ready, not yet enabled

**Handheld expansion wave 1 (M1, 2026-09-09).** Six Chinese handheld
manufacturers, all probed Shopify-confirmed from the owner machine the same
day, all staged `enabled: false`, all on the existing `shopify` engine
(config-only; no new engine, no schema change). Product family:
`handheld` via per-source `category_map`; PC-handheld vs retro-handheld
subtype is editorial metadata (the feeds do not expose it — decided from
each product's own SoC/OS at review time, never from brand alone).
Editorial priority below is operator scheduling intent only (existing
`min_interval` knob; no tier field exists in this project).

| OEM | Source ID | Region | URL | Platform | Engine | Status | ~Catalog (p1) | Priority | Signals | Fixture | Notes |
|-----|-----------|--------|-----|----------|--------|--------|----------|----------|---------|---------|-------|
| Anbernic | anbernic-shopify | CN/Global | anbernic.com | Shopify | shopify | NEEDS_OWNER_PROBE → staged | 91 (52 kept; 39 accessories denied) | P1 | model, RAM/storage variants, price, images; Chinese product_type (游戏机/配件) | anbernic_products_p1.json | Highest retro-handheld SKU velocity; vendor casing varies; accessories embed model names in titles |
| AYANEO | ayaneo-shopify | CN/Global | **shop.ayaneo.com** | Shopify | shopify | NEEDS_OWNER_PROBE → staged | 94 (34 kept; 60 accessories denied) | P1 | model incl. KONKR sub-brand, SoC, configs, price | ayaneo_products_p1.json | **Retargeted** from www.ayaneo.com (custom JS app, 502 to plain fetches, never enabled); KONKR stays in model names; PC (AYANEO 3/NEXT) and retro (Pocket/KONKR Pocket) in one feed |
| ONEXPLAYER | onexplayer-shopify | CN/Global | onexplayerstore.com | Shopify | shopify | NEEDS_OWNER_PROBE → staged | 70 (15 kept; 55 accessories/refurbs denied) | P1 | model, CPU, display, configs, price | onexplayer_products_p1.json | ONEXFLY/ONEXSUGAR sub-brands stay in model names; vendor's own product_type typo "ONEXPLAYE" preserved in category_map; refurb + battery/keyboard/eGPU denylist |
| AYN | ayn-shopify | CN/Global | www.ayntec.com | Shopify | shopify | NEEDS_OWNER_PROBE → staged | 28 (4 kept; 24 accessories denied) | P2 | model, batch pre-order listings (available=false → SOLD_OUT), configs, price | ayn_products_p1.json | Batch-numbered pre-orders are ordinary variants — no special machinery; "Fill Price Difference" internal SKU denied |
| Retroid | retroid-shopify | CN/Global | www.goretroid.com | Shopify | shopify | NEEDS_OWNER_PROBE → staged | 47 (8 kept; 39 accessories denied) | P2 | model, configs, price | retroid_products_p1.json | Retail entity MOORECHIP TECHNOLOGIES LIMITED (HK); Shenzhen entity UNKNOWN; accessory-dense catalogue |
| AOKZOE | aokzoe-shopify | CN/Global | aokzoestore.com | Shopify | shopify | NEEDS_OWNER_PROBE → staged | 22 (4 kept; 18 parts/refurb/internal SKUs denied) | P2 | model, APU, display, configs, price | aokzoe_products_p1.json | No vendor SKUs anywhere in the feed — identity leans on model_key; parts/repair storefront denied |

Baseline/enablement gate for all six (unchanged existing machinery):
first crawl is `baseline_quiet` (recorded, never delivered), then soak/QC
→ `CANARY` → `LIVE_PARTIAL`. Identity resolution uses the existing ADR-3
cascade; fixture-level handheld naming tests live in
`tests/test_handheld_sources.py` (including the documented RG35XX vs
RG35XX H SKU-guard caveat — no resolver change was made).

## New-OEM reconnaissance, not enabled (Stage 5-7 combined)

Full evidence in `docs/STAGE5_RECON.md` Part 2, `docs/STAGE6_RECON.md`,
and `docs/STAGE7.md`. Summary:

| Candidate | Classification | Why not enabled |
|---|---|---|
| **Samsung** | **LIVE_PARTIAL — real, confirmed reachable** | Real Product JSON-LD with real pricing on `/buy/` pages (Stage 7), but no discovery mechanism found yet (no working sitemap). Highest-confidence next win — needs category-page link scraping, not a config tweak |
| ASUS | Confirmed requires JS execution | Real data exists in a minified Nuxt SSR payload serialized as a JS function call, not parseable statically (Stage 7 — confirmed, not assumed) |
| Lenovo, MSI | BLOCKED_BOT (confirmed on direct product-page fetches, not just root, Stage 7) | No static fix exists |
| Acer, HP | NEEDS_OWNER_PROBE (timeouts, both root and product-page, Stage 6-7) | Genuinely inconclusive — not confirmed blocked |
| Axiomtek, Qotom, BOXX Technologies, Velocity Micro | `static_jsonld` probe guess, not deep-checked | Surfaced during Stage 7 Phase 2 WooCommerce recon; worth a `sitemap_jsonld` follow-up |
| Advantech, Neousys, Winmate, Portwell, Juno Computers, Insurgo | NEEDS_OWNER_PROBE | Network-level failures from this sandbox (Stage 7) — retry from elsewhere before concluding anything |
| Protectli, Puget Systems | WooCommerce hint, no working Store API | Theme/asset hints only; Store API route not exposed |
| System76, Tuxedo, XMG/Schenker | NEEDS_OWNER_PROBE | Root-level probe inconclusive; need a product-page check |
| Framework, Zotac | BLOCKED_BOT | Cloudflare challenge |
| Razer | DISABLED_LOW_VALUE | No Product JSON-LD despite a modern platform; catalog is 93% non-laptop peripherals |
| Eurocom, Falcon Northwest, ASRock Industrial | CANARY | Real, high editorial fit for some, but zero structured data — needs a bespoke parser, not a generic engine |
| Dynabook, Panasonic Toughbook, Fujitsu | BROKEN | Stale sitemap or wrong domain entirely |

## Handheld/ODM expansion recon dispositions (M1, 2026-09-09)

Full classification evidence in the M1 recon; dispositions recorded here so
the coverage matrix stays the single source inventory.

| Candidate | Classification | Disposition | Evidence |
|---|---|---|---|
| **Sixunited** (Shanghai Sixunited Intelligent Technology Co., Ltd., 上海六联智能科技有限公司) | **ODM** (high confidence; official ODM-service offering + industry press). Upstream laptop + mini-PC catalogue, ~630 SKUs, Intel/AMD/domestic platforms; demonstrably exposes new AMD platforms before retail | **NEEDS_ENGINE — not implemented.** `oem-radar probe` on the root returns "needs a product-page fetch"; product-page fetches (2026-09-09) show **zero Product JSON-LD anywhere**: detail pages (`/hyl_deatail/<id>.html`, e.g. XN77-160M5-CS, XS170-6HD-QSB) are server-rendered HTML with specs only as visible text/CMS field metadata; no `application/ld+json` blocks on any checked page; sitemap is flat (not an index) with template-dated `lastmod`. No existing engine can extract this; a bespoke one-OEM parser is below the 3-confirmed-OEM engine bar | Priority 1 editorial intent recorded; revisit when a second/third catalogue-style ODM (e.g. Weibu, uniwill-family) is confirmed, which would justify a small new engine. Story-count note: when admitted, Sixunited would count as one distinct manufacturer in story rules alongside downstream OEMs of the same platform — a story-policy tuning question for that future mission, not now. Weibu probe: SSL handshake failure from this environment (inconclusive, retry elsewhere) |
| **FEVM** (深圳市和峰忆电子科技有限公司, Shenzhen Hefengyi Electronic Technology) | Hybrid own-brand mini-PC design house (medium confidence); ODM-for-others NOT established; no confirmed downstream rebrands | **HOLD — not implemented.** Canonical site fevmpc.com is a JS SPA: raw HTML is an app shell ("FEVM迷你主机" only), sitemap URL returns the same text fragment — no crawlable catalogue, no engine fit. High-value FEVM signals (e.g. pre-release Panther Lake prototype) surface via press, not the site. A Beelink-POC-style bounded delta collector over its private JSON API is the only plausible future path and needs separate ratification | No runtime code, no config, no fixtures |
| Zotac (Zone handheld) | Global OEM — Singapore-domiciled (PC Partner, SGX), not a China-section fit | Rejected for the handheld section; zotac.com behind SafeLine WAF (403) | Corporate structure: PC Partner split from VTech, HQ relocated to Singapore |
| Powkiddy / Orange Pi / Magicx / Data Frog / trimuistore.com | Marketplace-centric or unverifiable official surfaces; Powkiddy's own Shopify feed no longer carries Powkiddy handhelds (retails TrimUI) | Rejected as canonical sources | Marketplace crawling remains out of scope by policy |
| Eluktronics | BLOCKED_JS | Static/API probing found nothing; likely a JS SPA |
| Purism | DISABLED_LOW_VALUE | Sitemap almost entirely blog posts; catalog looks stale |

## Health expectations

Enabled Shopify collectors must not report `ok` with **zero** products when a prior successful run had products, or when zero is unexpected.

Config (`collector_health` in `radar.yaml`):

- `unexpected_zero_is_failure: true`
- `minimum_fraction_of_previous_catalog: 0.35` → below this = **failed** (not mass removals)
- `warn_fraction_of_previous_catalog: 0.70` → **degraded**

## Recommended next batch

1. **Samsung discovery strategy** — data access is already confirmed real
   (Product JSON-LD with real pricing on `/buy/` pages); the only missing
   piece is a bulk-discovery mechanism (category-page link scraping, since
   no working sitemap was found). Highest-confidence win on the table.
2. Deep-check Axiomtek/Qotom/BOXX Technologies/Velocity Micro (surfaced as
   `static_jsonld` guesses during Stage 7's WooCommerce recon, not yet
   product-page-verified).
3. Retry Acer/HP and the unreachable WooCommerce industrial candidates
   (Advantech, Neousys, Winmate, Portwell, Juno Computers, Insurgo) from a
   different network — Stage 7 could not distinguish "blocked" from
   "network-level failure in this sandbox" for any of them.
4. Owner probes for AYANEO, Firebat, Peladn, GPD (www.), Kingnovy, System76,
   Tuxedo, XMG, TUXEDO, Slimbook, Shuttle, Maxtang, LattePanda, MeLE — see
   `docs/STAGE6_RECON.md`/`docs/STAGE7.md` for the specific next step per
   source.

## Browser automation

**Still not justified — now with sharper evidence.** Stage 7 confirmed
Lenovo/MSI are hard-blocked on direct product-page fetches (not just
root), confirmed ASUS specifically requires JS execution (its Nuxt payload
is a minified function call, not parseable JSON — a proven fact, not a
guess), and confirmed **Samsung is fully reachable without any browser
automation** (real JSON-LD, real pricing) — the gap there is a discovery
strategy, not JS rendering. Acer/HP remain genuinely inconclusive
(timeouts). The one platform where JS execution is now a confirmed
requirement (ASUS) still isn't grounds for adding Playwright platform-wide
— see `docs/ENTERPRISE_OEM_ARCHITECTURE.md` §15 and `docs/STAGE7.md`
Phase 3 for the full evidence.


## Runtime health path (Stage 4.1)

```
config/radar.yaml → CollectorHealthConfig (Pydantic)
  → RadarConfig.collector_health
  → run_all(radar_cfg, ...)
  → run_source(..., health_cfg=radar_cfg.collector_health)
  → SourceRunStats.health / health_reason
  → store.run_finished(status='failed' if health=='failed' else 'ok')
```

**Last-good baseline** = most recent `crawler_runs` row with `status='ok'`.
Failed health runs are stored as `status='failed'` and **do not** replace the baseline.
Degraded runs remain `status='ok'` (catalog still processed) but set `health=degraded`.

Reason codes: `HEALTHY_CATALOG`, `CATALOG_WARN_THRESHOLD`, `CATALOG_FAILURE_THRESHOLD`,
`UNEXPECTED_ZERO`, `NO_PREVIOUS_BASELINE`, `RECOVERED`.

Failed collapses return before product processing → **no mass removal events**.

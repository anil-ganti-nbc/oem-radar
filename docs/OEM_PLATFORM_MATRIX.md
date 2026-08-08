# OEM Platform Matrix

Every OEM ecosystem OEM Radar has probed (Stage 4 through Stage 7),
grouped by **derived platform family** — not by brand tier. Originated as
Phase 2 of Stage 6 ("stop thinking in OEMs, think in ecosystems") and
extended through Stage 7. Categories below were not assumed up front; they
fell out of what the probes actually found.

## Platform families

### 1. Shopify — `engine: shopify`

The single highest-leverage family found so far: one endpoint
(`/products.json`) returns the full catalog in bulk, no per-page fetch,
consistent shape across every vendor.

| OEM | Status | Notes |
|---|---|---|
| GMKtec, Minisforum, Beelink, AOOSTAR, Chuwi, Bosgame, NiPoGi, ACEMAGIC, KAMRUI | `LIVE_VALIDATED`, enabled | Original Stage 3–4.1 batch |
| VAIO | `LIVE_VALIDATED`, enabled | Stage 5 — 157/165 items are Warranty SKUs, filtered by the existing denylist automatically |
| Morefine | `LIVE_VALIDATED`, enabled | Stage 5 — old config had the wrong domain entirely |
| Star Labs | `LIVE_VALIDATED`, **enabled Stage 7** | Real Linux laptops; the catalog was ~85% spare parts (mainboards, batteries, displays, input covers) — fixed with an expanded `non_product_terms` list, config-only |
| Trigkey | `BROKEN` | Stage 5 — real Shopify theme, but the store itself returns HTTP 402 (suspended/unpaid) |
| GEEKOM, GPD, Peladn, Firebat, AYANEO, Kingnovy, Morefine* | disabled/audited | See `docs/STAGE5_RECON.md`/`docs/OEM_COVERAGE.md` — mixed reasons, mostly `NEEDS_OWNER_PROBE` |

### 2. Sitemap + schema.org JSON-LD `Product` — `engine: sitemap_jsonld` (new, Stage 6)

Second-highest leverage: no bulk catalog endpoint, but a real sitemap +
real per-page structured data. One fetch per product (not per catalog),
so more expensive than Shopify but still fully static/deterministic.

| OEM | Status | Notes |
|---|---|---|
| SimplyNUC | `LIVE_VALIDATED`, enabled | WordPress + WooCommerce + Yoast SEO. Clean `@graph` with sku/mpn/offers. Pricing is mostly "$0 = quote required" placeholders across this vendor — tracked for spec/SKU/availability signal anyway |
| Khadas | `LIVE_VALIDATED`, enabled | Wix Stores. Real price/availability, but with non-standard `Offers`/`Availability` capitalization — the engine's field lookups are case-insensitive specifically because of this |
| Medion | `LIVE_VALIDATED`, **enabled Stage 7** | Real Product JSON-LD; `url_include_pattern` scopes the 6,265-URL mixed retailer catalog to ERAZER gaming lines only (~680 URLs) — even scoped, this is the largest single source in the platform, hence `min_interval: 24h` |
| LG (gram line) | `LIVE_VALIDATED`, **enabled Stage 7** | Re-probed on the US consumer site (`lg.com/us`, not the India business site tried in Stage 6) — real pricing confirmed there. `url_include_pattern` scopes 6,220 URLs to 182 real gram-laptop pages. No sku/mpn field, but the URL slug itself embeds LG's own model code — stable identity without it |
| **Samsung** | **`LIVE_PARTIAL` — real data confirmed Stage 7, not yet enabled** | Real `Product` JSON-LD on `/buy/` pages: real SKU, real price, real availability. No engine/scoping problem — the gap is *discovery*: no working sitemap found (`robots.txt` serves an HTML fallback, `/us/sitemap.xml` returned only 7 unrelated URLs). Needs category-page link-scraping as a discovery strategy. **The strongest unclaimed opportunity in the platform right now** |

**Ready-to-confirm candidates** (real sitemap + real product URLs, JSON-LD
not yet checked or found empty on the pages tried): System76, Tuxedo,
XMG/Schenker (`NEEDS_OWNER_PROBE` from Stage 5); Axiomtek, Qotom, BOXX
Technologies, Velocity Micro (surfaced as `static_jsonld` probe guesses
during Stage 7's WooCommerce recon, not yet product-page-verified) — these
are the best next bets for expanding this family further.

**Confirmed NOT a fit** (real catalog, real sitemap-shaped URLs, but zero
`Product` JSON-LD on the actual pages): Razer, Eurocom, Falcon Northwest,
ASRock Industrial. This is the single most important negative finding of
Stages 5–6: a sitemap with plausible product URLs is **not** predictive of
JSON-LD presence. Only fetching an actual product page settles it.

### 3. WooCommerce Store API — `engine: woocommerce_store_api` (new, Stage 7)

`GET /wp-json/wc/store/v1/products` — when it's exposed, it returns full
paginated catalogs with real prices, SKUs, and stable numeric IDs. When
it's not exposed (most WordPress/WooCommerce sites tried), the site is
better served by family #2 instead, if it happens to also emit JSON-LD.

| OEM | Status | Notes |
|---|---|---|
| GEEKOM | `LIVE_VALIDATED`, **enabled Stage 7** | 77 real products; `currency_minor_unit: 0` (whole-dollar pricing) — the specific real-world quirk that proved the engine needed to read minor-unit scale per-product rather than assume a fixed 100 |
| NovaCustom | `LIVE_VALIDATED`, **enabled Stage 7** | Security-focused Linux/coreboot laptop maker; `category_include`/`category_exclude` scopes a 275-item catalog (dominated by refurbished/spare-parts listings) to 6 real current products |
| Pine64 | `LIVE_VALIDATED`, **enabled Stage 7** | Open-hardware community brand; scoped from 213 items (phones/tablets/SBCs/accessories) to 2 real current Pinebook Pro SKUs. Also the source of a real denylist false positive found this stage: a generic "keyboard" term matched a real laptop's regional-variant title (`"...LAPTOP (UK Keyboard)"`) — removed from the built-in list |
| XMG, SimplyNUC, Tuxedo | Store API confirmed **absent** | `wp-content` hints in the HTML do not mean the REST Store API is exposed — checked directly and got 404/500 on all three |
| Protectli, Puget Systems | Store API confirmed **absent** (Stage 7) | WooCommerce theme/asset hints present, no working Store API route |

### 3b. Category-page ItemList JSON-LD — `engine: category_jsonld` (new, Stage 8)

Third real "the category page IS the bulk catalog" family, alongside
Shopify's bulk JSON and WooCommerce's Store API — except the payload here
is schema.org JSON-LD embedded on a normal HTML page, not a JSON API. First
seen at `dell` (kept bespoke — see family #4 below); generalized once
Samsung confirmed the same shape independently.

| OEM | Status | Notes |
|---|---|---|
| Samsung | `LIVE_VALIDATED`, **enabled Stage 8** | `samsung.com/us/computers/galaxy-book/` embeds a real 12-item `ItemList` with full `Product` data (price/availability/name/image) nested in `itemListElement[].item`. No `sku`/`mpn` field on the nested items — identity comes from a `-sku-XXXXXX` URL suffix, extracted via a configurable regex |
| Lenovo | **Confirmed compatible, deliberately NOT enabled** | `lenovo.com/buy/us/en/<slug>` curated landing pages carry a *different* real variant of this shape: a purely-navigational `ItemList` (no offers) plus separate standalone top-level `Product` JSON-LD blocks on the same page — 64 real SKUs confirmed across 3 pages. Blocked on UA-based bot detection (200 with a spoofed browser UA, 403 with the project's real crawler UA) — not enabled on principle, not on missing evidence. See `config/oems/lenovo.yaml` |

### 4. Dell-style static HTML + JSON-LD `ItemList` — `engine: dell` (bespoke, deliberately not generalized)

| OEM | Status | Notes |
|---|---|---|
| Dell | `LIVE_VALIDATED`, enabled | The one deliberately vendor-specific engine in the codebase — built before the sitemap_jsonld engine existed, and Dell's catalog-page `ItemList` shape (a list of `Product` nodes *inside* one page) is different enough from the per-URL sitemap+detail-page pattern that folding it into `sitemap_jsonld` would add an `if vendor == "Dell"` branch. Left isolated per the "no OEM-specific logic in reusable engines" rule — the isolation *is* the compliance, not a violation of it |

### 5. Bot-blocked at the HTTP layer — no engine can help without a written justification for browser automation

| OEM | Status | Notes |
|---|---|---|
| Lenovo, MSI | `BLOCKED_BOT` — **confirmed on direct product-page fetches, Stage 7**, not just root | HTTP 403 + Akamai/Cloudflare challenge signatures |
| Origin PC | `BLOCKED_BOT` | HTTP 403 + Cloudflare challenge on the root fetch |
| Framework, Zotac | `BLOCKED_BOT` | Stage 5 — same signature |

### 6. Enterprise commerce platforms — mixed outcome after Stage 7's deeper look

Stage 6 stopped at category pages and left this whole tier as
`NEEDS_OWNER_PROBE`. Stage 7 fetched real product pages and got three
different, evidence-backed answers instead of one vague one:

| OEM | Status | Notes |
|---|---|---|
| **Samsung** | **Confirmed reachable — real `Product` JSON-LD with real pricing on `/buy/` pages** | Moved to family #2 above. Not blocked, not JS-required — just needs a discovery strategy |
| **ASUS** | **Confirmed to require JS execution** | Product page ships `window.__NUXT__=(function(a,b,c,...){...})(...)` — a minified Nuxt SSR payload serialized as a JS function call with positional parameters, not JSON. This is a proven fact about this specific platform, not a hypothesis — reconstructing the data requires actually running the JS |
| Acer, HP | `NEEDS_OWNER_PROBE` — still genuinely inconclusive | Read-timeouts on both root and direct product-page fetches, both stages. Cannot distinguish "blocked" from "slow/rate-limited from this network" without a retry elsewhere |

### 7. Configurator-driven boutique builders — real catalogs, zero structured data

| OEM | Status | Notes |
|---|---|---|
| Eurocom (Stage 5), Falcon Northwest, ASRock Industrial | `CANARY` / `DISABLED_LOW_VALUE` | Clean, real, well-organized product URLs; zero JSON-LD on any page checked. High editorial value (Eurocom, Falcon Northwest) but would need a bespoke, isolated per-vendor adapter — explicitly out of scope for "no vendor-specific engines unless unavoidable and high-value," and not high-value enough yet to justify the exception |

### 8. Wrong target / stale sitemap

| OEM | Status | Notes |
|---|---|---|
| Panasonic Toughbook (Stage 5), Fujitsu | `BROKEN` | Probed domain is the corporate/marketing site, not a product storefront |
| Dynabook (Stage 5) | `BROKEN` | Sitemap technically resolves but content is Windows-8.1-era, clearly abandoned |
| Purism | `DISABLED_LOW_VALUE` | Sitemap is almost entirely blog posts; only ~3 real product URLs found, no JSON-LD |

### 9. Undetermined — needs a real probe, not a root-domain guess

TUXEDO, Slimbook, Shuttle, Maxtang, LattePanda, MeLE, AYANEO, Firebat,
Peladn, GPD, Kingnovy, System76, plus a Stage 7 batch of industrial/
workstation candidates that read as network-level failures from this
sandbox specifically (Advantech, Neousys, Winmate, Portwell, Juno
Computers, Insurgo). Every one of these returned either a timeout, a DNS
failure, or a 200 with no detectable commerce surface at the root. None
are dead ends — they're unfinished investigations. See
`docs/STAGE5_RECON.md` Part 6, `docs/STAGE6_RECON.md`, and `docs/STAGE7.md`
for the specific next probe command for each.

## What this matrix proves

Three reusable engines (`shopify`, `sitemap_jsonld`, `woocommerce_store_api`)
plus one deliberately isolated bespoke engine (`dell`) now cover every OEM
this project has *confirmed* real, collectible product data for — 20
enabled sources from 4 engines. The remaining candidates split cleanly
into: bot-blocked (no static fix), confirmed-requires-JS (ASUS —
narrow and specific, not a blanket claim about the whole enterprise tier),
confirmed-reachable-needs-discovery-work (Samsung — the standout Stage 7
finding), inconclusive-needs-a-retry (Acer, HP, several industrial
WooCommerce candidates), zero-structured-data-needs-bespoke-parser (the
boutique-configurator family), and wrong-target (fix the URL, not the
architecture). None of those buckets currently justifies a *fifth* generic
engine — they justify more owner probes, a handful of config-only fixes
already applied (Star Labs' denylist, Medion/LG/NovaCustom/Pine64
scoping), and one concrete engineering investment worth prioritizing:
Samsung's discovery strategy, which is real product-collection value
sitting on the table for the cost of a category-page crawler, not a new
engine or a Playwright conversation.

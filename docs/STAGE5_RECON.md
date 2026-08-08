# Stage 5 — OEM reconnaissance and engine decision

Probed 2026-08-07, using the improved deterministic `oem-radar probe`
(`src/oem_radar/core/probe.py`) plus targeted manual follow-up (real
`products.json`/sitemap/product-page fetches) where the quick probe alone
wasn't conclusive. All findings below are from live HTTP responses captured
on this date — nothing is fabricated. See
`tests/fixtures/shopify/PROVENANCE.md` for the two fixtures captured this
stage.

Status codes: `LIVE_VALIDATED` · `LIVE_PARTIAL` · `CANARY` ·
`NEEDS_OWNER_PROBE` · `BLOCKED_JS` · `BLOCKED_BOT` · `BROKEN` ·
`DISABLED_LOW_VALUE`

## Part 1 — re-probe of existing disabled/audited descriptors

| OEM | URL tried | Platform found | Evidence | Classification | Next action |
|---|---|---|---|---|---|
| AYANEO | `www.ayaneo.com` | unknown (nginx) | 200 OK; no `products.json`, no WC Store API, no sitemap, no JSON-LD Product on homepage | `NEEDS_OWNER_PROBE` | Custom cart platform. Owner: `oem-radar probe https://www.ayaneo.com --json` from a residential IP; if CN-hosted checkout is involved, region may matter |
| Firebat | `firebat.com` | unknown (nginx) | 200 OK; `products.json` 404; no WC/sitemap/JSON-LD signals | `NEEDS_OWNER_PROBE` | Same as above |
| GEEKOM | `www.geekompc.com` | **WooCommerce Store API — live and real** | `GET /wp-json/wc/store/v1/products?per_page=100` → 200, `X-WP-Total: 77`, 77 real products (IT13 Max, GT13 Max, A9 Mega, GeekBook X16 Pro, …) with id/slug/permalink/price/currency | `LIVE_VALIDATED` (storefront) — **contradicts the previous `BROKEN` audit note**, which was likely testing the wrong endpoint or an intermittent redirect. Not collectible today only because **no WooCommerce engine exists yet** (see Part 4) | Keep `enabled: false` until a WooCommerce engine is built or a 2nd/3rd confirmed WC OEM justifies one |
| GPD | `gpd.hk` (bare) times out; `www.gpd.hk` works | `static_jsonld` guess (sitemap present) | `www.gpd.hk` → 200 cloudflare, `sitemap.xml` found; `gpd.hk` without `www.` hits a connect timeout from this network | `NEEDS_OWNER_PROBE` | The configured base_url may need a `www.` prefix; did not get far enough to confirm real Product JSON-LD on a product page — owner: `oem-radar probe https://www.gpd.hk --json` |
| Kingnovy | `kingnovy.com`, `www.kingnovy.com` | unreachable | Both connect-timeout (15s) from this network/sandbox | `NEEDS_OWNER_PROBE` | Cannot distinguish "down" from "network-blocked here" — needs a probe from the owner's machine |
| Morefine | `store.morefine.com` (configured) → DNS failure; `www.morefine.com` → live Shopify | **Shopify — confirmed** | Real `products.json`: 40 products (M8 Plus, S800, S700, H1 mini-PCs, external-GPU docks); 8 filtered (2 shipping-protection, 4 "docking station", 1 adapter, 1 bracket — all via existing denylist) | `LIVE_VALIDATED` | **Enabled this stage** — fixed the stale `base_url` (was never actually reachable, which is very likely why it was left disabled) |
| Peladn | `peladn.com` | unknown | 200 cloudflare; sitemap present (not an index); `products.json` returns a JS redirect page (`window.location='/'`), not JSON | `NEEDS_OWNER_PROBE` | Custom SPA-ish cart; not Shopify. Owner probe from a browser to see the real product-listing route |
| Trigkey | `www.trigkey.com` → redirects to `trigkey.com` | Shopify **theme present but store returns HTTP 402** | `cdn.shopify.com` in body (real Shopify theme), but the store itself responds `402 Payment Required` — the classic signature of a **suspended/unpaid Shopify store** | `BROKEN` | Not an engine problem — the storefront itself appears to be down for billing reasons. Re-probe periodically; no action possible until the store is back |

## Part 2 — new OEM reconnaissance

| Candidate | URL | Platform | Publicly enumerable? | JSON-LD on product page? | Engine fit | Editorial value | Blockers | Classification |
|---|---|---|---|---|---|---|---|---|
| Framework | `frame.work` | unknown | — | — | — | High (real boutique/repairable laptop maker) | Cloudflare bot challenge (403) on the plain root fetch | `BLOCKED_BOT` |
| System76 | `system76.com` | unknown (custom, likely in-house) | Not via `products.json`/WC/sitemap at root | Not checked on a product page (ran out of probe budget) | Unclear — likely needs a one-off parser | High (Linux-first boutique laptops, exact "before it's news" fit) | Root probe alone inconclusive | `NEEDS_OWNER_PROBE` |
| Tuxedo Computers | `www.tuxedocomputers.com` | unknown | WC Store API confirmed **absent** (404 route) | not reached | Unclear | High (Linux boutique laptops, EU) | Root returned transient `500`; Store API route doesn't exist even though the site smells like WordPress | `NEEDS_OWNER_PROBE` (retry; may need a different endpoint) |
| XMG / Schenker | `www.xmg.gg` | WordPress-ish (`wp-content` hint) but **no WC Store API** (404 `rest_no_route`) | No | not reached | Unclear — likely a custom configurator, not a plain catalog | Medium-high | Heavy product-configurator UX typical of XMG; Store API not exposed | `NEEDS_OWNER_PROBE` |
| Razer | `www.razer.com` | SAP Commerce Cloud (Hybris) — `api-p1.phoenix.razer.com` media/product-sitemap pattern | Yes — real product sitemap with 637 URLs | **No** — product pages carry only `WebSite`/`Brand` JSON-LD, no `Product` node | Poor fit for the sitemap+JSON-LD pattern as-is | Medium (huge peripherals catalog, laptops are a small fraction — 44 of 637 URLs, heavily duplicated) | No structured product data; would need a bespoke SAP-Hybris parser for a catalog that's mostly accessories | `DISABLED_LOW_VALUE` |
| Medion | `www.medion.com` | Custom (SAP Commerce-style URL pattern) with a **dedicated Product sitemap** (`.../sitemap/Product-de-DE-medion-de-EUR.xml`) | Yes — 6,265 product URLs | **Yes** — real `@type: Product` JSON-LD confirmed on a laptop product page | Good technical fit for sitemap+JSON-LD | Low-medium — Medion is a mass consumer-electronics retailer (Aldi-affiliated); catalog mixes laptops/PCs with headphones, backpacks, monitors, speakers. Would need aggressive category-path filtering to stay on-mission | Massive accessory noise; German-locale by default | `LIVE_PARTIAL` |
| Dynabook | `us.dynabook.com` | legacy Toshiba site | Sitemap (`sitemap.xml.gz`) present but content is **stale** — pages reference Windows 8.1-era content, no active product catalog structure | not reached | N/A | Medium (business laptops) but likely resold via partners in the US, not sold direct | Sitemap appears abandoned/uncurated | `BROKEN` |
| VAIO | `us.vaio.com` | **Shopify — confirmed** | Yes — `products.json`, 165 items | N/A (Shopify JSON path used instead) | Existing Shopify engine, zero changes | High — premium Japanese-made laptops, real "before it's news" fit | 157 of 165 items are Warranty/repair-plan SKUs — already filtered by the existing `warranty` denylist term | `LIVE_VALIDATED` |
| Panasonic Toughbook | `na.panasonic.com` | N/A | N/A | N/A | N/A | High (rugged laptops, real news value) but **wrong URL entirely** — this domain is Panasonic's general corporate/news site (solar batteries, avionics), not a Toughbook storefront | Toughbook is very likely sold through authorized resellers in the US, not direct | `BROKEN` (wrong target; needs owner to identify the actual storefront, if a direct one exists) |
| Eurocom | `eurocom.com` → `shop.eurocom.com` | Custom (looks like an older Sencha/ExtJS configurator app based on URL patterns like `/ec/main()ec`) | Yes — clean `/product/{model}` and `/product/{model}/specs` URLs, ~15 real laptop models (Raptor X18/X16, Nightsky, Blitz Ultra) | **No** JSON-LD found on product pages | Poor fit for sitemap+JSON-LD as-is; would need a bespoke HTML parser (and possibly JS rendering for pricing) | High — boutique Canadian mobile-workstation maker, exactly the mission's target profile | No structured data despite a clean, small, well-organized catalog | `CANARY` — worth a dedicated one-off parser in a future stage, not a fit for the generic engine |
| Eluktronics | `eluktronics.com` | Likely a JS-rendered SPA | `sitemap.xml`, `products.json`, `/collections/all` all 404 despite a 200 homepage; `<html class="no-js">` fallback markup | not reached | Needs a browser to confirm | Medium-high (boutique gaming laptops) | Static/API probing found nothing; may genuinely require JS rendering | `BLOCKED_JS` (do not add Playwright for this alone) |
| Zotac | `www.zotac.com` | unknown | — | — | — | Medium (mini-PCs, GPUs — adjacent to mission) | HTTP 468 (non-standard Cloudflare block code) on every request tried | `BLOCKED_BOT` |
| SimplyNUC | `www.simplynuc.com` → redirects to `snuc.com` | WordPress + WooCommerce + Yoast SEO | Yes — dedicated `product-sitemap.xml`, 137 real product URLs | **Yes** — clean `@graph` with a real `Product` node: `sku`, `mpn`, `brand`, `offers[].price/priceCurrency/availability` | **Best sitemap+JSON-LD candidate found** | High — boutique NUC-style mini-PC/edge-server maker, squarely on-mission | WooCommerce Store API itself returned `500` (not usable directly), but the JSON-LD path works cleanly | `LIVE_VALIDATED` (for a future sitemap+JSON-LD engine) |

## Part 3 — probe tooling changes

`oem-radar probe <url>` now reports (via `core/probe.py`, `probe_storefront()`):
HTTP status, final URL + redirect chain, Shopify `products.json` detection
(with a sample product count), Shopify theme hint (`cdn.shopify.com`),
WooCommerce hint + **live WooCommerce Store API check**, sitemap/robots.txt
discovery (index vs. leaf, product-URL heuristic), JSON-LD `Product` node
count on the homepage (handles plain objects, arrays, and `@graph`), and a
bot/challenge heuristic. `--json` prints the full structured result. It
remains pure `requests`-based HTTP/HTML/JSON inspection — no JS execution,
no browser. 16 new unit tests in `tests/test_probe.py` cover the JSON-LD
parser (object/array/`@graph`/malformed/no-blocks) and the bot-detection
heuristic, including a real regression found during this stage: Shopify's
own anti-spam `captcha-bootstrap` script was tripping the old naive
"contains 'captcha'" check on completely ordinary storefronts (fixed by
requiring the strong markers to be genuine challenge-page phrases, and
demoting generic words like "captcha"/"cloudflare" to weak markers that
only count paired with a 403/503 status).

## Part 4 — engine decision matrix

| | **A. More Shopify** | **B. Sitemap + JSON-LD** | **C. WooCommerce Store API** | **D. Other static/API** |
|---|---|---|---|---|
| OEMs unlocked this stage | VAIO, Morefine (2, zero engine changes) | 0 implemented — 1 strong (SimplyNUC), 1 partial/noisy (Medion) | 0 implemented — 1 confirmed live (GEEKOM) | none identified |
| Editorial value | High (VAIO), high (Morefine, mini-PC) | High if built (SimplyNUC); low-medium (Medion) | High (GEEKOM — real mini-PC brand) | n/a |
| Implementation complexity | None — existing engine, config only | Medium (sitemap index/nested parsing, `@graph`/array/multi-node JSON-LD, offer/price/SKU extraction, dedup) | Medium (pagination via `X-WP-Total`, variable-product variations endpoint, WooCommerce doesn't guarantee stable SKUs) | n/a |
| Fixture availability | Real fixtures captured this stage | Real fixtures available for SimplyNUC + Medion product pages (not yet captured — engine not being built this stage) | Real fixture available for GEEKOM (not yet captured) | n/a |
| Anti-bot risk | Low (both are plain Cloudflare-fronted Shopify stores) | Low-medium (SAP Hybris sites like Razer are bot-protected in other ways even without blocking probes) | Low for GEEKOM | n/a |
| Expected maintenance | Very low — reuses proven code path | Medium — schema drift across sites is a real risk (Razer's own site has zero Product JSON-LD despite looking similar) | Medium | n/a |
| Data richness | High (full Shopify variant/price/image set) | High where present (SimplyNUC has SKU/MPN/offers); inconsistent elsewhere | High (GEEKOM has full spec text, price, images via WC) | n/a |
| Identity quality | High (Shopify id/handle/SKU) | Medium — relies on sitemap URL + JSON-LD `sku`/`mpn`, both vendor-dependent | High (WC numeric `id` + `slug`) | n/a |
| Pagination complexity | None (already solved) | Sitemap-index nesting (already prototyped in `core/probe.py`'s sitemap check) | Simple (`per_page`/`X-WP-Total` header) | n/a |
| Page-level fetching needed | No (catalog JSON is enough) | **Yes** — JSON-LD only appears on individual product pages, not sitemaps, so N+1 fetches per source | No (Store API returns full listings) | n/a |
| False-positive risk | Low | **Higher** — this stage found that "has a sitemap with 'product' in some URL" is a weak, frequently-wrong signal (Razer, Eurocom both looked promising and had zero real Product JSON-LD; Panasonic's "sitemap" was an unrelated corporate site) | Low (Store API either works or doesn't) | n/a |

### Recommendation: `MORE_SHOPIFY`

Two real, zero-engine-risk OEMs (VAIO, Morefine) clear the bar for the
"easy Shopify batch" path and were implemented this stage. Neither the
sitemap+JSON-LD engine nor the WooCommerce engine clears the "**at least 3
worthwhile OEMs**" bar required before building a new reusable engine:

- **Sitemap + JSON-LD**: only **1 strong** candidate (SimplyNUC — clean,
  boutique, real SKU/MPN/offers) plus **1 partial/marginal** one (Medion —
  real data but a noisy mass-retailer catalog, arguably off-mission). Of
  the 6 candidates that looked promising from sitemap/URL heuristics alone
  (Razer, Eurocom, Panasonic, Dynabook, Medion, SimplyNUC), only 2 actually
  had real `Product` JSON-LD on inspection — a useful data point for how
  unreliable the surface-level heuristic is on its own.
- **WooCommerce Store API**: only **1 confirmed** live candidate (GEEKOM).
  XMG, SimplyNUC, and Tuxedo all showed WordPress/WooCommerce *hints* but
  none exposed a working Store API route.

Per the implementation boundary rules, this means: **stop and report, do
not build either engine yet.** Both are documented below as ready-to-build
once one more confirmed OEM surfaces (from a future owner probe of
AYANEO/System76/Tuxedo/XMG, or a fresh candidate).

## Part 5 — proposed architecture (not implemented this stage)

### B. Sitemap + JSON-LD engine (recommended path once a 3rd OEM confirms)

Interface, mirroring the existing `ShopifyEngine`/`DellEngine` shape so it
drops into the same `engines.register()` pattern with no core changes:

```python
@engines.register("sitemap_jsonld")
class SitemapJsonLdEngine:
    config_schema = SitemapJsonLdSourceConfig  # sitemap_url, url_include_pattern,
                                                 # url_exclude_pattern, category_map

    def discover(self, fetcher: Fetcher) -> Iterable[ProductRef]:
        # 1. fetch sitemap_url; if <sitemapindex>, recurse into each <sitemap><loc>
        # 2. collect <url><loc> entries, dedup by URL
        # 3. filter through url_include_pattern / url_exclude_pattern (config,
        #    not vendor conditionals in the engine — this is how SimplyNUC's
        #    /product/ path gets kept while Medion's mixed catalog gets scoped
        #    down to notebook/multimedia-pc paths)
        ...

    def parse(self, doc: FetchedDocument, ref: ProductRef) -> RawProduct | None:
        # fetch each product URL individually (N+1 — no bulk JSON endpoint),
        # extract every <script type="application/ld+json"> block, walk
        # plain-object / array / @graph shapes, keep nodes where
        # @type == "Product" (or contains it, since @type can be a list)
        ...

    def normalize(self, raw: RawProduct) -> NormalizedProduct:
        # map schema.org Product fields: name -> model, sku/mpn -> identity,
        # offers[].price/priceCurrency/availability -> Price/availability,
        # image (str or list) -> images[], brand.name -> manufacturer
        # (cross-checked against the configured manufacturer, not trusted blindly)
        ...
```

First 2–3 OEMs it would support:
1. **SimplyNUC** (`snuc.com`) — confirmed clean `Product` JSON-LD with
   `sku`/`mpn`/`offers`, dedicated `product-sitemap.xml`, 137 items.
2. **Medion** — confirmed real `Product` JSON-LD, but requires a
   `url_include_pattern` scoped to `notebook`/`multimedia-pc`/`convertible`
   path segments to avoid ingesting thousands of unrelated SKUs (monitors,
   backpacks, speakers). Lower priority given the noise.
3. *(needs one more confirmed candidate — best next bets: System76 or
   Tuxedo, pending an owner probe of their actual product pages for
   JSON-LD, since the root-level probe alone was inconclusive for both.)*

Fixture sources: real captures of
`https://snuc.com/product/ee-1000/` and one Medion product page (both
already fetched live during this recon pass; not yet saved as fixtures
since the engine isn't being built this stage).

Known edge cases to test when this is built (per the Stage 5 brief):
sitemap index parsing, nested sitemap, duplicate URLs across sitemaps,
malformed XML, single Product object, Product array, `@graph`, multiple
Product nodes in one page, malformed JSON-LD (must skip, not crash — already
proven safe in `core/probe.py`'s parser), missing SKU, missing price,
multiple `offers` entries (pick lowest/in-stock, documented behavior),
unavailable product (`availability` other than `InStock`), image as string
vs. array, duplicate product identity across two sitemap entries pointing
at the same canonical URL, HTTP errors mid-crawl, zero product discovery,
and source isolation (one broken OEM's malformed page must not affect
another source's run).

### C. WooCommerce Store API engine (deferred — only 1 confirmed OEM)

Interface sketch, for when a 2nd/3rd candidate confirms:

```python
@engines.register("woocommerce")
class WooCommerceEngine:
    config_schema = WooCommerceSourceConfig  # per_page, category_include

    def discover(self, fetcher):
        # GET {base}/wp-json/wc/store/v1/products?per_page=100&page=N
        # paginate via X-WP-Total / X-WP-TotalPages response headers
        ...

    def parse(self, doc, ref):
        # id + slug = identity; strip HTML from name/description;
        # prices{} -> Price (Store API returns price as a minor-unit string,
        # e.g. "75900" with a separate price_decimals field — do not assume 2dp)
        ...
```

GEEKOM (`www.geekompc.com`) confirmed live with 77 real products (id, slug,
permalink, price, `variable` type products needing a follow-up
`/products/{id}/variations` call for RAM/storage configs). Real fixture
already captured live during this recon pass but not yet saved — deferred
along with the engine.

## Part 6 — owner probes still required

- AYANEO, Firebat, Peladn: platform undetermined from this sandbox; need a
  browser-based look at how checkout/cart actually works.
- GPD: retry with `www.gpd.hk` (bare domain times out) and check for
  Product JSON-LD on an actual product page.
- Kingnovy: fully unreachable from this network — needs a probe from a
  different network/region.
- System76, Tuxedo Computers, XMG/Schenker: root-level probes were
  inconclusive; need one real product-page fetch each to check for
  JSON-LD or a hidden API.
- Panasonic Toughbook: needs the owner to identify the actual direct
  storefront (if one exists) — `na.panasonic.com` is not it.

## Part 7 — explicitly not pursued this stage

- Razer, Eurocom, Dynabook: real catalogs exist but neither expose
  structured product data nor fit the existing engines without a bespoke,
  vendor-specific parser — out of scope per "do not build vendor-specific
  engines unless unavoidable and high-value."
- Eluktronics, Framework, Zotac: bot-blocked or JS-rendered; no Playwright
  added, per the stage's explicit boundary.

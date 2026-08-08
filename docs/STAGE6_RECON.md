# Stage 6 — Enterprise OEM reconnaissance

Probed 2026-08-07, using the Stage 5 `oem-radar probe` tooling plus targeted
manual follow-up (real sitemap/product-page fetches) for anything the quick
probe alone couldn't resolve — same methodology as Stage 5
(`docs/STAGE5_RECON.md`), extended here to the mainstream/enterprise and
remaining boutique/mini-PC tiers. Every finding below is from a live HTTP
response captured on this date. See
`tests/fixtures/sitemap_jsonld/PROVENANCE.md` for the fixtures captured this
stage. Targets already covered in Stage 5 (Framework, System76, Tuxedo*,
XMG/Schenker, Eurocom, Eluktronics, SimplyNUC, VAIO, Dynabook) are not
re-probed here except where noted; see `docs/STAGE5_RECON.md` for those.

Status codes: `LIVE_VALIDATED` · `LIVE_PARTIAL` · `CANARY` ·
`NEEDS_OWNER_PROBE` · `BLOCKED_JS` · `BLOCKED_BOT` · `BROKEN` ·
`DISABLED_LOW_VALUE`

## Primary tier (Lenovo, ASUS, HP, Acer, MSI)

| OEM | Root probe | Deeper check | Classification | Evidence |
|---|---|---|---|---|
| Lenovo | `www.lenovo.com` → HTTP 403, Akamai, strong bot-challenge markers | not pursued further | `BLOCKED_BOT` | Root fetch alone is challenged; a plain requests session cannot get past it |
| MSI | `www.msi.com` → HTTP 403, bot-challenge markers | not pursued further | `BLOCKED_BOT` | Same signature as Lenovo |
| Origin PC | `www.originpc.com` → HTTP 403, cloudflare, bot-challenge markers | not pursued further | `BLOCKED_BOT` | Same pattern |
| ASUS | `www.asus.com` → 200, sitemap index present, no Shopify/WC/product-sitemap hint at root | Checked a real category page (`/us/laptops/for-home/zenbook/`): 1 JSON-LD block, type `ItemList`/`BreadcrumbList` — **no `Product` node** | `NEEDS_OWNER_PROBE` | Category pages carry navigational schema only; individual product pages weren't checked (likely behind JS hydration per the brief's own hypothesis — not confirmed either way) |
| HP | `www.hp.com` → 200 after a 3-hop redirect chain (region auto-detect to `/in/en/`), no sitemap/JSON-LD/WC signal at the landed page | not pursued further | `NEEDS_OWNER_PROBE` | Region redirect alone ate the probe; a real product page in a fixed region needs a follow-up |
| Acer | `www.acer.com` → read timeout (15s) | not pursued further | `NEEDS_OWNER_PROBE` | Could not distinguish "slow" from "blocked" from this network |
| Samsung | `www.samsung.com` → 200 (redirects to `/in/`), sitemap index present, no product-sitemap hint | Checked a real category page (`/us/computing/galaxy-books/`): 1 JSON-LD block, type `WebPage` — **no `Product` node** | `NEEDS_OWNER_PROBE` | Same shape as ASUS: category pages are schema-light, product pages unconfirmed |

**Reading**: every mainstream global OEM in this batch is either outright
bot-blocked at the root, or shows category-page JSON-LD with no `Product`
node — consistent with the brief's own expectation that these run on
JS-hydrated, enterprise commerce platforms (Adobe Commerce / SAP Commerce /
custom React) that don't serve static per-product `Product` schema the way
smaller vendors do. This is a *pattern*, not a coincidence — see the
ecosystem map in `docs/OEM_PLATFORM_MATRIX.md`. None of the five were
enabled; none had enough evidence to justify Playwright per the stage's own
"exhaust static/API first, then write a justification" rule — the honest
finding is that static probing was inconclusive for 4 of 5 (ASUS/HP/Acer/
Samsung) and outright blocked for Lenovo/MSI/Origin, not that Playwright is
proven necessary.

## Secondary tier (Samsung/LG/Fujitsu — Dynabook/VAIO carried from Stage 5)

| OEM | Root probe | Deeper check | Classification | Evidence |
|---|---|---|---|---|
| LG | `www.lg.com` → 200 (redirects to `/in/`), sitemap (not index) with product-URL pattern | Fetched a real `lg-gram` model page: **2 JSON-LD blocks — `BreadcrumbList` + a real `product` node** (lowercase `@type`) with `mpn` and `brand`. **No `offers`/price** in this region's JSON-LD | `LIVE_PARTIAL` | Real identity data (MPN), no pricing via JSON-LD on the India business site tried — a US/consumer LG.com page might differ; not checked |
| Fujitsu | `www.fujitsu.com` → redirects to `global.fujitsu/en-global` (corporate site), no sitemap/product signal | not pursued further | `BROKEN` (wrong target, like Panasonic in Stage 5) | This is Fujitsu's corporate site, not a product storefront — same failure mode as `na.panasonic.com` in Stage 5 |

## Linux / boutique tier

| OEM | Root probe | Deeper check | Classification | Evidence |
|---|---|---|---|---|
| Star Labs | `starlabs.systems` → **Shopify confirmed**, 111 products | Real catalog inspected: 9 tagged `Laptop` + 1 `Desktop Computers`, but also ~13 untyped real laptop models (StarBook/StarFighter/StarLite families incl. "Privacy" editions) mixed with ~80 spare-parts SKUs (mainboards, batteries, displays, input covers) that the existing `_DEFAULT_NON_PRODUCT` denylist does **not** cover | `LIVE_VALIDATED` (technically) but **not enabled this stage** | Real, on-mission Linux laptop maker — but needs a materially larger `non_product_terms` list (mainboard/battery/display/input cover/daughter board/fan/heatsink/speaker/bottom cover/glass surface/wireless card/rubber feet/etc.) to avoid alerting on spare parts as "new products." Left as a documented, ready-to-enable candidate rather than rushed in with an incomplete denylist |
| TUXEDO Computers | `www.tuxedocomputers.com` → 200 this time (was a transient 500 in Stage 5); still no sitemap/WC-Store-API/JSON-LD signal at root; WC Store API route confirmed **absent** (404) in Stage 5 | not pursued further | `NEEDS_OWNER_PROBE` | Root-level probing still inconclusive; smells like a custom WordPress theme without the WooCommerce REST surface exposed |
| Slimbook | `slimbook.com` → 200 (redirects to `/en/`), sitemap present (leaf, not index), no product-URL pattern detected | not pursued further | `NEEDS_OWNER_PROBE` | — |
| Purism | `puri.sm` → 200, `wp-content` hint (WooCommerce guess), sitemap present with `/products/` URLs | Sitemap is mostly blog posts; only ~3 real `/products/` URLs found (Librem 5, Librem 15). Checked `librem-5` product page: **0 JSON-LD blocks** | `DISABLED_LOW_VALUE` | Catalog looks stale/minimal from the sitemap alone; no structured data either |

## Gaming tier

| OEM | Root probe | Deeper check | Classification | Evidence |
|---|---|---|---|---|
| Falcon Northwest | `www.falcon-nw.com` → 200, sitemap with product-URL pattern (272 URLs total) | Real model pages found (`/desktops/tiki`, `/laptops/tlx`, etc. — Tiki/RAK/DRX/TLX lineup). Checked two: **0 JSON-LD blocks** on either | `CANARY` | High editorial fit (boutique gaming PC builder, exactly the mission profile) but a custom configurator platform with zero structured data — same shape as Eurocom in Stage 5. Would need a bespoke parser, not the generic engine |

## Mini-PC / SBC tier

| OEM | Root probe | Deeper check | Classification | Evidence |
|---|---|---|---|---|
| Khadas | `www.khadas.com` → 200, **Wix-hosted** (`generatedBy="WIX"` sitemap index), dedicated `store-products-sitemap.xml` | Real product page (`vim3`): clean single `Product` JSON-LD node with real **price ($169 USD), availability, description** — but using non-standard `Offers`/`Availability` capitalization | **`LIVE_VALIDATED`** | **Enabled this stage** via the new `sitemap_jsonld` engine — see below |
| ASRock Industrial | `www.asrockind.com` → 200, sitemap (leaf) with `/product/` URL pattern (761 URLs) | Fetched a real product page (`/en-gb/product/1059`): **0 JSON-LD blocks** | `DISABLED_LOW_VALUE` | Real catalog, no structured data; industrial/embedded boards are also a lower editorial priority than consumer mini-PCs |
| LattePanda | `www.lattepanda.com` → 200, sitemap index present, no product-URL pattern at the index level | not pursued further | `NEEDS_OWNER_PROBE` | Sitemap index didn't reveal a product leaf in the quick probe; a follow-up fetch of the actual leaf sitemaps is needed |
| Shuttle | `www.shuttle.eu` → 200 (redirects to `/en/`), no sitemap found at the standard path | not pursued further | `NEEDS_OWNER_PROBE` | — |
| Maxtang | `www.maxtangpc.com` → 200, cloudflare, no sitemap/product signal at root | not pursued further | `NEEDS_OWNER_PROBE` | — |
| MeLE | `www.meleplus.com` → DNS resolution failure | not pursued further | `NEEDS_OWNER_PROBE` | Domain guess was likely wrong (MeLE's real storefront domain wasn't confirmed) |

## Summary: what got enabled this stage

Two OEMs, both via the new `sitemap_jsonld` engine, both with real captured
fixtures (see `tests/fixtures/sitemap_jsonld/PROVENANCE.md`):

- **Khadas** (`khadas-sitemap`) — Wix Stores, real price/availability data.
- **SimplyNUC** (`simplynuc-sitemap`) — carried over from the Stage 5 recon
  (`docs/STAGE5_RECON.md`), which had already confirmed real JSON-LD with
  `sku`/`mpn`/`offers`; collected for the first time this stage now that the
  engine exists.

Combined with **Medion** (Stage 5, confirmed real but noisy — not enabled,
needs category-path scoping) and **LG** (this stage, confirmed real
identity data but no price in the region tried — not enabled, worth a
follow-up on a pricing-enabled LG storefront), that's **4 independently
confirmed real JSON-LD sources across 4 structurally different platforms**
(WordPress/Yoast, Wix Stores, LG's own CMS, and Medion's SAP-style catalog)
— the evidence base that justified building the engine. See
`docs/OEM_PLATFORM_MATRIX.md` for the full ecosystem breakdown and
`docs/ENTERPRISE_OEM_ARCHITECTURE.md` for the architecture this feeds into.

## What stayed disabled, and why

- **Star Labs**: real Shopify, real laptops present, but needs a larger
  spare-parts denylist before enabling responsibly (see above) — this is a
  config change, not an engine change, and is a strong candidate for the
  very next small batch.
- **Falcon Northwest, Eurocom (Stage 5), ASRock Industrial**: real catalogs,
  zero structured data. Good `CANARY`/`DISABLED_LOW_VALUE` candidates for a
  future bespoke, isolated adapter — not the generic engine.
- **Purism**: catalog looks stale from sitemap evidence alone.
- **Fujitsu, Panasonic (Stage 5)**: wrong target entirely (corporate site,
  not a storefront).
- **Lenovo, MSI, Origin PC**: bot-blocked at the root; no Playwright added
  per the stage's explicit boundary.
- **ASUS, HP, Acer, Samsung, TUXEDO, Slimbook, LattePanda, Shuttle,
  Maxtang, MeLE**: inconclusive from static/API probing alone — genuine
  `NEEDS_OWNER_PROBE`, not a euphemism for "blocked." A product-page-level
  fetch (not just the root/category page) is the next concrete step for
  each.

## Probe tooling

No changes to `oem-radar probe` itself this stage (Stage 5 already added
the redirect/Shopify/WC/sitemap/JSON-LD detection used throughout this
recon). The JSON-LD extraction logic it uses was refactored into
`src/oem_radar/core/jsonld.py` so the new engine and the probe tool share
exactly one parser (`extract_jsonld_nodes`) instead of duplicating the
"walk plain object / array / @graph, tolerate malformed blocks" logic.

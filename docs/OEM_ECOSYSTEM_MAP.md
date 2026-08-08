# OEM Ecosystem Map

**Status: master planning document, written Stage 8 (2026-08-07).** Every
OEM this project has probed through Stage 8, in one table, grouped the way
Stage 8 Phase 8 asked for: engine, platform, region, editorial value,
confidence, blocked/reachable, owner-probe status, discovery quality. This
supersedes `docs/OEM_PLATFORM_MATRIX.md` as the day-to-day planning
reference — the matrix stays as the deeper narrative/evidence record for
*why* each finding is what it is; this document is the flat table for
deciding *what to probe next*.

Confidence scale: **Confirmed** (real fetch, real structured data seen) ·
**Confirmed-not-a-fit** (real fetch, no usable data) · **Confirmed-blocked**
(real fetch, bot/WAF-blocked) · **Inconclusive** (fetch failed for reasons
that don't distinguish blocked/slow/broken) · **Undetermined** (not yet
probed with a real fetch this stage or prior).

## Enabled, in production (21 sources / 27 OEMs configured, 28 descriptors)

| OEM | Engine | Region | Discovery quality | Editorial value | Notes |
|---|---|---|---|---|---|
| GMKtec, Minisforum, Beelink, AOOSTAR, Chuwi, Bosgame, NiPoGi, ACEMAGIC, KAMRUI | shopify | Global (CN mfg) | Excellent (bulk JSON) | High — mini-PC/handheld category leaders | Original Stage 3-4.1 batch |
| VAIO, Morefine, Star Labs | shopify | JP / CN / UK | Excellent | High (VAIO), Medium (Morefine), High (Star Labs, Linux) | Stage 5/7 additions |
| Dell | dell (bespoke) | US | Good (ItemList-in-page, model-level) | High — mainstream brand | Only bespoke engine, justified structural exception |
| SimplyNUC, Khadas | sitemap_jsonld | US / HK | Good, price often absent | Medium-High | Stage 6 |
| Medion, LG | sitemap_jsonld | DE / US | Good, scoped via url_include | Medium (Medion), High (LG gram) | Stage 7 |
| GEEKOM, NovaCustom, Pine64 | woocommerce_store_api | CN / NL / community | Excellent (real Store API) | High (GEEKOM), Medium (NovaCustom, Pine64 — niche) | Stage 7 |
| **Samsung** | **category_jsonld** | **US** | **Excellent — category page IS the bulk catalog, real sku/price/availability** | **High — major global OEM, Galaxy Book line** | **Stage 8 — new engine, first OEM** |

## Confirmed real data, deliberately NOT enabled (evidence exists, principle blocks it)

| OEM | Engine match | Region | Discovery quality | Editorial value | Why not enabled |
|---|---|---|---|---|---|
| **Lenovo** | category_jsonld (confirmed compatible) | US | Excellent when reachable — 64 real SKUs across 3 curated `/buy/` landing pages | Very high — top global OEM | UA-gated: 200 with a spoofed browser UA, 403 with the project's real, honest crawler UA. Enabling would require identity-spoofing bot-detection evasion — a line this project does not cross. See `config/oems/lenovo.yaml`. |

## Confirmed-not-a-fit (real fetch, no usable structured data)

| OEM | What was checked | Region | Notes |
|---|---|---|---|
| Razer, Eurocom, Falcon Northwest, ASRock Industrial | Real sitemap + product pages | Various | Stage 5-6. Real catalogs, zero JSON-LD. |
| Qotom | Real sitemap (2,575 URLs) + product detail page | CN | Stage 8. Zero Product JSON-LD on the actual page. |
| BOXX | Real sitemap (342 URLs) + 2 product pages | US | Stage 8. Zero JSON-LD. |
| Velocity Micro | Real sitemap (184 URLs) + 2 product pages | US | Stage 8. Zero JSON-LD. |
| Winmate | Real sitemap (2,470 URLs) + 2 product pages | TW | Stage 8. Zero JSON-LD. |
| Protectli, Puget Systems | WooCommerce theme hints | US | Stage 7. Store API confirmed absent (404/500). |
| System76 | Real product pages (adder-pro, darter-pro, lemur-pro, oryx-pro) | US | Stage 8. Live-updating price configurator UI, zero JSON-LD — needs JS execution, same class of blind spot as ASUS. |

## Confirmed-blocked (bot/WAF, evidenced with a real 403 + signature)

| OEM | Signature | Region | Notes |
|---|---|---|---|
| Lenovo (direct PDP), MSI | HTTP 403, Akamai/Cloudflare | Global | Stage 7, reconfirmed Stage 8 and Stage 9 |
| Origin PC, Framework, Zotac | HTTP 403, Cloudflare challenge | US | Stage 5 |
| Juno Computers | HTTP 418 (deliberate anti-bot status) | CA | Stage 8, new finding |

## Confirmed-requires-JS (real fetch, page ships a client-rendered payload, not data)

| OEM | Evidence | Region | Notes |
|---|---|---|---|
| ASUS | `window.__NUXT__=(function(...){...})(...)` — minified function call, not JSON | Global | Stage 7, reconfirmed Stage 9. Page itself is reachable (200, no bot markers) — the gap is rendering, not access. A human devtools check for a public API the Nuxt app calls has never been done |
| System76 | See "confirmed-not-a-fit" above — configurator UI | US | Stage 8 |
| OnLogic | Next.js app; sitemap has only 51 URLs, all locale variants of a "product-finder" tool, no product-detail pages indexed at all | US | Stage 8, distinct from ASUS's shape — not confirmed JS-required so much as confirmed "no product pages are even in the discoverable set" |
| Kontron | Nuxt-hydrated, zero JSON-LD on root | Global | Stage 8, root-only check |

## Confirmed-real-but-below-production-bar (structured data exists but too sparse/inconsistent)

| OEM | Evidence | Notes |
|---|---|---|
| Axiomtek | Real sitemap (1,348 URLs, 364 product-detail-shaped), real Product JSON-LD confirmed on 1 of 8 sampled product pages (`aie810-onx` — real sku/mpn/name/offers) | Stage 8. The JSON-LD template is not applied consistently across Axiomtek's own catalog — motherboards, AMR controllers, and most edge-AI siblings checked had zero JSON-LD even though they're the same general product family as the one page that did. Enabling now would mean the collector silently misses ~87%+ of the real catalog with no way to distinguish "not a product" from "template doesn't emit JSON-LD here." Revisit only if a broader sample shows better coverage. |

## Inconclusive (fetch failed in a way that doesn't distinguish blocked/slow/broken)

| OEM | Failure mode | Region | Notes |
|---|---|---|---|
| Acer | Read-timeout on root and product pages — Stage 7, Stage 8, and Stage 9 (20s/25s/40s attempts), the same symptom three stages running | Global | Persistence across 3 stages argues against "unlucky network," but still no explicit block signature — needs a different egress IP or an owner probe |
| HP | Stage 9 narrowed this: root (`hp.com/`) is a clean 200, zero bot markers, zero JSON-LD, no sitemap. Only the catalog path (`/us-en/shop/laptops`) times out, at both 20s and 60s | US | Not domain-wide — scoped to shop/catalog-shaped paths specifically. Reads like a silent soft-throttle on paths that look like scraping targets, distinct from Acer's total-domain silence |
| Advantech, Neousys | No sitemap found (root, `/en/`, `robots.txt` has no sitemap directive) | TW | Stage 8. Genuinely unresolved discovery, not a data-quality question yet |
| TUXEDO | No sitemap; root nav has no direct laptop-model links (informational pages only); robots.txt shows a PrestaShop-style storefront path not yet located | DE | Stage 8 |
| Slimbook | Sitemap URL returns intermittent HTTP 500 (probe caught 200 once, retest got 500) | ES | Stage 8. Server-side flakiness, not a block |
| Portwell | TLS certificate chain fails verification (`SSL: CERTIFICATE_VERIFY_FAILED`) | TW | Stage 8. A real, distinct failure mode — broken infra on their end, not a bot block |
| Insurgo | `shop.insurgo.ca` fails DNS resolution entirely | CA | Stage 8. Likely a stale/wrong subdomain — needs the current real storefront URL, not a re-probe of the same one |
| Supermicro Edge | The specific `/en/products/system/edge` URL 404s | US | Stage 8. Wrong path, not evidence about the platform — needs the real current URL |

## Wrong target / stale / structurally broken

| OEM | Notes |
|---|---|
| Panasonic Toughbook, Fujitsu | Corporate/marketing site, not a storefront |
| Dynabook | Sitemap resolves but content is Windows-8.1-era, abandoned |
| Purism | ~3 real product URLs in an otherwise blog-dominated sitemap, no JSON-LD |
| Trigkey | Real Shopify theme, store itself returns HTTP 402 (suspended/unpaid) |

## Undetermined (not yet probed with a real fetch)

TUXEDO's actual storefront path, Shuttle, Maxtang, LattePanda, MeLE,
AYANEO, Firebat, Peladn, GPD, Kingnovy — carried forward unchanged from
`docs/OEM_PLATFORM_MATRIX.md`; Stage 8 did not re-probe these (per this
stage's own instruction not to repeat Stage 5-7 recon without new reason).

## What this map says to do next

1. **Nothing to build.** Every confirmed-real opportunity this stage
   (Samsung) used an existing-or-newly-generalized engine, not a new one.
   The `category_jsonld` engine now exists and is proven on two structurally
   different real platforms (Samsung, Lenovo) — the next OEM using it is
   config + fixtures only.
2. **The two highest-value open questions are both discovery, not parsing**:
   Lenovo's UA-gating (a policy question this project has already answered:
   don't spoof) and Acer/HP's timeout ambiguity (an infrastructure/retry
   question — try from a different network/time before concluding anything).
3. **Axiomtek is the clearest "almost"** — real data exists, but at a
   coverage rate too low to trust in production. A wider sample (20-30
   pages instead of 8) would settle whether 1-of-8 was an unlucky sample or
   the real ceiling.
4. **Advantech/Neousys/TUXEDO/Slimbook/Insurgo/Supermicro** need a human to
   supply the actual correct entry URL before another automated probe pass
   is worth running — the failures found this stage are "wrong door," not
   "door is locked."

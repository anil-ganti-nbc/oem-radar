# Lenovo PSREF Deep Reconnaissance

**Written Stage 11 (2026-08-08).** Full characterization of
`psref.lenovo.com`'s real API surface (found Stage 10 by reading its own
published JS bundle text, confirmed here with deeper investigation)
before any collector decision. Every number below is from a real live
fetch with this project's honest UA — no browser execution, no spoofing.

## The confirmed endpoint

`GET https://psref.lenovo.com/api/ph/ProductCategoryTree` — no
authentication, no cookies, no special headers required beyond a normal
`Accept: application/json`.

**Response shape** (nested, nothing paginated — the whole catalog in one
response):

```
data.ProductClassificationList[]        (9 entries: Laptops, Desktops, ...)
  .ClassificationName, .ClassificationImage
  .ProductLineList[]                     (Lenovo brand line: ThinkPad, IdeaPad, Legion, ...)
    .ProductLine
    .ProductSeriesList[]                 (134 entries total: "C Series", "E Series", ...)
      .SeriesName, .IsExistNewProduct
      .ProductList[]                     (1,544 entries total — the real product records)
        .ProductID        int, stable-looking, e.g. 1523
        .ProductName       "ThinkPad C13 Yoga Gen 1 Chromebook"
        .ProductKey        "ThinkPad_C13_Yoga_Gen_1_Chromebook" — URL slug, unique
        .ImageURL           real CDN image URL
        .Withdraw           0 or 1 — see "current vs. historical" below
        .IsDigitalSpec      0 or 1
        .IsNewProduct       0 or 1
```

## Request cost for a full crawl of what this endpoint gives you

**One request.** This is a bulk-inline shape, architecturally identical
to `shopify`'s `/products.json` or `woocommerce_store_api`'s Store
API — discovery and data arrive together, no per-product fetch needed
for anything this endpoint itself exposes.

## Caching / repeat-call behavior

- `Cache-Control: public, max-age=3600, s-maxage=86400, stale-while-revalidate=600`
- Served via Akamai; `Server-Timing: cdn-cache; desc=HIT` on both of two
  calls made 2 seconds apart — genuinely CDN-cached, cheap to poll.
- **No `ETag` or `Last-Modified`** — this endpoint does not support
  conditional GET (`If-None-Match`/`If-Modified-Since`). A client can't
  get a cheap 304; every request re-transfers the full ~450KB body
  (though the CDN itself absorbs most of the real cost on Lenovo's side).
- Two calls seconds apart returned byte-identical bodies (SHA-256
  matched) — stable, not randomized per-request.

## Current vs. historical products — a real, usable status field

`Withdraw` is a genuine current/discontinued flag, computed directly from
the real response:

| Withdraw | Count | Meaning |
|---|---|---|
| 0 | 592 | Current (not withdrawn) |
| 1 | 952 | Withdrawn/discontinued |
| **Total** | **1,544** | |

This means PSREF's 1,544 records are **not** "1,544 current products" —
they're the full historical catalog, 38.3% of which is still current.
Any future collector must filter on `Withdraw == 0` to scope to "what
Lenovo currently sells," exactly the same class of scoping work
`category_jsonld`/`woocommerce_store_api` already do via
`category_include`/`non_product_terms`.

`IsNewProduct` is true for only 3 of 1,544 — likely a "recently added to
PSREF" flag, probably useful as a secondary signal but far too sparse to
be the primary discovery mechanism.

## What this endpoint does NOT give you — and the central open question

The category tree gives identity-and-status fields only: no CPU, GPU,
RAM, storage, display, weight, dimensions, OS, wireless, or **machine
type/MTM**. Getting those requires a per-product detail fetch — and this
recon **could not find that endpoint**.

Read the actual JS the product-detail page (`product-CVjO0cC-.js`) ships,
plus every module it references (`utils-*.js`, `apiUtils-*.js`,
`Layout-*.js`, `index-*.js`) — none contain a literal `/api/...` path for
per-product data (the one real API path found, `/api/product/info/
GoWhereToBuy`, is a "where to buy" redirect helper, not spec data). Tried
nine plausible endpoint-name guesses based on Lenovo's own naming
convention (`ProductInfo`, `ProductDetail`, `GetProductInfo`, `Product/
{id}`, etc.) against a real `ProductID`/`ProductKey` — **all 404**. This
means the real call is very likely constructed from data fetched by a
separate, not-yet-found bootstrap call (e.g., a per-product config object
fetched by ID through a path built from string concatenation the static
analysis here didn't resolve), which static analysis of minified JS
cannot reliably reconstruct further. **This is exactly the situation
`docs/OWNER_DEVTOOLS_GUIDE.md` exists for** — recommended as the next
concrete step, not more blind guessing (see "Do not re-probe" constraint
this stage set for dead sources, applied here by extension: nine
guesses is enough).

## Identity hierarchy — proposed, but explicitly provisional

Lenovo's real nomenclature (confirmed via the response) has at least
three levels visible in this endpoint alone:

```
ClassificationName  (Laptops)
  └─ ProductLine     (ThinkPad)
       └─ SeriesName  (C Series)
            └─ ProductKey/ProductID  (ThinkPad_C13_Yoga_Gen_1_Chromebook / 1523)
```

Stage 11's instruction is explicit: do not flatten this prematurely, and
prefer an exact MTM/SKU over a normalized marketing name if one is
exposed. **It is not exposed at this level**, and this recon could not
reach the level where it might be. This is the single most important
unresolved question before any implementation:

**Does one `ProductKey` (e.g. "ThinkPad C13 Yoga Gen 1 Chromebook")
represent one sellable configuration, or — per Lenovo's well-known dense
nomenclature — does it collapse multiple distinct MTM/CPU/RAM
configurations under one entry?** This project already has a real,
documented incident of exactly this failure mode (Stage 8: Samsung
listings sharing a coarse model name but carrying distinct SKUs/RAM/price
were nearly merged by `resolve_prior`'s coarse fallback — see
`docs/STAGE8.md` and the `resolve_prior` vendor-SKU-disagreement guard it
produced). Building any collector on `ProductKey` alone, without first
confirming whether it's SKU-granular or family-granular, risks the exact
same class of bug from day one.

**Provisional identity recommendation, pending confirmation**:
`ProductKey` is stable, unique (used as the real URL slug), and
guaranteed collision-free across the whole catalog — a legitimate
fallback identity anchor if nothing more granular is ever found. But it
must **not** be treated as SKU-equivalent, and no collector should be
built on the assumption that it is, until a human DevTools capture (or
future reconnaissance) confirms the real granularity of a `ProductKey`
entry.

## PSREF change-value matrix (Stage 11 Track 1 deliverable)

Speculative — based on what fields exist, not on observed real diffs
(this project has zero real repeat-crawl history for PSREF, since no
collector exists yet):

| Field | Change frequency (expected) | Identity importance | Editorial usefulness | Likely noise level |
|---|---|---|---|---|
| New `ProductKey` appears | Low-moderate (new model launches) | Very high — this IS the new-product signal | High — a new Lenovo model is real news | Low |
| `Withdraw` flips 0→1 | Low-moderate | High | Medium — "Lenovo discontinued X" is a real story, lower urgency than a launch | Low |
| `IsNewProduct` flips 1→0 | Unknown cadence | Low | Low — looks like a PSREF-internal housekeeping flag, not a market event | Possibly high (unclear semantics) |
| Per-product CPU/GPU/RAM/storage option added *(unconfirmed field, pending per-product endpoint)* | Unknown | High | High — a new configuration is genuinely newsworthy | Unknown |
| `ImageURL` changed | Likely low | None | Very low | High if tracked naively |
| `ProductName` text changed | Low | Medium (could signal a rebrand) | Low-medium | Medium |

This matrix should be revisited once real per-product fields are
confirmed — it is deliberately conservative and flags its own biggest gap
(no confirmed spec-level fields yet).

## Production suitability verdict (Track 1 close-out)

**Not yet production-ready, and specifically not for the reason Stage 11
asked to check for.** The category-tree endpoint alone is real,
enumerable, cheap (1 request, CDN-cached), and gives a genuine new-model
and discontinuation signal via `Withdraw`. But:

1. The central identity question (SKU-granular vs. family-granular) is
   unresolved — building on `ProductKey` without confirming this risks
   repeating the Samsung/Stage 8 identity bug on day one, this time with
   no way to even detect it (no vendor SKU field exists at this level to
   guard against it, unlike Samsung's case).
2. No confirmed spec fields (CPU/RAM/etc.) — a launch-only feed of
   `ProductName`/`Withdraw` is real signal, but noticeably thinner than
   what every existing enabled engine provides.

**Recommendation**: do not build a collector this stage. Add PSREF to
the DevTools reconnaissance target list (alongside ASUS) for the next
owner-assisted session — one real per-product page capture would very
likely resolve both open questions (the detail endpoint's shape, and
whether it exposes MTM-level identity) in one pass.

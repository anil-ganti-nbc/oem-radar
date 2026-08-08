# Alternate Source Matrix — Stage 11

**Written 2026-08-08.** Every row is a real live fetch with this
project's honest UA (no auth, no spoofing, no JS execution — API paths
were found by reading fetched JS bundle *text*, the same class of action
as reading any other document). This is the evidence base for this
stage's trigger decision.

| OEM | Surface | Public URL | Access status | Discovery mechanism | Enumerable? | Model identifier | Pagination | Structured data? | Anti-bot | Update cadence | Signal value |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Lenovo | PSREF product taxonomy | `psref.lenovo.com/api/ph/ProductCategoryTree` | 200, no auth | Found by reading `product-*.js`'s own text (Stage 10) | **Yes** — 1,544 real products in one response | `ProductID` (int) + `ProductKey` (string slug), both stable across repeat calls | None needed — single bulk response | Yes — real JSON, `Withdraw`/`IsNewProduct` status flags | None observed | Unknown (no repeat-crawl history yet) | High — real new-model + discontinuation signal, see `docs/PSREF_RECON.md` |
| Lenovo | PSREF per-product specs | Unconfirmed endpoint | N/A | 9 endpoint-name guesses tried, all 404; static analysis of every referenced JS chunk found no literal path | No — endpoint not found | N/A | N/A | Unconfirmed | N/A | N/A | Unconfirmed — pending human DevTools |
| Lenovo | Support/pcsupport/download | `support.lenovo.com`, `pcsupport.lenovo.com`, `download.lenovo.com` | **403**, reconfirmed this stage | N/A | No | N/A | N/A | N/A | Same signature as storefront | N/A | None — same closed door already declined (UA-gating) |
| Lenovo | Newsroom | `news.lenovo.com` | 200 | WordPress (`wp-json` present) | Technically yes (WP REST API) | Post ID | Standard WP pagination | Yes | None | Unknown | **Explicitly excluded by this stage's own rule** ("do not count a newsroom RSS feed") — not counted toward the trigger regardless of technical merit |
| **HP** | Support product-category navigation | `support.hp.com/wcc-services/prodcategory/getProductCategoriesBySeoName` (POST) | 200, no auth | Found by reading `main.*.js`'s own text | **Yes** — confirmed 18 real laptop sub-brand categories (Pavilion, ENVY, EliteBook, OMEN, Spectre, ...) from one call | `oid` (numeric) + `uid` (long numeric) + `seoLabel`, confirmed **stable across repeat calls** (identical `oid` list twice) | Category-navigation tree; leaf-level product enumeration not yet reached this stage | Yes — real JSON with names, image URLs, stable IDs | None observed | Unknown | Medium (confirmed) — real, stable brand/family taxonomy; whether it reaches individual SKU level is unconfirmed |
| HP | Support specifications/manuals API family | `support.hp.com/wcc-services/pdp/specifications/`, `.../pdp/manuals/getManuals`, `.../pdp/category-details` | Endpoints **confirmed to exist** (structured error responses, not blanket 404s) — exact request shape for leaf-level data not resolved this stage | Found by reading `main.*.js`'s own text | Unconfirmed at leaf level | Unconfirmed | Unconfirmed | Unconfirmed | None observed | N/A | Real, but unresolved this stage — same class of gap as Lenovo's per-product endpoint |
| HP | QuickSpecs legacy subdomain | `h20195.www2.hp.com` | TLS certificate failure | N/A | No | N/A | N/A | N/A | Broken infra, not a block | N/A | None — infra failure, not a signal source |
| ASUS | Support root | `asus.com/support/` | 200 | N/A | No | N/A | N/A | Only `BreadcrumbList`/`Organization` JSON-LD | None | N/A | None found |
| ASUS | Download Center | `asus.com/support/Download-Center/` | 200, structurally different from storefront (no `__NUXT__` marker on this shell) | Unconfirmed | Unconfirmed | Unconfirmed | Unconfirmed | Unconfirmed | None | N/A | Inconclusive, not negative — flagged for the same DevTools session as the ASUS storefront investigation |
| MSI | Support root | `msi.com/support` | **403** | N/A | No | N/A | N/A | N/A | Same signature as storefront | N/A | None |
| Acer | Support root | `acer.com/us-en/support` | Connection reset / timeout | N/A | No | N/A | N/A | N/A | Same silent-stall signature as storefront | N/A | None |
| Dell | Support home | `dell.com/support/home/en-us` | 200 | Real API traces found (`/support/client/api/52/eSupportClientApi`, warranty/incident lookups) | Structurally different in kind — service-tag/warranty-oriented, not a browsable catalog | Service tag (requires already owning the product) | N/A | Likely yes, unconfirmed | None | N/A | **Different kind of surface, not a catalog** — doesn't compete with PSREF/HP's model; Dell's own storefront collector already covers what a catalog surface would provide |

## Trigger evaluation

**Trigger A (2 OEMs with useful enumerable alternate official data): MET.**
Lenovo (PSREF's `ProductCategoryTree`) and HP (`prodcategory/
getProductCategoriesBySeoName`) both independently satisfy the bar set
before this investigation began: official (each OEM's own domain),
public (no auth, no spoofing), enumerable (both return real, structured,
multi-entry JSON lists in one call), stable identity (`ProductKey`/
`ProductID` for Lenovo, `oid`/`uid` for HP — both verified stable across
repeat calls in this session), and useful product intelligence (real
model/category names, not placeholder or navigational-only data).

**Trigger B (1 OEM + 3 materially independent evidence types): NOT MET
for either OEM.** Lenovo has exactly one confirmed type (PSREF); its
other three candidate surfaces (support, download, pcsupport) are all
blocked by the identical UA-gating already declined as a spoofing
target — not independently confirmed, the same closed door checked three
more times. HP has one confirmed type (the category-navigation API); its
specifications/manuals endpoints exist but their exact request shape
wasn't resolved this stage, so they're "found but not yet working," not
independently confirmed.

**Decision: implementation is justified. Trigger A fired.** See
`docs/STAGE11.md` for the resulting architecture decision (Track 6) and
what was actually built.

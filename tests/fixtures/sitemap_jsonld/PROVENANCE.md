# Fixture provenance — tests/fixtures/sitemap_jsonld/

Per the real-fixture policy: every file here is an unmodified capture of a
real, public HTTP response. No HTML/XML/JSON is hand-written or invented.
Malformed-input test fixtures used in the test suite (truncated XML, broken
JSON-LD) are deliberately hand-written to test parser robustness — those are
never presented as real vendor captures, and are inlined directly in test
code rather than stored here, to keep this directory's contents honestly
100% real.

| File | OEM | Source URL | Capture date | Response type | Notes |
|---|---|---|---|---|---|
| `simplynuc_sitemap_index.xml` | SimplyNUC | `https://snuc.com/sitemap.xml` | 2026-08-07 | WordPress/Yoast sitemap index | Lists product/post/category/etc. sub-sitemaps |
| `simplynuc_product_sitemap.xml` | SimplyNUC | `https://snuc.com/product-sitemap.xml` | 2026-08-07 | WooCommerce product sitemap leaf | 137 real product URLs |
| `simplynuc_product_ee1000.html` | SimplyNUC | `https://snuc.com/product/ee-1000/` | 2026-08-07 | full product page HTML | Real Product JSON-LD in `@graph`; sku/mpn populated, price=`"0"` (this vendor's real "quote required" placeholder — used as the "missing/unusable price" test case) |
| `simplynuc_product_nuc15tzu7.html` | SimplyNUC | `https://snuc.com/product/nuc15tzu7/` | 2026-08-07 | full product page HTML | Real NUC product; sku/mpn both empty strings in JSON-LD (missing-SKU test case), price also `"0"` |
| `simplynuc_product_giftcard.html` | SimplyNUC | `https://snuc.com/product/simply-nuc-e-gift-card/` | 2026-08-07 | full product page HTML | Real non-product accessory (gift card) with a genuine non-zero price (`$25`) — used to confirm the denylist filters it regardless of having real pricing |
| `khadas_sitemap_index.xml` | Khadas | `https://www.khadas.com/sitemap.xml` | 2026-08-07 | Wix-generated sitemap index | `generatedBy="WIX"` |
| `khadas_product_sitemap.xml` | Khadas | `https://www.khadas.com/store-products-sitemap.xml` | 2026-08-07 | Wix Stores product sitemap leaf | 78 real product URLs, includes both SBCs and accessories |
| `khadas_product_vim3.html` | Khadas | `https://www.khadas.com/product-page/vim3` | 2026-08-07 | full product page HTML | Real single-board-computer product; JSON-LD uses non-standard `Offers`/`Availability` casing (real-world schema quirk — this is the fixture that motivated the case-insensitive field lookup in the engine) |
| `khadas_product_adapter.html` | Khadas | `https://www.khadas.com/product-page/usb-c-24w-adapter` | 2026-08-07 | full product page HTML | Real accessory listing, used for denylist filtering test |
| `medion_product_sitemap.xml` | Medion | `https://www.medion.com/de/shop/sitemap/Product-de-DE-medion-de-EUR.xml` | 2026-08-07 (Stage 7) | dedicated Product sitemap leaf | 6,265 real URLs spanning Medion's entire consumer-electronics catalog (fridges, radios, vacuums, TVs, PCs); used to derive and test the `url_include_pattern` scoping to gaming-line PC/notebook categories only |
| `medion_product_erazer_x17805.html` | Medion | `https://www.medion.com/de/shop/p/high-end-gaming-notebooks-medion-erazer-...` | 2026-08-07 (Stage 7) | full product page HTML | Real ERAZER gaming notebook; JSON-LD has `mpn` + real `offers` (price 1649.95 EUR, `OutOfStock`) |
| `lg_us_sitemap.xml` | LG | `https://www.lg.com/us/sitemap.xml` | 2026-08-07 (Stage 7) | full US-site sitemap (not sitemap-index) | 6,220 URLs across all of LG's US catalog (TVs, appliances, phones, laptops); used to derive/test `url_include_pattern` scoping to the 182 real `.../laptops/lg-...-gram-laptop` product pages |
| `lg_product_14t90q.html` | LG | `https://www.lg.com/us/laptops/lg-14t90q-k.aab6u1-gram-laptop` | 2026-08-07 (Stage 7) | full product page HTML | Real gram laptop; JSON-LD has real `offers` (price $1299.99 USD) but no `sku`/`mpn` field — identity instead comes from the URL slug itself, which embeds LG's own model code |

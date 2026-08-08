# Fixture provenance — tests/fixtures/category_jsonld/

Per the real-fixture policy: every file here is a trimmed-but-unmodified
capture of a real, public HTTP response — trimmed to `<head>` + the JSON-LD
`<script>` blocks the engine actually parses (dropping ~400KB of unrelated
CSS/JS/nav markup), never hand-written or invented. Malformed-input test
fixtures (truncated JSON, an `ItemList` with no real products) are
deliberately hand-written to test parser robustness and are inlined
directly in `tests/test_category_jsonld_engine.py` rather than stored here.

| File | OEM | Source URL | Capture date | Response type | Notes |
|---|---|---|---|---|---|
| `samsung_galaxy_book_category.html` | Samsung | `https://www.samsung.com/us/computers/galaxy-book/` | 2026-08-07 (Stage 8) | category listing page HTML (trimmed) | Real `ItemList` JSON-LD, `numberOfItems: 12`, 12 real `Product` nodes each with `name`/`offers.price`/`offers.availability`/`image`/`url`. No `sku`/`mpn` field on the nested items — real Samsung SKUs (e.g. `NP960UJH-XG7US`) are only present as a URL suffix, which is why the engine falls back to a configurable `sku_url_pattern` regex. Also carries a `BreadcrumbList` and a `WebPage` JSON-LD node (both real, both non-Product) — used to confirm the engine only extracts the `ItemList`'s nested products and ignores the other two node types. |
| `lenovo_buy_thinkpad_p_series.html` | Lenovo | `https://www.lenovo.com/buy/us/en/amd-ryzen-7-pro-thinkpad-p-series-laptops-0arz00a` | 2026-08-07 (Stage 8) | curated marketing/deals landing page HTML (trimmed) | Real `ItemList` with 24 real `Product` nodes (real `sku`/`offers.price`/`offers.availability`). Found via Stage 8 Phase 2 recon after direct PDP fetches (`/us/en/p/laptops/...`) confirmed HTTP 403 — this landing-page URL is not behind that block. Several SKUs share the exact model name `"ThinkPad P14s Gen 7 AMD (14” ) Mobile Workstation"` at different prices/configs — the real-world case that motivated the Stage 8 `resolve_prior` fix (see `tests/test_sqlite_store.py::test_resolve_prior_distinct_vendor_skus_never_merge`). |
| `lenovo_buy_wide_screen_laptops.html` | Lenovo | `https://www.lenovo.com/buy/us/en/intel/wide-screen-laptops-0abz00a` | 2026-08-07 (Stage 8) | curated marketing/deals landing page HTML (trimmed) | Real `ItemList` with 20 real `Product` nodes, mixed IdeaPad/Yoga/ThinkBook lines. |
| `lenovo_buy_laptops_under_800.html` | Lenovo | `https://www.lenovo.com/buy/us/en/laptops-under-800-0akz00a` | 2026-08-07 (Stage 8) | curated marketing/deals landing page HTML (trimmed) | Real `ItemList` with 20 real `Product` nodes, budget-tier IdeaPad/LOQ models. |

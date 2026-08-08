# Fixture provenance — tests/fixtures/woocommerce/

Per the real-fixture policy: every file here is an unmodified capture of a
real, public `/wp-json/wc/store/v1/...` response. No JSON is hand-written
or invented. Malformed-input test fixtures (used for parser-robustness
tests only) are inlined directly in test code, never stored here.

| File | OEM | Source URL | Capture date | Notes |
|---|---|---|---|---|
| `geekom_products_p1.json` | GEEKOM | `https://www.geekompc.com/wp-json/wc/store/v1/products?per_page=100&page=1` | 2026-08-07 | 77 products = full catalog (single page, `X-WP-Total: 77`) |
| `geekom_categories.json` | GEEKOM | `https://www.geekompc.com/wp-json/wc/store/v1/products/categories?per_page=100` | 2026-08-07 | 64 real categories |
| `novacustom_products_p1.json` | NovaCustom | `https://novacustom.com/wp-json/wc/store/v1/products?per_page=100&page=1` | 2026-08-07 | Page 1 of 275 total (`X-WP-Total: 275`, `X-WP-TotalPages: 55`) |
| `novacustom_products_p2.json` | NovaCustom | `https://novacustom.com/wp-json/wc/store/v1/products?per_page=100&page=2` | 2026-08-07 | Page 2 — captured specifically to exercise real pagination in tests |
| `novacustom_categories.json` | NovaCustom | `https://novacustom.com/wp-json/wc/store/v1/products/categories?per_page=100` | 2026-08-07 | 35 real categories |
| `pine64_products_p1.json` | Pine64 | `https://pine64.com/wp-json/wc/store/v1/products?per_page=100&page=1` | 2026-08-07 | Page 1 of 213 total |
| `pine64_categories.json` | Pine64 | `https://pine64.com/wp-json/wc/store/v1/products/categories?per_page=100` | 2026-08-07 | 72 real categories |

## Notes

- **Minor-unit pricing**: the Store API returns `prices.price` as a string
  of the amount in minor units, scaled by `prices.currency_minor_unit`.
  GEEKOM's is `0` (whole-dollar USD); NovaCustom/Pine64 use `2` (cents).
  Dividing by a hardcoded 100 would silently misprice GEEKOM by 100x —
  this is exactly why the engine reads `currency_minor_unit` per-product
  rather than assuming a fixed scale. See
  `tests/test_woocommerce_engine.py::test_geekom_zero_minor_unit_pricing`.
- **Real false positive found and fixed during this stage**: the engine's
  first denylist draft included the word "keyboard" (meant to filter
  standalone keyboard accessories) — this incorrectly matched Pine64's real
  product `"14″ PINEBOOK Pro LINUX LAPTOP (UK Keyboard)"`, a genuine laptop
  whose title happens to name its keyboard layout. Removed "keyboard"/
  "mouse" from the engine's built-in denylist; NovaCustom's own standalone
  "DVORAK keyboard (USB)" accessory is filtered via a source-scoped
  `non_product_terms` entry instead, where it can't collide with anyone
  else's product names.
- NovaCustom's raw catalog (275 items) is dominated by refurbished/
  second-hand/returned inventory and spare parts; `category_include`/
  `category_exclude` + `non_product_terms` scope it to 6 real current
  listings. Pine64's raw catalog (213 items) spans phones/tablets/SBCs/
  accessories; scoped to its 2 real current Pinebook Pro SKUs (UK/US
  keyboard-layout variants).

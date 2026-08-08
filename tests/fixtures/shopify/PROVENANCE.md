# Fixture provenance — tests/fixtures/shopify/

Per the real-fixture policy (Stage 5): every fixture here is an unmodified
capture of a real, public `/products.json` response. No HTML/JSON is
hand-written or invented. New entries go at the bottom.

| File | OEM | Source URL | Capture date | Response type | Sanitization |
|---|---|---|---|---|---|
| `gmktec_products.json` | GMKtec | `https://www.gmktec.com/products.json` | pre-Stage-5 (undated) | Shopify `products.json` | none recorded |
| `bosgame_products_p1.json` | Bosgame | `https://bosgame.com/products.json?limit=250&page=1` | pre-Stage-5 (undated) | Shopify `products.json` | none recorded |
| `nipogi_products_p1.json` | NiPoGi | `https://www.nipogi.com/products.json?limit=250&page=1` | pre-Stage-5 (undated) | Shopify `products.json` | none recorded |
| `acemagic_products_p1.json` | ACEMAGIC | `https://acemagic.com/products.json?limit=250&page=1` | pre-Stage-5 (undated) | Shopify `products.json` | none recorded |
| `kamrui_products_p1.json` | KAMRUI | `https://kamrui.com/products.json?limit=250&page=1` | pre-Stage-5 (undated) | Shopify `products.json` | none recorded |
| `vaio_products_p1.json` | VAIO | `https://us.vaio.com/products.json?limit=250&page=1` | 2026-08-07 | Shopify `products.json`, page 1 (165 products = full catalog; page 2 empty) | none — raw response, re-serialized with `json.dump(..., ensure_ascii=False, indent=2)` for readability, no field changes |
| `morefine_products_p1.json` | Morefine | `https://www.morefine.com/products.json?limit=250&page=1` | 2026-08-07 | Shopify `products.json`, page 1 (40 products = full catalog) | none — raw response, re-serialized with `json.dump(..., ensure_ascii=False, indent=2)` for readability, no field changes |
| `starlabs_products_p1.json` | Star Labs | `https://starlabs.systems/products.json?limit=250&page=1` | 2026-08-07 | Shopify `products.json`, page 1 (111 products = full catalog) | none — raw response, re-serialized for readability, no field changes |

## Notes

- VAIO's catalog is 165 items but only 8 are real laptops — 157 are
  `product_type: "Warranty"` (extended-warranty/repair-plan SKUs). These are
  filtered automatically by the existing `_DEFAULT_NON_PRODUCT` denylist in
  `engines/shopify/__init__.py` (matches "warranty" via `product_type`), no
  engine or config change needed.
- Morefine's real storefront is `www.morefine.com`, not `store.morefine.com`
  as previously configured in `config/oems/morefine.yaml` — the old base_url
  was stale/wrong, which is very likely *why* it was never actually verified
  live before being marked `enabled: false`. Two items have
  `product_type: "shipping-protection"`, filtered via a per-source
  `non_product_terms: ["shipping-protection"]` addition in the descriptor
  (config-driven, not a code change).
- Star Labs (Stage 7): only 19 of 111 raw catalog entries are real laptop
  listings (12 distinct StarBook/StarFighter/StarLite models, some with
  multiple pre-built config SKUs — real catalog behavior, not noise). The
  other ~85% are spare parts sold directly (mainboards, batteries, displays,
  input covers, daughter boards) plus OS licenses/recovery media, none of
  which the built-in denylist covered. `config/oems/starlabs.yaml`'s
  `non_product_terms` list was derived empirically against this fixture —
  see `tests/test_stage7_starlabs_medion_lg.py`.

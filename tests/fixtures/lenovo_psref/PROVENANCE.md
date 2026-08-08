# Provenance — lenovo_psref fixtures

## psref_product_category_tree_trimmed.json

- **Source**: `GET https://psref.lenovo.com/api/ph/ProductCategoryTree`
- **Captured**: 2026-08-08 (Stage 11), with this project's honest declared
  UA (`OEMRadar/0.1 (product-intelligence; respectful crawler;
  contact@x8.design)`), no auth, no cookies.
- **Real data, trimmed for size**: the live response is ~450KB covering
  1,544 products across 9 classifications / 134 series. This fixture
  keeps one real classification (`Laptops`), one real product line
  (`ThinkPad`), and the first 2 real series with their first 3 real
  products each — every field is a real, unmodified value from the live
  API, nothing invented or hand-written.
- **Real quirk preserved**: both kept products have `Withdraw: 1`
  (discontinued) — this is genuinely what the live data returns for these
  two specific ThinkPad C-Series Chromebooks, not a fixture artifact. A
  hand-written malformed-JSON variant is used separately in
  `tests/test_lenovo_psref_evidence_source.py` for parser-robustness
  checks only (never presented as a real capture), per this project's
  standing fixture convention.

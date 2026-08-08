# Axiomtek Wide Sample — Stage 10 Track 3

**Written 2026-08-07.** Stage 8 sampled 8 Axiomtek product pages and
found real Product JSON-LD on 1 of them (12.5%) — too small a sample to
tell "rare template" from "unlucky sampling." Stage 10 resolves this with
a wider, reproducible sample.

## Threshold, defined before sampling

- **≥ 80% structured coverage**: strong candidate — proceed to fixtures/
  config/enable.
- **50-79%**: `LIVE_PARTIAL` — investigate template scoping (maybe one
  sub-category consistently has it).
- **< 50%**: reject for the generic `sitemap_jsonld`/`category_jsonld`
  engines. Do not write a bespoke parser for a single vendor at this
  coverage level — the project's stated bar for a reusable engine is ≥3
  confirmed OEMs, and a bespoke one-OEM engine at <50% real-data coverage
  has no precedent or justification anywhere in this project's history.

## Method

1. Fetched `axiomtek.com/sitemap.xml` live (1,348 total URLs).
2. Filtered to real product-detail URLs: path contains `/products/` and
   the final URL segment contains at least one digit (excludes
   category-index pages like `.../nvidia-jetson-system/`, keeps model
   pages like `.../nvidia-jetson-system/aie810-onx`). This produced 367
   URLs — consistent with Stage 8's cited "364 product-detail-shaped."
3. Grouped by top-level category (`systems-and-platforms`,
   `boards-and-modules`, `panel-pcs-and-monitors`,
   `intelligent-solutions`, `industrial-panel-pcs`).
4. Took a **reproducible stratified sample**: within each category,
   sorted URLs alphabetically and took every Nth one, proportional to
   that category's real share of the 367 — not hand-picked, not biased
   toward pages likely to already have JSON-LD. 31 URLs resulted (target
   was 30).
5. Fetched each of the 31 with this project's honest UA and checked for
   real `Product`-typed JSON-LD via `core.jsonld.extract_jsonld_nodes` —
   the exact same extraction logic the `sitemap_jsonld`/`category_jsonld`
   engines and `core/probe.py` use, not a separate ad hoc check.

## Result

**4 / 31 = 12.9%** had real Product JSON-LD (`imb711`, `got710a`,
`aie015-at`, `aie900b-onx`) — all with `sku`/`mpn`, `offers`, and
`image` present when JSON-LD was found at all (i.e. when the template
fires, it fires completely; the problem is purely that it doesn't fire
on most pages).

| Category sampled | URLs in sample | JSON-LD hits |
|---|---|---|
| `boards-and-modules` | 11 | 1 (`imb711`) |
| `systems-and-platforms` | 12 | 2 (`aie015-at`, `aie900b-onx`) |
| `panel-pcs-and-monitors` | 5 | 0 |
| `intelligent-solutions` | 1 | 0 |
| `industrial-panel-pcs` | 1 | 1 (`got710a`) |
| `products/compare` (navigational, excluded) | — | — |

**12.9% falls decisively below the 50% reject threshold.** This
confirms — not merely repeats — Stage 8's 12.5% finding: two independent
samples (8 pages, then a reproducible 31-page stratified sample) landed
within half a percentage point of each other. That is strong evidence
this is a stable, real ceiling for Axiomtek's catalog, not sampling
noise.

## Observation (not the deciding factor)

All 4 hits cluster around two product families: AI edge-computing
systems (`aie015-at`, `aie900b-onx` — Nvidia Jetson-based) and a subset
of motherboards/panel-PCs. This is consistent with Axiomtek applying a
newer JSON-LD template only to a subset of product lines, not a random
subset of pages. That's a real, interesting pattern — but it doesn't
change the verdict: even if a future engineer wanted to scope collection
to just the `edge-ai-gpu-computing/nvidia-jetson-system` sub-category,
that would require confirming a much higher hit rate *within* that
narrower scope specifically, which this sample didn't test (only 2 of
the 12 `systems-and-platforms` sample URLs were from that exact
sub-path). Worth a note for whoever revisits Axiomtek, not a Stage 10
action item.

## Decision

**Rejected for the generic JSON-LD engines, decisively.** Axiomtek is
parked with real, wide-sample evidence, not a stale "almost." No bespoke
parser was written.

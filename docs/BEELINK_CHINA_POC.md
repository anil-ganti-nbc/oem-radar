# Beelink China Proof-of-Concept (2026-08-12)

Follow-up to the ME Pro Ryzen AI 9 HX 470 live-miss investigation. That
investigation established `SOURCE_GAP` / `REGION_GAP`: the global
`bee-link.com` Shopify storefront (Radar's only Beelink source) never
contained the HX 470 ME Pro; the launch was China-first via Beelink's
official Weibo. This document records whether a first-party Chinese Beelink
web surface could close that gap without scraping Weibo.

## Source map

Honest-access reconnaissance of `bee-link.com.cn` (plain GET, standard UA,
no auth/CAPTCHA/rate-limit evasion):

| Surface | Status | Notes |
|---|---|---|
| `robots.txt` | 200 | `User-agent: *`, no directives, no `Sitemap:` line |
| `sitemap.xml` | 200 | **Empty body** — not a usable discovery surface |
| `/computer-73493777` (category page) | 200 | Client-rendered Vue app; static HTML has no product data, only `{{ item.title }}` templates |
| `/catalog/category/ajaxdata?cid=<n>` | 200 | **The real surface.** Plain unauthenticated JSON API backing the category page's Vue app. Found by reading the page's own inline `<script>` (`var ajaxUrl = ".../ajaxdata"`), not by guessing |
| `/catalog/product/index?id=<n>` (product detail page) | 200 | Server-rendered HTML, no additional JSON endpoint found, no timestamp fields |
| `/cms/support/index` | 200 | Navigation hub only, no product-level entries, no API |
| `/cms/support/driverhardware`, `/cms/support/productlist?id=7` | 200 (not deeply probed) | Out of scope for this PoC — catalogue API already answered the question |
| `/cms/news/index` | 200 | Static-looking; only two dates found on the page, both from 2021–2022. Not a live announcement feed |
| Weibo | out of scope | Not investigated further; already the known primary source |

**Best first-party source: `/catalog/category/ajaxdata?cid=<series>`.**
Category IDs are embedded in the category page's Vue `data()` (e.g.
`{"id":"84","name":"ME系列"}` = ME series). Response shape:

```json
{"status": "success", "data": [
  {"id": "1352", "spu": "SER10 MAX HX470", "title": "SER10 MAX HX470",
   "startPrice": "￥4599", "detailUrl": "https://www.bee-link.com.cn/catalog/product/index?id=1352",
   "configurations": [
     {"id": "1352", "CPU": "AI9 HX 470", "RAM": "0GB", "Storage": "0GB", "price": "￥4599"},
     {"id": "1354", "CPU": "AI9 HX 470", "RAM": "32G DDR5", "Storage": "1TB SSD", "price": "￥8259"}
   ]}
]}
```

Per Phase 1's checklist: server-rendered JSON (not HTML-embedded), fully
structured, model identity via numeric `id` (both product/spu-level and
per-configuration), CPU/RAM/Storage/price all present as explicit fields,
availability is implicit (absence = not offered), **no timestamp field of
any kind**, discovery is per-category `cid` (no pagination observed within
a category — ME series returned all 7 items in one response), stability
assessed only over two live passes minutes apart (identical both times).
Editorial value: high for identity/spec quality, unproven for speed (see
Timing evidence below).

## HX 470 status

| Check | Result |
|---|---|
| CHINA PRODUCT PAGE | NO |
| CHINA CATALOGUE ENTRY (`cid=84`, ME series) | NO — 7 items returned, none is an HX 470 ME Pro |
| CHINA SUPPORT ENTRY | Not found (not deeply probed beyond the nav hub) |
| CHINA DRIVER ENTRY | Not found (not deeply probed) |
| PUBLIC API ENTRY | NO |
| SITEMAP ENTRY | N/A — sitemap is empty |

**As of this investigation, the ME Pro HX 470 configuration does not exist
on Beelink's own structured China backend either** — only on Weibo. This is
the single most important finding: a Beelink China collector running today
would *not* have closed this specific incident's gap yet, because Beelink
itself has not yet propagated the Weibo announcement into its own product
database.

## Historical replay

Bounded comparison across the ME Pro / ME mini family, using only what was
directly retrievable from the two live catalogues (no fabricated
chronology):

| Configuration | CPU | China (`cid=84`) | Global (`bee-link.com`) | Known announcement | Classification |
|---|---|---|---|---|---|
| ME Pro N95 | N95 | YES (id 1294) | NO | UNKNOWN | `NOT_PROVEN` — China-only SKU, no timestamp to prove a catch, but demonstrates real coverage the global source structurally cannot provide |
| ME mini N200 | N200 | YES (id 1041) | NO | UNKNOWN | `NOT_PROVEN` |
| ME Pro 2-bay 13500H | Core i5-13500H | YES (id 1365) | NO exact match | UNKNOWN | `NOT_PROVEN` |
| ME Pro 4-bay 13500H / N150 | 13500H / N150 | YES (ids 1368, 1370) | NO (global's N150 SKU is 2-bay, a different config) | UNKNOWN | `NOT_PROVEN` — bay-count mismatch means these are not the same SKU as global's |
| ME Pro N150 (2-bay) | N150 | Not found under this exact bay count | YES (id 132) | UNKNOWN | `NO_ADVANTAGE` — global already has it |
| ME Pro Core 3-304 | Intel Core 3-304 | NO | YES (id 114) | UNKNOWN | `NO_ADVANTAGE` — global led here, China's own catalogue doesn't even carry it |
| ME Pro H255 | — | NO | NO | — | `SOURCE_ABSENT` — could not verify this configuration exists at all |
| ME Pro J5005 | — | NO | NO | — | `SOURCE_ABSENT` — legacy config, not retrievable from either live surface |
| ME Pro Ryzen AI 9 HX370 | HX370 | NO | NO (HX370 exists only under the unrelated SER9 Pro line) | UNKNOWN | `SOURCE_ABSENT` — the article's framing of "the previous HX370 variant" could not be matched to a distinct live ME Pro SKU on either surface |
| **ME Pro Ryzen AI 9 HX470 (incident)** | HX470 | **NO** | NO | 2026-08-12 (Weibo, per Notebookcheck) | `SOURCE_ABSENT` |

**PROVEN_CATCH: 0. PROBABLE_CATCH: 0.** No trustworthy timestamp exists
anywhere on either catalogue to support even a probable claim. The only
date-shaped value found (a Unix-epoch suffix in CDN image filenames, e.g.
`...1738909512.jpg`) is a CDN upload/edit time, not a launch time, and is
explicitly excluded per Phase 4's instruction not to treat modification
time as launch time.

## Timing evidence

What **can** be shown: the two catalogues (China `cid=84` and global
Shopify) hold materially different SKU sets for the same product family —
China carries N95/N200 configs and multiple bay-count variants global
lacks; global carries the Core 3-304 config China's own ME-series listing
lacks. This is genuine two-way regional divergence, not a simple
"China-first" lag pattern.

What **cannot** be shown: any case where China's structured catalogue
carried a configuration measurably earlier than the global store, because
no timestamp exists on either side to measure with. The HX 470 incident
itself is currently absent from *both* structured catalogues, so it cannot
serve as a proof case either — it only proves Weibo currently leads both.

## Recommended source contract

**Collection strategy: B — BASELINE → DELTA** (Phase 6). No trustworthy
timestamp exists, but product/SKU enumeration via `cid` is stable and
deterministic. Silent baseline on first pass; later additions (new `spu`-level
product id, or a new configuration id under a known product) become
review-only candidates. Not a timestamped feed (A), not primarily a
configuration-diff-on-existing-page model (C) — the catalogue API already
returns full structured configuration data per pull, so there is no
separate "page" to diff.

Identity: product-level `id` (spu-level numeric id) for `NEW_CHINA_PRODUCT`,
configuration-level `id` (per-SKU numeric id, distinct namespace) for
`NEW_CHINA_CONFIGURATION`. Neither the Chinese free-text title/spu string
nor the URL is used as identity — both were observed to be inconsistent
(e.g. `"...-clone-1"` suffixes on some entries).

Scope: **ME series only (`cid=84`)** — the family implicated in the
incident. Other series share the same API shape and are candidates for a
future, separately-scoped pass; this PoC does not generalize to them.

## Experimental implementation

**MODULE:** [`src/oem_radar/experimental/beelink_china_delta.py`](../src/oem_radar/experimental/beelink_china_delta.py) —
`BeelinkChinaDeltaCollector` + `ExperimentalBeelinkChinaStore`, mirroring
the safety shape of `LenovoRegionalSitemapDeltaCollector` (isolated SQLite
file, never imported by `core/runner.py`, never wired into `run_all`, no
SnapshotStore/notifier/health-counter access).

**STATE DB:** isolated SQLite file (caller-supplied path — not
`data/radar.db`). Four tables: `beelink_cn_runs`, `beelink_cn_products`,
`beelink_cn_configurations`, `beelink_cn_candidates`. No table overlaps
with the production schema.

**CANDIDATE TYPES:** `NEW_CHINA_PRODUCT` (new spu-level id), `NEW_CHINA_CONFIGURATION`
(new configuration id under an already-known product). `CHINA_PRODUCT_PAGE_APPEARANCE`
and `CHINA_SUPPORT_MODEL_APPEARANCE` were **not implemented** — nothing in
the discovered source contract justifies them (no support-database source
was used; there is only one surface, so there is no "appeared elsewhere"
corroboration case the way Lenovo's multi-region sitemap has).

Each candidate carries a best-effort `global_source_presence` annotation
(`yes`/`no`/`unknown`, via loose CPU-token matching against a caller-supplied
set) — informational only, never used to merge or suppress identity, per
Phase 9's instruction that regional aliases must not automatically become
global products.

**BASELINE RESULT (live, ME series):** 7 products, 12 configurations
discovered; 0 candidates (silent baseline, as required).

**SECOND PASS RESULT (live, minutes later):** identical 7 products, 0 new
products, 0 new configurations, 0 candidates — stable repeat/dedup
confirmed.

**TEST RESULT:** 13/13 focused tests pass (baseline, repeat pass, new
product, new configuration, global-presence yes/no, no-reemission on
repeat, partial failure, empty failure, malformed identity, missing-SKU
fallback, candidate dedup, isolated-table check). Full offline suite: 542/542
pass.

**CHANGE_EVENTS:** 0 — this module never touches the `change_events` table;
it has no code path that could write to it.
**NOTIFICATIONS:** 0 — same; no notification code path exists in this
module.

## Git

| | |
|---|---|
| HEAD BEFORE | `25805ce` |
| HEAD AFTER | see commit below |
| REMOTE | `codex/bankai-config-availability` (same branch as the Lenovo/ASUS/PSREF experimental work) |
| PUSH | yes, normal push, no force |
| EXE REBUILT | **NOT REQUIRED** — `oem_radar.experimental` is not imported by `launch_dashboard.py`, `cli.py`, or `dashboard/__init__.py`; PyInstaller's import-graph analysis (per `build_dashboard_exe.cmd`, no `--collect-all`/`--hidden-import` for this package) will not bundle it, matching the existing Lenovo/ASUS precedent |

## China-audit lessons (for the future all-OEM China coverage audit — not started now)

1. Don't guess API paths — read the page's own inline `<script>` source for
   the real AJAX/fetch call; client-rendered category pages hide the actual
   data source from a naive HTML fetch.
2. A 200 status on `sitemap.xml` does not mean a usable sitemap — check body
   length, not just status code.
3. Numeric backend ids (both product/spu-level and configuration-level) are
   far more reliable identity than free-text titles on Chinese e-commerce
   sites — titles carry inconsistent suffixes (`-clone-1`) and co-brand
   variants of the same underlying config.
4. Configuration ids and product/spu ids can share the same numeric space
   (a product's first configuration commonly reuses the parent's id) —
   namespace identities by type (`product:` vs `config:`) to avoid
   cross-type collisions.
5. Absence of a timestamp field anywhere is common enough to plan for by
   default — check for it, but design the baseline/delta fallback strategy
   up front rather than assuming a timestamped feed exists.
6. CDN image-filename epochs are tempting but untrustworthy as launch-time
   proxies — they reflect asset upload/edit time, not product launch time.
7. Regional catalogues can diverge in **both directions** — don't assume
   "China leads, global lags" as a universal pattern; verify per case.
   Here, global had a config (Core 3-304) China's own catalogue lacked.
8. An official "news" page existing doesn't mean it's a live announcement
   feed — this one was effectively static since 2021–2022 and was not a
   useful source for this product family.
9. When neither surface has the launch yet, that's a valid finding, not a
   failed investigation — it proves the social source currently leads both
   structured surfaces, which is itself the answer to "would this collector
   have caught it."
10. A structural coverage advantage (catching real SKUs the global source
    will never see) is real editorial value even without a proven speed
    advantage on any single specific incident — don't require proof of
    beating the news cycle before recognizing genuine catalogue-completeness
    value.

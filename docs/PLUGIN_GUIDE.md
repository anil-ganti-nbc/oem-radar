# PLUGIN_GUIDE.md

Two extension paths, in order of how often you'll use them.

## Path 1: Add an OEM (YAML only — the common case)

If the OEM runs Shopify or WooCommerce, you write no code. Create `config/oems/<name>.yaml`:

```yaml
manufacturer:
  name: GMKtec
  aliases: [GMK, "极摩客"]
  country: CN

sources:
  - id: gmktec-shopify
    engine: shopify                # registered engine name
    base_url: https://www.gmktec.com
    min_interval: 6h               # ADR-1: run skips this source if crawled more recently
    discovery: [products_json, sitemap]   # strategies, union of results
    currency_default: USD
    category_map:                  # vendor collection → normalized category
      mini-pcs: mini_pc
      handhelds: handheld
    spec_hints:                    # optional regex/JSON-path nudges for messy fields
      cpu_from_title: true
```

Run `oem-radar validate` — it checks the descriptor against the engine's declared config schema without touching the network. Then `oem-radar run --source gmktec-shopify --dry-run` to see what would be stored/notified. That's the whole procedure; core, DB, notifier, and every other OEM are untouched.

How do you know which platform a store runs? `oem-radar probe <url>` (M2) fetches the homepage once and fingerprints it (Shopify: `/products.json` responds, `cdn.shopify.com` assets; Woo: `wp-json/wc/store` or `woocommerce` body classes).

## Path 2: Add an engine (code — for platforms and oddballs)

An engine implements the `SourceEngine` protocol (`core/interfaces.py`):

```python
from oem_radar.core.interfaces import SourceEngine, Fetcher, ProductRef, FetchedDocument
from oem_radar.core.models import NormalizedProduct, RawProduct, ValidationIssue
from oem_radar.core.registry import engines

@engines.register("topton")
class ToptonEngine:
    config_schema = ToptonConfig          # pydantic model; validates the YAML source block

    def discover(self, fetcher: Fetcher) -> Iterable[ProductRef]: ...
    def parse(self, doc: FetchedDocument) -> RawProduct: ...
    def normalize(self, raw: RawProduct) -> NormalizedProduct: ...
    def validate(self, product: NormalizedProduct) -> list[ValidationIssue]: ...
```

Rules that keep the architecture honest:

- **No I/O except through the injected `Fetcher`.** The fetcher gives you politeness, caching, conditional GETs, and — in tests — canned fixtures for free. An engine that imports `requests` fails review.
- **No database, no Discord, no AI.** Return values only.
- **`normalize` maps into the shared model; put everything else in `raw_data`.** Never invent values: unknown stays `None`, and `confidence` should reflect how much of the listing you actually understood.
- **`validate` reports, it doesn't reject.** Issues lower confidence; the core decides what to do (a listing failing validation because of an unrecognized CPU string is high-value, not garbage — see DIFF_ENGINE.md on known-hardware flags).
- **Discovery strategies are separate registered classes** (`discovery.register("sitemap")`) so engines share them; an engine declares which strategies it supports.

### Engine tests (required per engine)

Fixtures live in `tests/fixtures/<engine>/` as captured real responses (JSON/HTML), goldens in `tests/goldens/<engine>/`. Minimum suite: discovery finds the expected refs from fixture responses; parse+normalize matches stored golden JSON (`assert_goldens` — a change in engine output fails loudly; accept deliberately with `UPDATE_GOLDENS=1 pytest`); validate flags the deliberately broken fixture (`assert_validate_flags`); config schema rejects a malformed block (`assert_config_rejected`). The shared harness in `tests/engine_harness.py` provides all four given routed fixture responses, so a new engine's test file is ~20 lines — see `tests/test_review_now_list.py` for usage.

## Path 3 (rare): new provider

Storage, notification, and AI backends implement `SnapshotStore`, `Notifier`, `Summarizer` respectively, register under a name, and get selected in `radar.yaml` (`notifier: discord`, `store: sqlite`, `summarizer: anthropic`). Same rules: config-schema declared, no cross-imports.

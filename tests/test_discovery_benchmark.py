"""Stage 9 Phase 6: discovery benchmark suite. Runs core.benchmark's
`benchmark_discovery` against one real, already-captured fixture per
engine (the same fixtures each engine's own test file uses — see
tests/fixtures/*/PROVENANCE.md) and asserts the numbers are sane. This is
what makes the suite "repeatable": same fixtures in, same measurements
out, every run, offline.

Regenerating docs/DISCOVERY_BENCHMARKS.md is a deliberate, separate step
(`UPDATE_BENCHMARK_DOC=1 pytest tests/test_discovery_benchmark.py`), not
something that happens silently on every test run.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from oem_radar.core.benchmark import benchmark_discovery
from oem_radar.core.config import SourceConfig
from oem_radar.core.models import FetchedDocument
from oem_radar.engines.category_jsonld import CategoryJsonLdEngine
from oem_radar.engines.dell import DellEngine
from oem_radar.engines.shopify import ShopifyEngine
from oem_radar.engines.sitemap_jsonld import SitemapJsonLdEngine
from oem_radar.engines.woocommerce_store_api import WooCommerceStoreApiEngine

ROOT = Path(__file__).parent
DOC_PATH = ROOT.parent / "docs" / "DISCOVERY_BENCHMARKS.md"


class _FixtureFetcher:
    """Routes URLs to on-disk fixture bodies; anything unrouted 404s
    rather than raising — engines are expected to degrade gracefully on
    a missing page, and the benchmark should measure that behavior, not
    crash on it."""

    def __init__(self, routes: dict[str, str]):
        self.routes = routes
        self.calls: list[str] = []

    def get(self, url: str, **kwargs):
        self.calls.append(url)
        if url in self.routes:
            return FetchedDocument(url=url, status=200, body=self.routes[url])
        return FetchedDocument(url=url, status=404, body="")


def _read(engine: str, name: str) -> str:
    return (ROOT / "fixtures" / engine / name).read_text(encoding="utf-8")


def _bench_category_jsonld():
    base = "https://www.samsung.com"
    url = f"{base}/us/computers/galaxy-book/"
    src = SourceConfig(id="samsung-galaxybook", engine="category_jsonld", base_url=base,
                        category_urls=[url], enabled=True)
    engine = CategoryJsonLdEngine(src, "Samsung")
    fetcher = _FixtureFetcher({url: _read("category_jsonld", "samsung_galaxy_book_category.html")})
    return benchmark_discovery("samsung-galaxybook", "category_jsonld", engine, fetcher)


def _bench_shopify():
    base = "https://www.gmktec.com"
    src = SourceConfig(id="gmktec-shopify", engine="shopify", base_url=base,
                        discovery=["products_json"], currency_default="USD", max_pages=1)
    engine = ShopifyEngine(src, "GMKtec")
    fetcher = _FixtureFetcher({f"{base}/products.json?limit=250&page=1": _read("shopify", "gmktec_products.json")})
    return benchmark_discovery("gmktec-shopify", "shopify", engine, fetcher)


def _bench_woocommerce():
    base = "https://www.geekompc.com"
    src = SourceConfig(id="geekom-wc", engine="woocommerce_store_api", base_url=base, enabled=True)
    engine = WooCommerceStoreApiEngine(src, "GEEKOM")
    per_page = engine.cfg.per_page
    url = f"{base}/wp-json/wc/store/v1/products?per_page={per_page}&page=1"
    return benchmark_discovery("geekom-wc", "woocommerce_store_api", engine, _FixtureFetcher({url: _read("woocommerce", "geekom_products_p1.json")}))


def _bench_dell():
    base = "https://www.dell.com"
    path = "/en-us/shop/dell-laptops/sr/laptops"
    src = SourceConfig(id="dell-us-laptops", engine="dell", base_url=base,
                        category_paths=[path], region="us")
    engine = DellEngine(src, "Dell")
    return benchmark_discovery("dell-us-laptops", "dell", engine,
                                _FixtureFetcher({base + path: _read("dell", "dell_laptops_listing.html")}))


def _bench_sitemap_jsonld():
    base = "https://www.khadas.com"
    sitemap_url = "https://www.khadas.com/store-products-sitemap.xml"
    src = SourceConfig(id="khadas-sitemap", engine="sitemap_jsonld", base_url=base,
                        sitemap_url=sitemap_url)
    engine = SitemapJsonLdEngine(src, "Khadas")
    fetcher = _FixtureFetcher({
        sitemap_url: _read("sitemap_jsonld", "khadas_product_sitemap.xml"),
        f"{base}/product-page/vim3": _read("sitemap_jsonld", "khadas_product_vim3.html"),
        f"{base}/product-page/usb-c-24w-adapter": _read("sitemap_jsonld", "khadas_product_adapter.html"),
    })
    # The real sitemap lists ~78 URLs; this project only captured fixtures
    # for two of them (a real product and a real accessory). Sampling the
    # full discovery order — not just the first few — guarantees both
    # captured URLs land in the sample, at the honest cost of most other
    # sampled refs reporting "no fixture captured" rather than a real
    # validate() result.
    return benchmark_discovery("khadas-sitemap", "sitemap_jsonld", engine, fetcher, normalize_sample=200)


_BENCHMARKS = {
    "category_jsonld (Samsung)": _bench_category_jsonld,
    "shopify (GMKtec)": _bench_shopify,
    "woocommerce_store_api (GEEKOM)": _bench_woocommerce,
    "dell (Dell)": _bench_dell,
    "sitemap_jsonld (Khadas)": _bench_sitemap_jsonld,
}


def test_all_engine_benchmarks_find_real_products():
    for label, fn in _BENCHMARKS.items():
        result = fn()
        assert result.products_found > 0, f"{label}: discovery found nothing on a known-good fixture"
        assert result.time_seconds >= 0
        assert result.requests_made >= 1
        assert 0.0 <= result.identity_quality <= 1.0


def test_bulk_inline_engines_make_exactly_one_discovery_request():
    for label, fn in (("category_jsonld", _bench_category_jsonld), ("shopify", _bench_shopify),
                       ("woocommerce_store_api", _bench_woocommerce), ("dell", _bench_dell)):
        result = fn()
        assert result.requests_made == 1, f"{label} is bulk-inline; discovery should be a single request, got {result.requests_made}"


def test_sitemap_engine_discovery_is_cheap_relative_to_full_catalog():
    result = _bench_sitemap_jsonld()
    # discover() only fetches the sitemap itself; per-page fetches happen
    # later in the pipeline, not during discovery.
    assert result.requests_made == 1
    assert result.products_found > 1


def test_samsung_fixture_has_no_duplicate_refs():
    result = _bench_category_jsonld()
    assert result.duplicate_refs == 0


def test_benchmark_doc_regeneration_is_opt_in():
    if os.environ.get("UPDATE_BENCHMARK_DOC") != "1":
        return
    lines = [
        "# Discovery Benchmarks",
        "",
        "**Generated by `tests/test_discovery_benchmark.py` "
        "(`UPDATE_BENCHMARK_DOC=1 pytest tests/test_discovery_benchmark.py`), Stage 9.** "
        "One real fixture per engine, same fixtures each engine's own test suite uses. "
        "Every number is measured by actually running `discover()`/`normalize()`/`validate()` "
        "against real captured data — nothing here is estimated.",
        "",
        "| Source | Engine | Time (s) | Requests | Products found | Duplicate refs | "
        "Identity quality | Validation pass rate | Sample size | Notes |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for label, fn in _BENCHMARKS.items():
        r = fn()
        if len(r.notes) > 3:
            notes = f"{len(r.notes)} notes (mostly 'no fixture captured' — see test source for the full list)"
        else:
            notes = "; ".join(r.notes) if r.notes else "-"
        lines.append(
            f"| {r.source_id} | {r.engine} | {r.time_seconds} | {r.requests_made} | "
            f"{r.products_found} | {r.duplicate_refs} | {r.identity_quality} | "
            f"{r.validation_pass_rate} | {r.normalized_sample_size} | {notes} |"
        )
    lines.append("")
    lines.append(
        "Identity quality = fraction of discovered refs carrying a non-empty stable "
        "handle. Validation pass rate = fraction of the normalized sample with zero "
        "fatal `validate()` issues (a proxy for category/discovery quality — a ref "
        "that fails validation is exactly the kind of false positive discovery should "
        "avoid). Re-run any time fixtures or engine logic change; the numbers should "
        "only move when the underlying code or fixture actually changed."
    )
    DOC_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

"""Stage 7 Phase 1: the three carried-over "easy wins" from Stage 5/6 recon.

- Star Labs: real Shopify catalog, needed a bigger spare-parts denylist
  (config only, no code change) — see config/oems/starlabs.yaml.
- Medion: real sitemap_jsonld candidate, needed url_include_pattern scoping
  to stay PC-only and keep the crawl size reasonable.
- LG: real sitemap_jsonld candidate, needed a pricing-enabled region (US
  consumer site instead of the India business site tried in Stage 6) and
  url_include_pattern scoping to the real gram-laptop product pages.

Real fixtures throughout — see tests/fixtures/shopify/PROVENANCE.md and
tests/fixtures/sitemap_jsonld/PROVENANCE.md.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from oem_radar.core.config import ManufacturerConfig, OemConfig, RadarConfig, SourceConfig, load_oem_configs
from oem_radar.core.models import FetchedDocument, RawProduct
from oem_radar.core.runner import run_all
from oem_radar.engines import shopify  # noqa: F401
from oem_radar.engines.shopify import ShopifyEngine
from oem_radar.engines.sitemap_jsonld import SitemapJsonLdEngine
from oem_radar.providers.discord import DiscordNotifier
from oem_radar.providers.sqlite import SqliteStore

SHOPIFY_FIXTURES = Path(__file__).parent / "fixtures" / "shopify"
SJ_FIXTURES = Path(__file__).parent / "fixtures" / "sitemap_jsonld"


def _read_sj(name: str) -> str:
    return (SJ_FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture()
def store(tmp_path):
    s = SqliteStore(str(tmp_path / "s.db"), str(tmp_path / "raw"))
    yield s
    s.close()


# ============================================================================
# Star Labs (shopify, denylist expansion)
# ============================================================================

def _starlabs_engine():
    oems = load_oem_configs(Path("config/oems"))
    src = next(s for s in oems["Star Labs"].sources if s.id == "starlabs-shopify")
    return ShopifyEngine(src, "Star Labs"), src


def test_starlabs_config_loads_enabled():
    oems = load_oem_configs(Path("config/oems"))
    assert "Star Labs" in oems
    src = next(s for s in oems["Star Labs"].sources if s.id == "starlabs-shopify")
    assert src.enabled is True
    assert src.engine == "shopify"


def test_starlabs_denylist_filters_spare_parts_and_keeps_real_laptops():
    eng, _ = _starlabs_engine()
    data = json.loads((SHOPIFY_FIXTURES / "starlabs_products_p1.json").read_text(encoding="utf-8"))
    assert len(data["products"]) == 111

    kept = []
    for p in data["products"]:
        product = eng.normalize(RawProduct(
            source_id="starlabs-shopify", url=f"https://starlabs.systems/products/{p['handle']}",
            payload=p))
        if not product.raw_data.get("non_product"):
            kept.append(product)
    assert len(kept) == 19
    models = {p.model for p in kept}
    assert "StarBook Horizon Plus" in models
    assert "StarFighter AMD" in models
    assert "Privacy StarLite" in models
    # spare parts and accessories must not leak through
    leaked = {p.model for p in kept if any(
        term in (p.model or "").lower()
        for term in ("mainboard", "battery", "display -", "license", "keyboard", "recovery"))}
    assert leaked == set()


def test_starlabs_baseline_run_is_quiet(store):
    eng, src = _starlabs_engine()
    data_path = SHOPIFY_FIXTURES / "starlabs_products_p1.json"

    class F:
        def get(self, url, **k):
            if "products.json" in url:
                return FetchedDocument(url=url, status=200,
                                       body=data_path.read_bytes().decode("utf-8"),
                                       content_type="application/json")
            return FetchedDocument(url=url, status=404, body="{}")

    radar = RadarConfig(baseline_quiet=True)
    oems = {"Star Labs": OemConfig(
        manufacturer=ManufacturerConfig(name="Star Labs", country="GB"), sources=[src])}
    notifier = DiscordNotifier(store, "https://hook.example", 1,
                               sender=lambda u, p: (True, None))
    run_all(radar, oems, store, notifier, F(), force=True)
    pending = store.db.execute(
        "SELECT COUNT(*) c FROM notifications WHERE status='pending'").fetchone()["c"]
    assert pending == 0


# ============================================================================
# Medion (sitemap_jsonld, url_include_pattern scoping)
# ============================================================================

def _medion_engine():
    oems = load_oem_configs(Path("config/oems"))
    src = next(s for s in oems["Medion"].sources if s.id == "medion-gaming-sitemap")
    return SitemapJsonLdEngine(src, "Medion"), src


def test_medion_config_loads_enabled_and_scoped():
    _, src = _medion_engine()
    assert src.enabled is True
    assert src.engine == "sitemap_jsonld"
    assert "high-end-gaming-notebooks" in src.model_dump()["url_include_pattern"]


def test_medion_url_include_pattern_scopes_mixed_catalog_to_gaming_pcs():
    eng, _ = _medion_engine()

    class F:
        def get(self, url, **k):
            return FetchedDocument(url=url, status=200, body=_read_sj("medion_product_sitemap.xml"))

    refs = list(eng.discover(F()))
    # The real sitemap has 6,265 URLs across Medion's entire consumer-
    # electronics catalog; scoped down to the gaming PC/notebook lines only.
    assert 0 < len(refs) <= 700
    assert all("gaming" in r.url for r in refs)
    assert all("kuehlschraenke" not in r.url and "haushalt" not in r.url for r in refs)


def test_medion_real_gaming_notebook_has_price_and_mpn():
    eng, _ = _medion_engine()
    doc = FetchedDocument(url="https://www.medion.com/de/shop/p/high-end-gaming-notebooks-medion-x",
                          status=200, body=_read_sj("medion_product_erazer_x17805.html"))
    product = eng.normalize(eng.parse(doc))
    assert product.model
    assert product.vendor_sku  # mpn present
    assert len(product.prices) == 1
    assert product.prices[0].currency == "EUR"
    assert product.prices[0].amount == 1649.95


def test_medion_max_products_safety_valve_applied():
    _, src = _medion_engine()
    assert src.model_dump()["max_products"] == 700


def test_medion_min_interval_reduced_to_72h_after_cloud_soak_evidence():
    """2026-08-09 Hetzner soak evidence: a real forced re-crawl found 0/692
    changed products and cost 68m34s (57% of a 119m26s full-fleet cycle).
    Category scoping (url_include_pattern above) and model-family
    deduplication were both investigated; scoping is already correct and
    dedup was rejected (same-model URLs carry genuinely different CPU/GPU
    configs -- exactly the signal this engine exists to catch). min_interval
    is the one safe, completeness-preserving lever -- see medion.yaml."""
    _, src = _medion_engine()
    assert src.min_interval_s == 72 * 3600


# ============================================================================
# LG (sitemap_jsonld, pricing-enabled region + url_include_pattern)
# ============================================================================

def _lg_engine():
    oems = load_oem_configs(Path("config/oems"))
    src = next(s for s in oems["LG"].sources if s.id == "lg-us-gram-sitemap")
    return SitemapJsonLdEngine(src, "LG"), src


def test_lg_config_loads_enabled_and_scoped():
    _, src = _lg_engine()
    assert src.enabled is True
    assert src.engine == "sitemap_jsonld"
    assert "gram-laptop" in src.model_dump()["url_include_pattern"]


def test_lg_url_include_pattern_scopes_full_us_sitemap_to_gram_laptops():
    eng, _ = _lg_engine()

    class F:
        def get(self, url, **k):
            return FetchedDocument(url=url, status=200, body=_read_sj("lg_us_sitemap.xml"))

    refs = list(eng.discover(F()))
    # The real US sitemap has 6,220 URLs (TVs, appliances, phones, laptops);
    # scoped to the 182 real gram-laptop product pages.
    assert len(refs) == 182
    assert all(r.url.endswith("-gram-laptop") for r in refs)


def test_lg_real_product_has_price_but_identity_comes_from_url_slug():
    """LG's US consumer site has real pricing but no sku/mpn field in
    JSON-LD (unlike the India business site checked in Stage 6, which had
    mpn but no price) — identity has to fall back to the URL slug, which
    embeds LG's own model code."""
    eng, _ = _lg_engine()
    url = "https://www.lg.com/us/laptops/lg-14t90q-k.aab6u1-gram-laptop"
    doc = FetchedDocument(url=url, status=200, body=_read_sj("lg_product_14t90q.html"))
    product = eng.normalize(eng.parse(doc))
    assert product.model
    assert product.vendor_sku is None
    assert len(product.prices) == 1
    assert product.prices[0].currency == "USD"
    assert product.prices[0].amount == 1299.99
    assert eng._slug(url) == "lg-14t90q-k.aab6u1-gram-laptop"


def test_lg_baseline_run_is_quiet_with_real_fixtures(store):
    eng, src = _lg_engine()

    class F:
        def get(self, url, **k):
            if url == src.model_dump()["sitemap_url"]:
                return FetchedDocument(url=url, status=200, body=_read_sj("lg_us_sitemap.xml"))
            if url == "https://www.lg.com/us/laptops/lg-14t90q-k.aab6u1-gram-laptop":
                return FetchedDocument(url=url, status=200, body=_read_sj("lg_product_14t90q.html"))
            return FetchedDocument(url=url, status=404, body="")

    # Narrow discovery to just the one fixture-backed product for a fast,
    # deterministic run (the real sitemap scopes to 182 URLs).
    class NarrowEngine(SitemapJsonLdEngine):
        def discover(self, fetcher):
            return [r for r in super().discover(fetcher)
                    if r.url == "https://www.lg.com/us/laptops/lg-14t90q-k.aab6u1-gram-laptop"]

    radar = RadarConfig(baseline_quiet=True)
    narrow = NarrowEngine(src, "LG")
    oems = {"LG": OemConfig(manufacturer=ManufacturerConfig(name="LG", country="KR"), sources=[src])}
    # run_all constructs the engine from the registry, so exercise the
    # pipeline directly against the narrowed engine instead.
    from oem_radar.core.pipeline import run_source
    stats = run_source(src, narrow, F(), store, DiscordNotifier(
        store, "https://hook.example", 1, sender=lambda u, p: (True, None)), baseline=True)
    assert stats.snapshots_written == 1
    pending = store.db.execute(
        "SELECT COUNT(*) c FROM notifications WHERE status='pending'").fetchone()["c"]
    assert pending == 0

"""Stage 7 Phase 2: the woocommerce_store_api engine. Built after 3
independently confirmed real OEMs (GEEKOM, NovaCustom, Pine64) cleared the
same "≥3 confirmed real candidates" bar as sitemap_jsonld did in Stage 6 —
see docs/STAGE7.md. Real fixtures for the happy paths; hand-written
malformed inputs only for parser-robustness checks (same convention as
tests/test_sitemap_jsonld_engine.py — never presented as real vendor data).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from oem_radar.core.config import CollectorHealthConfig, SourceConfig, load_oem_configs
from oem_radar.core.models import FetchedDocument, RawProduct
from oem_radar.core.pipeline import run_source
from oem_radar.core.runner import run_all
from oem_radar.engines.woocommerce_store_api import WooCommerceStoreApiEngine
from oem_radar.providers.discord import ConsoleNotifier, DiscordNotifier
from oem_radar.providers.sqlite import SqliteStore

FIXTURES = Path(__file__).parent / "fixtures" / "woocommerce"


def _read_json(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _src(id_, base, **extra) -> SourceConfig:
    return SourceConfig(id=id_, engine="woocommerce_store_api", base_url=base,
                        enabled=True, **extra)


@pytest.fixture()
def store(tmp_path):
    s = SqliteStore(str(tmp_path / "s.db"), str(tmp_path / "raw"))
    yield s
    s.close()


class _PageFetcher:
    """Serves per-page Store API responses from a list of pages; empty list
    (or a missing page) yields an empty JSON array (end of pagination)."""

    def __init__(self, pages: dict[int, list], base="https://ex.com"):
        self.pages = pages
        self.base = base
        self.calls: list[str] = []

    def get(self, url: str, **kwargs):
        self.calls.append(url)
        import re
        m = re.search(r"[?&]page=(\d+)", url)  # not per_page=
        page = int(m.group(1)) if m else 1
        body = json.dumps(self.pages.get(page, []))
        return FetchedDocument(url=url, status=200, body=body, content_type="application/json")


# ============================================================================
# discovery / pagination
# ============================================================================

def test_discovery_single_page_real_geekom():
    eng = WooCommerceStoreApiEngine(_src("geekom-wc", "https://www.geekompc.com"), "GEEKOM")
    products = _read_json("geekom_products_p1.json")
    fetcher = _PageFetcher({1: products})
    refs = list(eng.discover(fetcher))
    assert len(refs) == 77
    assert all(r.inline_payload is not None for r in refs)  # bulk-inline, no per-page fetch


def test_discovery_paginates_real_novacustom_two_pages():
    eng = WooCommerceStoreApiEngine(_src("novacustom-wc", "https://novacustom.com"), "NovaCustom")
    p1 = _read_json("novacustom_products_p1.json")
    p2 = _read_json("novacustom_products_p2.json")
    fetcher = _PageFetcher({1: p1, 2: p2})
    refs = list(eng.discover(fetcher))
    assert len(refs) == 200  # 100 + 100, and a 3rd page would have been fetched if non-empty
    # confirms it actually paginated (page 2 requested) rather than stopping at page 1
    assert any("page=2" in c for c in fetcher.calls)
    assert any("page=3" in c for c in fetcher.calls)  # tries page 3, gets empty, stops


def test_discovery_stops_on_short_page_without_extra_request():
    eng = WooCommerceStoreApiEngine(_src("ex", "https://ex.com", per_page=100), "Ex")
    short_page = [{"id": i, "name": f"P{i}", "slug": f"p{i}"} for i in range(5)]
    fetcher = _PageFetcher({1: short_page})
    refs = list(eng.discover(fetcher))
    assert len(refs) == 5
    assert not any("page=2" in c for c in fetcher.calls)


def test_discovery_malformed_json_page_does_not_crash():
    class BadFetcher:
        def get(self, url, **k):
            return FetchedDocument(url=url, status=200, body="{not valid json")
    eng = WooCommerceStoreApiEngine(_src("ex", "https://ex.com"), "Ex")
    assert list(eng.discover(BadFetcher())) == []


def test_discovery_http_error_on_first_page_does_not_crash():
    class ErrorFetcher:
        def get(self, url, **k):
            raise ConnectionError("simulated failure")
    eng = WooCommerceStoreApiEngine(_src("ex", "https://ex.com"), "Ex")
    assert list(eng.discover(ErrorFetcher())) == []


def test_discovery_zero_products():
    eng = WooCommerceStoreApiEngine(_src("ex", "https://ex.com"), "Ex")
    fetcher = _PageFetcher({1: []})
    assert list(eng.discover(fetcher)) == []


def test_discovery_max_pages_safety_valve():
    eng = WooCommerceStoreApiEngine(_src("ex", "https://ex.com", per_page=10, max_pages=2), "Ex")
    full_page = [{"id": i, "name": f"P{i}", "slug": f"p{i}"} for i in range(10)]
    fetcher = _PageFetcher({1: full_page, 2: full_page, 3: full_page})
    refs = list(eng.discover(fetcher))
    assert len(refs) == 20  # stopped after 2 pages despite page 3 having data too
    assert not any("page=3" in c for c in fetcher.calls)


# ============================================================================
# normalize: real fixtures, pricing, identity, categories, stock
# ============================================================================

def test_geekom_zero_minor_unit_pricing():
    """Regression: GEEKOM's currency_minor_unit is 0 (whole dollars), unlike
    NovaCustom/Pine64's 2 (cents) — dividing by a hardcoded 100 would
    silently misprice this vendor by 100x."""
    eng = WooCommerceStoreApiEngine(_src("geekom-wc", "https://www.geekompc.com"), "GEEKOM")
    products = _read_json("geekom_products_p1.json")
    p = next(x for x in products if x.get("prices", {}).get("currency_minor_unit") == 0)
    product = eng.normalize(RawProduct(source_id="geekom-wc", url=p["permalink"], payload=p))
    expected = float(p["prices"]["price"])
    assert product.prices[0].amount == expected  # not expected/100


def test_novacustom_two_cent_minor_unit_pricing():
    eng = WooCommerceStoreApiEngine(_src("novacustom-wc", "https://novacustom.com"), "NovaCustom")
    products = _read_json("novacustom_products_p1.json")
    p = next(x for x in products if x.get("sku") == "KEYBOARD-KBC-2818")
    product = eng.normalize(RawProduct(source_id="novacustom-wc", url=p["permalink"], payload=p))
    assert product.prices[0].amount == 29.0  # "2900" / 10^2
    assert product.prices[0].currency == "EUR"


def test_geekom_variable_product_type_recorded():
    eng = WooCommerceStoreApiEngine(_src("geekom-wc", "https://www.geekompc.com"), "GEEKOM")
    products = _read_json("geekom_products_p1.json")
    p = next(x for x in products if x.get("type") == "variable")
    product = eng.normalize(RawProduct(source_id="geekom-wc", url=p["permalink"], payload=p))
    assert product.raw_data["wc_type"] == "variable"
    assert product.model
    assert product.prices  # base/cheapest-variant price still usable


def test_stable_identity_from_wc_id_and_sku():
    eng = WooCommerceStoreApiEngine(_src("novacustom-wc", "https://novacustom.com"), "NovaCustom")
    products = _read_json("novacustom_products_p1.json")
    p = products[0]
    product = eng.normalize(RawProduct(source_id="novacustom-wc", url=p["permalink"], payload=p))
    assert str(p["id"]) in product.aliases
    if p.get("sku"):
        assert p["sku"] in product.aliases


def test_out_of_stock_maps_to_sold_out():
    eng = WooCommerceStoreApiEngine(_src("novacustom-wc", "https://novacustom.com"), "NovaCustom")
    products = _read_json("novacustom_products_p1.json")
    p = next(x for x in products if x.get("is_in_stock") is False
             and float(x.get("prices", {}).get("price") or 0) > 0)
    product = eng.normalize(RawProduct(source_id="novacustom-wc", url=p["permalink"], payload=p))
    from oem_radar.core.models import Availability
    assert product.prices[0].availability == Availability.SOLD_OUT


def test_categories_recorded_in_raw_data():
    eng = WooCommerceStoreApiEngine(_src("pine64-wc", "https://pine64.com"), "Pine64")
    products = _read_json("pine64_products_p1.json")
    p = next(x for x in products if x.get("categories"))
    product = eng.normalize(RawProduct(source_id="pine64-wc", url=p["permalink"], payload=p))
    assert product.raw_data["categories"]


# ============================================================================
# category_include / category_exclude / non_product_terms scoping
# ============================================================================

def test_pine64_scoped_to_real_laptops_only():
    src = _src("pine64-wc", "https://pine64.com",
              category_include=["laptop", "pinebook pro"],
              category_exclude=["accessor", "spare part"])
    eng = WooCommerceStoreApiEngine(src, "Pine64")
    products = _read_json("pine64_products_p1.json")
    kept = [p for p in products
            if not eng.normalize(RawProduct(source_id="x", url=p["permalink"], payload=p))
            .raw_data["non_product"]]
    assert len(kept) == 2
    assert all("PINEBOOK" in p["name"] for p in kept)


def test_pine64_real_laptop_with_keyboard_in_title_not_filtered():
    """The exact false positive found this stage: a real laptop's title
    contains the word 'Keyboard' (regional layout), which must not trigger
    an accessory-denylist match."""
    src = _src("pine64-wc", "https://pine64.com")  # no extra non_product_terms
    eng = WooCommerceStoreApiEngine(src, "Pine64")
    products = _read_json("pine64_products_p1.json")
    p = next(x for x in products if "Keyboard" in x["name"] and "PINEBOOK" in x["name"])
    product = eng.normalize(RawProduct(source_id="x", url=p["permalink"], payload=p))
    assert product.raw_data["non_product"] is False


def test_novacustom_scoped_to_real_current_products():
    src = _src("novacustom-wc", "https://novacustom.com",
              category_include=["laptop", "mini pc"],
              category_exclude=["bag", "spare part", "accessor", "old model",
                                "refurbished", "wifi card", "storage drive", "charger"],
              non_product_terms=["refurbished", "second hand", "returned", "keyboard"])
    eng = WooCommerceStoreApiEngine(src, "NovaCustom")
    p1 = _read_json("novacustom_products_p1.json")
    p2 = _read_json("novacustom_products_p2.json")
    kept = [p for p in p1 + p2
            if not eng.normalize(RawProduct(source_id="x", url=p["permalink"], payload=p))
            .raw_data["non_product"]]
    assert len(kept) == 6
    assert all("REFURBISHED" not in p["name"].upper() for p in kept)
    assert all("SECOND HAND" not in p["name"].upper() for p in kept)


# ============================================================================
# malformed / missing-field robustness (hand-written, parser-only)
# ============================================================================

def test_missing_prices_object():
    eng = WooCommerceStoreApiEngine(_src("ex", "https://ex.com"), "Ex")
    p = {"id": 1, "name": "NoPrice", "slug": "no-price", "permalink": "https://ex.com/np"}
    product = eng.normalize(RawProduct(source_id="ex", url=p["permalink"], payload=p))
    assert product.prices == []
    issues = eng.validate(product)
    assert any(i.field == "prices" and not i.fatal for i in issues)


def test_missing_sku():
    eng = WooCommerceStoreApiEngine(_src("ex", "https://ex.com"), "Ex")
    p = {"id": 2, "name": "NoSku", "slug": "no-sku", "permalink": "https://ex.com/ns",
         "prices": {"price": "100", "currency_code": "USD", "currency_minor_unit": 2}}
    product = eng.normalize(RawProduct(source_id="ex", url=p["permalink"], payload=p))
    assert product.vendor_sku is None
    issues = eng.validate(product)
    assert any(i.field == "vendor_sku" and not i.fatal for i in issues)


def test_missing_name_is_fatal():
    eng = WooCommerceStoreApiEngine(_src("ex", "https://ex.com"), "Ex")
    p = {"id": 3, "slug": "no-name", "permalink": "https://ex.com/nn"}
    product = eng.normalize(RawProduct(source_id="ex", url=p["permalink"], payload=p))
    issues = eng.validate(product)
    assert any(i.fatal for i in issues)


def test_malformed_prices_price_string():
    eng = WooCommerceStoreApiEngine(_src("ex", "https://ex.com"), "Ex")
    p = {"id": 4, "name": "Bad", "slug": "bad", "permalink": "https://ex.com/bad",
         "prices": {"price": "not-a-number", "currency_code": "USD", "currency_minor_unit": 2}}
    product = eng.normalize(RawProduct(source_id="ex", url=p["permalink"], payload=p))
    assert product.prices == []  # degrades gracefully, doesn't crash


def test_zero_price_dropped_as_placeholder():
    eng = WooCommerceStoreApiEngine(_src("ex", "https://ex.com"), "Ex")
    p = {"id": 5, "name": "Quote", "slug": "quote", "permalink": "https://ex.com/q",
         "prices": {"price": "0", "currency_code": "USD", "currency_minor_unit": 2}}
    product = eng.normalize(RawProduct(source_id="ex", url=p["permalink"], payload=p))
    assert product.prices == []


def test_image_extraction_from_src_field():
    eng = WooCommerceStoreApiEngine(_src("ex", "https://ex.com"), "Ex")
    p = {"id": 6, "name": "Img", "slug": "img", "permalink": "https://ex.com/img",
         "images": [{"src": "https://ex.com/a.jpg"}, {"no_src": True}]}
    product = eng.normalize(RawProduct(source_id="ex", url=p["permalink"], payload=p))
    assert product.images == ["https://ex.com/a.jpg"]


# ============================================================================
# HTTP failures / health / evidence — through the real pipeline
# ============================================================================

def test_zero_catalog_marks_health_failed(store):
    eng = WooCommerceStoreApiEngine(_src("ex", "https://ex.com"), "Ex")
    src = _src("ex", "https://ex.com")
    store.db.execute(
        "INSERT INTO crawler_runs(source_key, started_at, finished_at, status, stats_json) "
        "VALUES (?,?,?,?,?)",
        ("ex", "2026-01-01", "2026-01-01", "ok", json.dumps({"discovered": 10})),
    )
    store.db.commit()
    stats = run_source(src, eng, _PageFetcher({1: []}), store, ConsoleNotifier(),
                       health_cfg=CollectorHealthConfig())
    assert stats.health == "failed"
    assert stats.health_reason == "UNEXPECTED_ZERO"


def test_source_isolation_one_broken_product_does_not_abort_source(store):
    class BrokenNormalizeEngine(WooCommerceStoreApiEngine):
        def normalize(self, raw):
            if raw.payload.get("id") == 999:
                raise RuntimeError("simulated normalize failure")
            return super().normalize(raw)

    src = _src("ex", "https://ex.com")
    eng = BrokenNormalizeEngine(src, "Ex")
    products = [
        {"id": 999, "name": "Broken", "slug": "broken", "permalink": "https://ex.com/broken"},
        {"id": 1000, "name": "Fine", "slug": "fine", "permalink": "https://ex.com/fine",
         "prices": {"price": "100", "currency_code": "USD", "currency_minor_unit": 2}},
    ]
    stats = run_source(src, eng, _PageFetcher({1: products}), store, ConsoleNotifier(),
                       health_cfg=CollectorHealthConfig())
    assert stats.snapshots_written == 1
    assert len(stats.errors) == 1


def test_source_url_evidence_present():
    eng = WooCommerceStoreApiEngine(_src("geekom-wc", "https://www.geekompc.com"), "GEEKOM")
    products = _read_json("geekom_products_p1.json")
    p = products[0]
    product = eng.normalize(RawProduct(source_id="geekom-wc", url=p["permalink"], payload=p))
    assert product.source_url == p["permalink"]
    assert product.raw_data.get("wc_id") == p["id"]


def test_baseline_run_is_quiet(store):
    from oem_radar.core.config import ManufacturerConfig, OemConfig, RadarConfig
    src = _src("geekom-wc", "https://www.geekompc.com")
    products = _read_json("geekom_products_p1.json")
    radar = RadarConfig(baseline_quiet=True)
    oems = {"GEEKOM": OemConfig(manufacturer=ManufacturerConfig(name="GEEKOM", country="TW"),
                                sources=[src])}
    notifier = DiscordNotifier(store, "https://hook.example", 1, sender=lambda u, p: (True, None))
    run_all(radar, oems, store, notifier, _PageFetcher({1: products}), force=True)
    pending = store.db.execute(
        "SELECT COUNT(*) c FROM notifications WHERE status='pending'").fetchone()["c"]
    assert pending == 0


# ============================================================================
# config wiring
# ============================================================================

def test_geekom_novacustom_pine64_load_enabled():
    oems = load_oem_configs(Path("config/oems"))
    for name, src_id in [("GEEKOM", "geekom-wc"), ("NovaCustom", "novacustom-wc"),
                         ("Pine64", "pine64-wc")]:
        assert name in oems
        src = next(s for s in oems[name].sources if s.id == src_id)
        assert src.enabled is True
        assert src.engine == "woocommerce_store_api"

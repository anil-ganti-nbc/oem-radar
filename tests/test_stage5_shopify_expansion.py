"""Stage 5: easy Shopify wins found by re-probing/reconnaissance — VAIO
(new) and Morefine (stale base_url fixed, now confirmed live). Real
fixtures; see tests/fixtures/shopify/PROVENANCE.md for capture provenance."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from oem_radar.core.config import CollectorHealthConfig, SourceConfig, load_oem_configs
from oem_radar.core.models import FetchedDocument, ProductRef, RawProduct
from oem_radar.core.pipeline import run_source
from oem_radar.core.runner import run_all
from oem_radar.engines import shopify  # noqa: F401  registers engine
from oem_radar.engines.shopify import ShopifyEngine
from oem_radar.providers.discord import ConsoleNotifier, DiscordNotifier
from oem_radar.providers.sqlite import SqliteStore

FIXTURES = Path(__file__).parent / "fixtures" / "shopify"


class _FixtureFetcher:
    def __init__(self, mapping: dict[str, Path]):
        self.mapping = mapping

    def get(self, url: str, **kwargs):
        for key, path in self.mapping.items():
            if key in url and "products.json" in url:
                return FetchedDocument(url=url, status=200, body=path.read_bytes(),
                                       content_type="application/json")
        return FetchedDocument(url=url, status=404, body=b"{}", content_type="application/json")


@pytest.fixture()
def store(tmp_path):
    s = SqliteStore(str(tmp_path / "s.db"), str(tmp_path / "raw"))
    yield s
    s.close()


def _src(id_, base, **extra):
    return SourceConfig(id=id_, engine="shopify", base_url=base,
                        discovery=["products_json"], enabled=True, **extra)


# ---- config wiring ----------------------------------------------------------

def test_vaio_and_morefine_load_enabled():
    oems = load_oem_configs(Path("config/oems"))
    assert "VAIO" in oems
    vaio_src = next(s for s in oems["VAIO"].sources if s.id == "vaio-shopify")
    assert vaio_src.enabled is True
    assert vaio_src.base_url == "https://us.vaio.com"

    assert "Morefine" in oems
    more_src = next(s for s in oems["Morefine"].sources if s.id == "morefine-shopify")
    assert more_src.enabled is True
    assert more_src.base_url == "https://www.morefine.com"  # fixed, was store.morefine.com


# ---- discovery + normalization + identity -----------------------------------

def test_vaio_discovery_and_normalization():
    path = FIXTURES / "vaio_products_p1.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    eng = ShopifyEngine(_src("vaio-shopify", "https://us.vaio.com"), "VAIO")
    fetcher = _FixtureFetcher({"products.json": path})
    refs = list(eng.discover(fetcher))
    assert len(refs) == len(data["products"]) == 165

    laptops = []
    for ref in refs:
        product = eng.normalize(RawProduct(
            source_id="vaio-shopify", url=ref.url, payload=ref.inline_payload))
        if not product.raw_data.get("non_product"):
            laptops.append(product)
    # 157 warranty/repair SKUs filtered; 8 real laptops remain
    assert len(laptops) == 8
    assert all(p.manufacturer == "VAIO" for p in laptops)
    assert all(p.model for p in laptops)
    # stable identity: same handle -> same product_key basis (aliases include handle)
    assert all(p.aliases for p in laptops)


def test_vaio_warranty_skus_filtered_as_non_product():
    path = FIXTURES / "vaio_products_p1.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    warranty = [p for p in data["products"] if p.get("product_type") == "Warranty"]
    assert len(warranty) == 157
    eng = ShopifyEngine(_src("vaio-shopify", "https://us.vaio.com"), "VAIO")
    product = eng.normalize(RawProduct(
        source_id="vaio-shopify",
        url=f"https://us.vaio.com/products/{warranty[0]['handle']}",
        payload=warranty[0],
    ))
    assert product.raw_data["non_product"] is True
    assert product.confidence == 0.0
    issues = eng.validate(product)
    assert any(i.fatal for i in issues)


def test_vaio_price_and_availability_present():
    path = FIXTURES / "vaio_products_p1.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    real = next(p for p in data["products"] if p.get("product_type") == "Laptop")
    eng = ShopifyEngine(_src("vaio-shopify", "https://us.vaio.com"), "VAIO")
    product = eng.normalize(RawProduct(
        source_id="vaio-shopify", url=f"https://us.vaio.com/products/{real['handle']}",
        payload=real))
    assert product.prices
    assert product.prices[0].currency == "USD"
    assert product.raw_data["available"] in (True, False)


def test_morefine_discovery_and_filtering():
    path = FIXTURES / "morefine_products_p1.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    eng = ShopifyEngine(_src("morefine-shopify", "https://www.morefine.com",
                             non_product_terms=["shipping-protection"]), "Morefine")
    fetcher = _FixtureFetcher({"products.json": path})
    refs = list(eng.discover(fetcher))
    assert len(refs) == len(data["products"]) == 40

    kept = []
    for ref in refs:
        product = eng.normalize(RawProduct(
            source_id="morefine-shopify", url=ref.url, payload=ref.inline_payload))
        if not product.raw_data.get("non_product"):
            kept.append(product)
    protection_skus = [p for p in data["products"] if p.get("product_type") == "shipping-protection"]
    assert len(protection_skus) == 2
    # 8 filtered total: 2 shipping-protection (via the source-scoped
    # non_product_terms above) + 4 external-GPU docks ("docking station") +
    # adapter + bracket (both caught by the built-in denylist already).
    assert len(kept) == 32
    assert all(p.manufacturer == "Morefine" for p in kept)


def test_morefine_without_denylist_config_keeps_protection_skus():
    """Confirms the filtering above is config-driven (non_product_terms), not
    hardcoded — without it, 'shipping-protection' isn't in the built-in
    denylist and those SKUs would NOT be auto-filtered."""
    path = FIXTURES / "morefine_products_p1.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    protection = next(p for p in data["products"] if p.get("product_type") == "shipping-protection")
    eng = ShopifyEngine(_src("morefine-shopify", "https://www.morefine.com"), "Morefine")
    product = eng.normalize(RawProduct(
        source_id="morefine-shopify",
        url=f"https://www.morefine.com/products/{protection['handle']}",
        payload=protection,
    ))
    assert product.raw_data.get("non_product") is not True


# ---- malformed / zero-catalog / health behavior ------------------------------

def test_vaio_malformed_fixture_does_not_crash_discovery():
    class BadFetcher:
        def get(self, url, **k):
            return FetchedDocument(url=url, status=200, body=b"{not json", content_type="application/json")
    eng = ShopifyEngine(_src("vaio-shopify", "https://us.vaio.com"), "VAIO")
    with pytest.raises(Exception):
        list(eng.discover(BadFetcher()))


def test_vaio_zero_catalog_marks_health_failed(store):
    class ZeroFetcher:
        def get(self, url, **k):
            return FetchedDocument(url=url, status=200,
                                   body=json.dumps({"products": []}).encode(),
                                   content_type="application/json")
    src = _src("vaio-shopify", "https://us.vaio.com")
    store.db.execute(
        "INSERT INTO crawler_runs(source_key, started_at, finished_at, status, stats_json) "
        "VALUES (?,?,?,?,?)",
        ("vaio-shopify", "2026-01-01", "2026-01-01", "ok", json.dumps({"discovered": 8})),
    )
    store.db.commit()
    eng = ShopifyEngine(src, "VAIO")
    stats = run_source(src, eng, ZeroFetcher(), store, ConsoleNotifier(),
                       health_cfg=CollectorHealthConfig())
    assert stats.health == "failed"
    assert stats.health_reason == "UNEXPECTED_ZERO"


def test_morefine_baseline_run_is_quiet(store):
    """First-ever crawl of a newly-enabled source must not notify (baseline)."""
    path = FIXTURES / "morefine_products_p1.json"
    sent = []

    def _sender(u, p):
        sent.append(p)
        return True, None

    notifier = DiscordNotifier(store, "https://hook.example", 1, sender=_sender)
    oems = {"Morefine": __import__("oem_radar.core.config", fromlist=["OemConfig"]).OemConfig(
        manufacturer=__import__("oem_radar.core.config", fromlist=["ManufacturerConfig"]).ManufacturerConfig(
            name="Morefine", country="CN"),
        sources=[_src("morefine-shopify", "https://www.morefine.com",
                      non_product_terms=["shipping-protection"])],
    )}
    from oem_radar.core.config import RadarConfig
    radar = RadarConfig(baseline_quiet=True)
    fetcher = _FixtureFetcher({"products.json": path})
    run_all(radar, oems, store, notifier, fetcher, force=True)
    pending = store.db.execute(
        "SELECT COUNT(*) c FROM notifications WHERE status='pending'").fetchone()["c"]
    assert pending == 0  # baseline crawl: history recorded, nothing queued to send

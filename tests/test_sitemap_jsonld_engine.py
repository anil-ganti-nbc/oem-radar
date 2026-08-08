"""Stage 6: the sitemap+JSON-LD engine. Real fixtures for the happy paths
(SimplyNUC, Khadas — see tests/fixtures/sitemap_jsonld/PROVENANCE.md);
hand-written malformed inputs for robustness paths (never presented as real
vendor data, only as parser-resilience checks — same convention as
tests/test_probe.py).

Dashboard/feedback/analytics compatibility isn't tested here separately:
this engine speaks the same NormalizedProduct/ChangeEvent contract every
other engine does, and those systems are already engine-agnostic (see
tests/test_dashboard.py, test_feedback_*.py) — a new engine gets that
compatibility for free by construction, not by writing engine-specific
dashboard tests.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from oem_radar.core.config import CollectorHealthConfig, SourceConfig, load_oem_configs
from oem_radar.core.models import ChangeType, FetchedDocument, ProductRef
from oem_radar.core.pipeline import run_source
from oem_radar.core.runner import run_all
from oem_radar.engines.sitemap_jsonld import SitemapJsonLdEngine
from oem_radar.providers.discord import ConsoleNotifier, DiscordNotifier
from oem_radar.providers.sqlite import SqliteStore

FIXTURES = Path(__file__).parent / "fixtures" / "sitemap_jsonld"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class _FixtureFetcher:
    """Routes URLs to on-disk fixtures or inline bodies; 404 otherwise."""

    def __init__(self, routes: dict[str, str]):
        self.routes = routes
        self.calls: list[str] = []

    def get(self, url: str, **kwargs):
        self.calls.append(url)
        if url in self.routes:
            return FetchedDocument(url=url, status=200, body=self.routes[url])
        return FetchedDocument(url=url, status=404, body="")


def _src(id_, base, **extra) -> SourceConfig:
    return SourceConfig(id=id_, engine="sitemap_jsonld", base_url=base, enabled=True, **extra)


@pytest.fixture()
def store(tmp_path):
    s = SqliteStore(str(tmp_path / "s.db"), str(tmp_path / "raw"))
    yield s
    s.close()


# ---- discovery: sitemap index / nested / duplicates / malformed -----------

def test_discovery_from_real_simplynuc_sitemap():
    eng = SitemapJsonLdEngine(
        _src("simplynuc", "https://snuc.com", sitemap_url="https://snuc.com/product-sitemap.xml"),
        "SimplyNUC")
    fetcher = _FixtureFetcher({
        "https://snuc.com/product-sitemap.xml": _read("simplynuc_product_sitemap.xml"),
    })
    refs = list(eng.discover(fetcher))
    assert len(refs) == 137
    assert all(isinstance(r, ProductRef) for r in refs)
    assert all(r.inline_payload is None for r in refs)  # per-page fetch required
    assert any(r.handle == "ee-1000" for r in refs)


def test_discovery_from_real_khadas_sitemap():
    eng = SitemapJsonLdEngine(
        _src("khadas", "https://www.khadas.com",
             sitemap_url="https://www.khadas.com/store-products-sitemap.xml"),
        "Khadas")
    fetcher = _FixtureFetcher({
        "https://www.khadas.com/store-products-sitemap.xml": _read("khadas_product_sitemap.xml"),
    })
    refs = list(eng.discover(fetcher))
    assert len(refs) == 78
    assert any(r.handle == "vim3" for r in refs)


def test_sitemap_index_recursion_into_leaf():
    index = """<?xml version="1.0"?>
    <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <sitemap><loc>https://ex.com/sitemap-products.xml</loc></sitemap>
      <sitemap><loc>https://ex.com/sitemap-pages.xml</loc></sitemap>
    </sitemapindex>"""
    products = """<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://ex.com/product/a</loc></url>
      <url><loc>https://ex.com/product/b</loc></url>
    </urlset>"""
    pages = """<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://ex.com/about</loc></url>
    </urlset>"""
    eng = SitemapJsonLdEngine(_src("ex", "https://ex.com"), "Ex")
    fetcher = _FixtureFetcher({
        "https://ex.com/sitemap.xml": index,
        "https://ex.com/sitemap-products.xml": products,
        "https://ex.com/sitemap-pages.xml": pages,
    })
    refs = list(eng.discover(fetcher))
    urls = {r.url for r in refs}
    assert urls == {"https://ex.com/product/a", "https://ex.com/product/b", "https://ex.com/about"}


def test_nested_sitemap_index_two_levels_deep():
    """An index pointing at another index pointing at a leaf."""
    top = """<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <sitemap><loc>https://ex.com/mid.xml</loc></sitemap>
    </sitemapindex>"""
    mid = """<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <sitemap><loc>https://ex.com/leaf.xml</loc></sitemap>
    </sitemapindex>"""
    leaf = """<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://ex.com/product/deep</loc></url>
    </urlset>"""
    eng = SitemapJsonLdEngine(_src("ex", "https://ex.com"), "Ex")
    fetcher = _FixtureFetcher({
        "https://ex.com/sitemap.xml": top,
        "https://ex.com/mid.xml": mid,
        "https://ex.com/leaf.xml": leaf,
    })
    refs = list(eng.discover(fetcher))
    assert [r.url for r in refs] == ["https://ex.com/product/deep"]


def test_duplicate_urls_across_sitemaps_deduped():
    index = """<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <sitemap><loc>https://ex.com/a.xml</loc></sitemap>
      <sitemap><loc>https://ex.com/b.xml</loc></sitemap>
    </sitemapindex>"""
    a = """<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://ex.com/product/x</loc></url>
    </urlset>"""
    b = """<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://ex.com/product/x</loc></url>
      <url><loc>https://ex.com/product/y</loc></url>
    </urlset>"""
    eng = SitemapJsonLdEngine(_src("ex", "https://ex.com"), "Ex")
    fetcher = _FixtureFetcher({"https://ex.com/sitemap.xml": index,
                               "https://ex.com/a.xml": a, "https://ex.com/b.xml": b})
    refs = list(eng.discover(fetcher))
    assert sorted(r.url for r in refs) == ["https://ex.com/product/x", "https://ex.com/product/y"]


def test_malformed_xml_sitemap_does_not_crash_discovery():
    eng = SitemapJsonLdEngine(_src("ex", "https://ex.com"), "Ex")
    fetcher = _FixtureFetcher({"https://ex.com/sitemap.xml": "<urlset><url><loc>broken"})
    refs = list(eng.discover(fetcher))
    assert refs == []  # no crash; just nothing usable extracted


def test_one_broken_nested_sitemap_does_not_sink_the_others():
    index = """<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <sitemap><loc>https://ex.com/broken.xml</loc></sitemap>
      <sitemap><loc>https://ex.com/good.xml</loc></sitemap>
    </sitemapindex>"""
    good = """<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://ex.com/product/ok</loc></url>
    </urlset>"""

    class FlakyFetcher(_FixtureFetcher):
        def get(self, url, **kwargs):
            if url == "https://ex.com/broken.xml":
                raise ConnectionError("simulated network failure")
            return super().get(url, **kwargs)

    eng = SitemapJsonLdEngine(_src("ex", "https://ex.com"), "Ex")
    fetcher = FlakyFetcher({"https://ex.com/sitemap.xml": index, "https://ex.com/good.xml": good})
    refs = list(eng.discover(fetcher))
    assert [r.url for r in refs] == ["https://ex.com/product/ok"]


def test_zero_product_sitemap():
    eng = SitemapJsonLdEngine(_src("ex", "https://ex.com"), "Ex")
    fetcher = _FixtureFetcher({
        "https://ex.com/sitemap.xml":
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></urlset>',
    })
    assert list(eng.discover(fetcher)) == []


def test_url_include_exclude_pattern_filtering():
    body = """<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://ex.com/notebook/a</loc></url>
      <url><loc>https://ex.com/headphones/b</loc></url>
    </urlset>"""
    eng = SitemapJsonLdEngine(
        _src("ex", "https://ex.com", url_include_pattern=r"/notebook/"), "Ex")
    fetcher = _FixtureFetcher({"https://ex.com/sitemap.xml": body})
    refs = list(eng.discover(fetcher))
    assert [r.url for r in refs] == ["https://ex.com/notebook/a"]


def test_max_products_safety_valve():
    urls = "".join(f"<url><loc>https://ex.com/product/{i}</loc></url>" for i in range(10))
    body = f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>'
    eng = SitemapJsonLdEngine(_src("ex", "https://ex.com", max_products=3), "Ex")
    fetcher = _FixtureFetcher({"https://ex.com/sitemap.xml": body})
    refs = list(eng.discover(fetcher))
    assert len(refs) == 3


# ---- parse + normalize on real fixtures ------------------------------------

def test_simplynuc_real_product_parses_with_graph_and_missing_price():
    eng = SitemapJsonLdEngine(_src("simplynuc", "https://snuc.com"), "SimplyNUC")
    doc = FetchedDocument(url="https://snuc.com/product/ee-1000/", status=200,
                          body=_read("simplynuc_product_ee1000.html"))
    raw = eng.parse(doc)
    assert raw.payload.get("@type") == "Product"
    product = eng.normalize(raw)
    assert product.model == "EE-1000"
    assert product.vendor_sku == "server-sku-ee-1000"
    assert product.prices == []  # real "$0 = quote required" placeholder, correctly dropped
    assert product.images
    issues = eng.validate(product)
    assert any(i.field == "prices" and not i.fatal for i in issues)


def test_simplynuc_missing_sku_product():
    eng = SitemapJsonLdEngine(_src("simplynuc", "https://snuc.com"), "SimplyNUC")
    doc = FetchedDocument(url="https://snuc.com/product/nuc15tzu7/", status=200,
                          body=_read("simplynuc_product_nuc15tzu7.html"))
    product = eng.normalize(eng.parse(doc))
    assert product.model
    assert product.vendor_sku is None
    issues = eng.validate(product)
    assert any(i.field == "vendor_sku" and not i.fatal for i in issues)


def test_simplynuc_giftcard_filtered_as_non_product_despite_real_price():
    eng = SitemapJsonLdEngine(_src("simplynuc", "https://snuc.com"), "SimplyNUC")
    doc = FetchedDocument(url="https://snuc.com/product/simply-nuc-e-gift-card/", status=200,
                          body=_read("simplynuc_product_giftcard.html"))
    product = eng.normalize(eng.parse(doc))
    assert product.raw_data["non_product"] is True
    issues = eng.validate(product)
    assert any(i.fatal for i in issues)


def test_khadas_real_product_price_and_availability_with_schema_casing_quirk():
    """Regression fixture: Khadas (Wix Stores) emits `Offers`/`Availability`
    with capital letters, not the documented `offers`/`availability`."""
    eng = SitemapJsonLdEngine(_src("khadas", "https://www.khadas.com"), "Khadas")
    doc = FetchedDocument(url="https://www.khadas.com/product-page/vim3", status=200,
                          body=_read("khadas_product_vim3.html"))
    product = eng.normalize(eng.parse(doc))
    assert product.model == "VIM3"
    assert len(product.prices) == 1
    assert product.prices[0].amount == 169.0
    assert product.prices[0].currency == "USD"
    from oem_radar.core.models import Availability
    assert product.prices[0].availability == Availability.IN_STOCK


def test_khadas_accessory_filtered_as_non_product():
    eng = SitemapJsonLdEngine(_src("khadas", "https://www.khadas.com"), "Khadas")
    doc = FetchedDocument(url="https://www.khadas.com/product-page/usb-c-24w-adapter", status=200,
                          body=_read("khadas_product_adapter.html"))
    product = eng.normalize(eng.parse(doc))
    assert product.raw_data["non_product"] is True


def test_brand_mismatch_produces_warning_not_fatal():
    """SimplyNUC's own JSON-LD brand is 'SNUC', not 'SimplyNUC' — a real
    naming quirk. Must warn, never break the source."""
    eng = SitemapJsonLdEngine(_src("simplynuc", "https://snuc.com"), "SimplyNUC")
    doc = FetchedDocument(url="https://snuc.com/product/ee-1000/", status=200,
                          body=_read("simplynuc_product_ee1000.html"))
    product = eng.normalize(eng.parse(doc))
    issues = eng.validate(product)
    brand_issues = [i for i in issues if i.field == "brand"]
    assert brand_issues and not brand_issues[0].fatal


# ---- synthetic JSON-LD shape coverage (object / array / @graph / offers) --

_PAGE_TMPL = '<html><head><script type="application/ld+json">{}</script></head></html>'


def _engine():
    return SitemapJsonLdEngine(_src("ex", "https://ex.com"), "Ex")


def test_plain_product_object():
    body = _PAGE_TMPL.format(json.dumps({
        "@context": "https://schema.org", "@type": "Product", "name": "Widget",
        "sku": "W1", "offers": {"price": "10", "priceCurrency": "USD", "availability": "InStock"},
    }))
    doc = FetchedDocument(url="https://ex.com/product/w1", status=200, body=body)
    product = _engine().normalize(_engine().parse(doc))
    assert product.model == "Widget"
    assert product.prices[0].amount == 10.0


def test_product_array_multiple_nodes_picks_matching_url():
    body = _PAGE_TMPL.format(json.dumps([
        {"@type": "Product", "name": "Other", "url": "https://ex.com/product/other"},
        {"@type": "Product", "name": "This One", "url": "https://ex.com/product/w1"},
    ]))
    doc = FetchedDocument(url="https://ex.com/product/w1", status=200, body=body)
    product = _engine().normalize(_engine().parse(doc))
    assert product.model == "This One"


def test_graph_with_multiple_product_nodes():
    body = _PAGE_TMPL.format(json.dumps({
        "@graph": [
            {"@type": "WebPage", "name": "irrelevant"},
            {"@type": "Product", "name": "Graphed", "url": "https://ex.com/product/w1"},
        ]
    }))
    doc = FetchedDocument(url="https://ex.com/product/w1", status=200, body=body)
    product = _engine().normalize(_engine().parse(doc))
    assert product.model == "Graphed"


def test_multiple_offers_keeps_all_instock_prices():
    body = _PAGE_TMPL.format(json.dumps({
        "@type": "Product", "name": "Multi", "sku": "M1",
        "offers": [
            {"price": "100", "priceCurrency": "USD", "availability": "InStock"},
            {"price": "120", "priceCurrency": "EUR", "availability": "OutOfStock"},
        ],
    }))
    doc = FetchedDocument(url="https://ex.com/product/m1", status=200, body=body)
    product = _engine().normalize(_engine().parse(doc))
    assert len(product.prices) == 2
    from oem_radar.core.models import Availability
    assert {p.currency for p in product.prices} == {"USD", "EUR"}
    assert any(p.availability == Availability.SOLD_OUT for p in product.prices)


def test_missing_price_field_entirely():
    body = _PAGE_TMPL.format(json.dumps({"@type": "Product", "name": "NoPrice", "sku": "N1"}))
    doc = FetchedDocument(url="https://ex.com/product/n1", status=200, body=body)
    product = _engine().normalize(_engine().parse(doc))
    assert product.prices == []
    assert product.model == "NoPrice"


def test_missing_images_field():
    body = _PAGE_TMPL.format(json.dumps({"@type": "Product", "name": "NoImg", "sku": "N2"}))
    doc = FetchedDocument(url="https://ex.com/product/n2", status=200, body=body)
    product = _engine().normalize(_engine().parse(doc))
    assert product.images == []


def test_image_as_array_of_objects():
    body = _PAGE_TMPL.format(json.dumps({
        "@type": "Product", "name": "ImgArr", "sku": "N3",
        "image": [{"contentUrl": "https://ex.com/a.jpg"}, {"url": "https://ex.com/b.jpg"}],
    }))
    doc = FetchedDocument(url="https://ex.com/product/n3", status=200, body=body)
    product = _engine().normalize(_engine().parse(doc))
    assert product.images == ["https://ex.com/a.jpg", "https://ex.com/b.jpg"]


def test_malformed_jsonld_block_skipped_not_fatal():
    body = '<html><head><script type="application/ld+json">{not valid json</script></head></html>'
    doc = FetchedDocument(url="https://ex.com/product/z1", status=200, body=body)
    raw = _engine().parse(doc)
    assert raw.payload == {}
    issues = _engine().validate(_engine().normalize(raw))
    assert any(i.fatal for i in issues)  # empty payload -> no model -> fatal, not a crash


def test_no_jsonld_at_all_on_page():
    doc = FetchedDocument(url="https://ex.com/product/z2", status=200,
                          body="<html><body>no structured data</body></html>")
    raw = _engine().parse(doc)
    product = _engine().normalize(raw)
    issues = _engine().validate(product)
    assert any(i.fatal and i.field == "model" for i in issues)


def test_unavailable_product_availability_mapped():
    from oem_radar.core.models import Availability
    body = _PAGE_TMPL.format(json.dumps({
        "@type": "Product", "name": "Gone", "sku": "G1",
        "offers": {"price": "50", "priceCurrency": "USD", "availability": "https://schema.org/OutOfStock"},
    }))
    doc = FetchedDocument(url="https://ex.com/product/g1", status=200, body=body)
    product = _engine().normalize(_engine().parse(doc))
    assert product.prices[0].availability == Availability.SOLD_OUT


def test_preorder_availability_mapped():
    from oem_radar.core.models import Availability
    body = _PAGE_TMPL.format(json.dumps({
        "@type": "Product", "name": "Soon", "sku": "S1",
        "offers": {"price": "50", "priceCurrency": "USD", "availability": "PreOrder"},
    }))
    doc = FetchedDocument(url="https://ex.com/product/s1", status=200, body=body)
    product = _engine().normalize(_engine().parse(doc))
    assert product.prices[0].availability == Availability.PREORDER


# ---- HTTP failures / health integration / evidence -------------------------

def test_http_failure_on_product_fetch_does_not_abort_source(store):
    """Per-URL fetch failures degrade one product, never the whole source
    (ARCHITECTURE.md §3) — exercised through the real pipeline."""
    class PartialFailFetcher:
        def get(self, url, **k):
            if "bad" in url:
                raise ConnectionError("simulated failure")
            return FetchedDocument(url=url, status=200, body=_PAGE_TMPL.format(json.dumps({
                "@type": "Product", "name": "Good", "sku": "OK1",
                "offers": {"price": "1", "priceCurrency": "USD", "availability": "InStock"},
            })))

    class TwoRefEngine(SitemapJsonLdEngine):
        def discover(self, fetcher):
            return [ProductRef(url="https://ex.com/product/bad", handle="bad"),
                    ProductRef(url="https://ex.com/product/good", handle="good")]

    src = _src("ex", "https://ex.com")
    store.db.execute(
        "INSERT INTO crawler_runs(source_key, started_at, finished_at, status, stats_json) "
        "VALUES (?,?,?,?,?)",
        ("ex", "2026-01-01", "2026-01-01", "ok", json.dumps({"discovered": 2})),
    )
    store.db.commit()
    eng = TwoRefEngine(src, "Ex")
    stats = run_source(src, eng, PartialFailFetcher(), store, ConsoleNotifier(),
                       health_cfg=CollectorHealthConfig())
    assert stats.snapshots_written == 1
    assert len(stats.errors) == 1
    assert "bad" in stats.errors[0]


def test_zero_catalog_marks_health_failed(store):
    class EmptyEngine(SitemapJsonLdEngine):
        def discover(self, fetcher):
            return []

    src = _src("ex", "https://ex.com")
    store.db.execute(
        "INSERT INTO crawler_runs(source_key, started_at, finished_at, status, stats_json) "
        "VALUES (?,?,?,?,?)",
        ("ex", "2026-01-01", "2026-01-01", "ok", json.dumps({"discovered": 20})),
    )
    store.db.commit()
    eng = EmptyEngine(src, "Ex")
    stats = run_source(src, eng, _FixtureFetcher({}), store, ConsoleNotifier(),
                       health_cfg=CollectorHealthConfig())
    assert stats.health == "failed"
    assert stats.health_reason == "UNEXPECTED_ZERO"


def test_source_url_evidence_present_on_normalized_product():
    eng = SitemapJsonLdEngine(_src("khadas", "https://www.khadas.com"), "Khadas")
    doc = FetchedDocument(url="https://www.khadas.com/product-page/vim3", status=200,
                          body=_read("khadas_product_vim3.html"))
    product = eng.normalize(eng.parse(doc))
    assert product.source_url
    assert product.raw_data.get("jsonld_type") == "Product"


def test_baseline_run_is_quiet(store):
    """First-ever crawl of a newly-enabled sitemap_jsonld source must not
    notify — same baseline-quiet contract as every other engine."""
    eng_urls = {
        "https://ex.com/sitemap.xml":
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            '<url><loc>https://ex.com/product/p1</loc></url></urlset>',
        "https://ex.com/product/p1": _PAGE_TMPL.format(json.dumps({
            "@type": "Product", "name": "Baseline Item", "sku": "B1",
            "offers": {"price": "1", "priceCurrency": "USD", "availability": "InStock"},
        })),
    }
    from oem_radar.core.config import ManufacturerConfig, OemConfig, RadarConfig
    radar = RadarConfig(baseline_quiet=True)
    oems = {"Ex": OemConfig(manufacturer=ManufacturerConfig(name="Ex", country="US"),
                            sources=[_src("ex", "https://ex.com")])}
    sent = []
    notifier = DiscordNotifier(store, "https://hook.example", 1,
                               sender=lambda u, p: (sent.append(p), (True, None))[1])
    run_all(radar, oems, store, notifier, _FixtureFetcher(eng_urls), force=True)
    pending = store.db.execute(
        "SELECT COUNT(*) c FROM notifications WHERE status='pending'").fetchone()["c"]
    assert pending == 0


# ---- config wiring ----------------------------------------------------------

def test_simplynuc_and_khadas_load_enabled_with_new_engine():
    oems = load_oem_configs(Path("config/oems"))
    assert "SimplyNUC" in oems
    snuc_src = next(s for s in oems["SimplyNUC"].sources if s.id == "simplynuc-sitemap")
    assert snuc_src.enabled is True
    assert snuc_src.engine == "sitemap_jsonld"

    assert "Khadas" in oems
    khadas_src = next(s for s in oems["Khadas"].sources if s.id == "khadas-sitemap")
    assert khadas_src.enabled is True
    assert khadas_src.engine == "sitemap_jsonld"

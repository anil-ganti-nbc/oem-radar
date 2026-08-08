"""Stage 8 Phase 1: the category_jsonld engine. Built after Samsung became
the second confirmed OEM (after `dell`) with the "category page embeds a
full ItemList of Product nodes" shape — see docs/STAGE8.md and
`docs/ENTERPRISE_OEM_ARCHITECTURE.md` §9's stated trigger for a third
reusable engine of that shape. Real fixture for the happy path (the actual
Samsung Galaxy Book category page); hand-written malformed/edge-case inputs
only for parser-robustness checks, per the project's fixture policy.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from oem_radar.core.config import CollectorHealthConfig, SourceConfig, load_oem_configs
from oem_radar.core.models import FetchedDocument, RawProduct
from oem_radar.core.pipeline import run_source
from oem_radar.core.runner import run_all
from oem_radar.engines.category_jsonld import CategoryJsonLdEngine
from oem_radar.providers.discord import ConsoleNotifier, DiscordNotifier
from oem_radar.providers.sqlite import SqliteStore

FIXTURES = Path(__file__).parent / "fixtures" / "category_jsonld"
SAMSUNG_URL = "https://www.samsung.com/us/computers/galaxy-book/"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _src(id_, base, **extra) -> SourceConfig:
    return SourceConfig(id=id_, engine="category_jsonld", base_url=base,
                        enabled=True, **extra)


@pytest.fixture()
def store(tmp_path):
    s = SqliteStore(str(tmp_path / "s.db"), str(tmp_path / "raw"))
    yield s
    s.close()


class _StaticFetcher:
    """Serves a fixed body for one or more configured URLs."""

    def __init__(self, pages: dict[str, str]):
        self.pages = pages
        self.calls: list[str] = []

    def get(self, url: str, **kwargs):
        self.calls.append(url)
        body = self.pages.get(url)
        if body is None:
            raise ConnectionError(f"unexpected URL: {url}")
        return FetchedDocument(url=url, status=200, body=body, content_type="text/html")


# ============================================================================
# discovery: real Samsung fixture
# ============================================================================

def test_discovery_real_samsung_itemlist():
    eng = CategoryJsonLdEngine(_src("samsung-galaxybook", "https://www.samsung.com",
                                    category_urls=[SAMSUNG_URL]), "Samsung")
    fetcher = _StaticFetcher({SAMSUNG_URL: _read("samsung_galaxy_book_category.html")})
    refs = list(eng.discover(fetcher))
    assert len(refs) == 12  # real numberOfItems on the captured page
    assert all(r.inline_payload is not None for r in refs)  # bulk-inline, no per-page fetch


def test_discovery_extracts_sku_from_url_suffix():
    """Samsung's ItemList items have no sku/mpn field — identity comes from
    the '-sku-XXXXXX' URL suffix, a real-world quirk this engine exists to
    handle via a configurable regex rather than a hardcoded assumption."""
    eng = CategoryJsonLdEngine(_src("samsung-galaxybook", "https://www.samsung.com",
                                    category_urls=[SAMSUNG_URL]), "Samsung")
    fetcher = _StaticFetcher({SAMSUNG_URL: _read("samsung_galaxy_book_category.html")})
    refs = list(eng.discover(fetcher))
    handles = {r.handle for r in refs}
    assert "NP960UJH-XG7US" in handles


def test_discovery_ignores_breadcrumblist_and_webpage_nodes():
    """The real fixture also carries a BreadcrumbList and a WebPage JSON-LD
    node alongside the ItemList — only the ItemList's nested Products count."""
    eng = CategoryJsonLdEngine(_src("samsung-galaxybook", "https://www.samsung.com",
                                    category_urls=[SAMSUNG_URL]), "Samsung")
    fetcher = _StaticFetcher({SAMSUNG_URL: _read("samsung_galaxy_book_category.html")})
    refs = list(eng.discover(fetcher))
    assert all("Galaxy Book" in (r.inline_payload or {}).get("name", "") for r in refs)


def test_discovery_dedupes_across_multiple_category_urls():
    eng = CategoryJsonLdEngine(_src("samsung-galaxybook", "https://www.samsung.com",
                                    category_urls=[SAMSUNG_URL, SAMSUNG_URL + "?x=1"]), "Samsung")
    fetcher = _StaticFetcher({
        SAMSUNG_URL: _read("samsung_galaxy_book_category.html"),
        SAMSUNG_URL + "?x=1": _read("samsung_galaxy_book_category.html"),
    })
    refs = list(eng.discover(fetcher))
    assert len(refs) == 12  # same 12 SKUs seen twice, deduped


def test_discovery_one_bad_category_url_does_not_lose_the_others():
    eng = CategoryJsonLdEngine(_src("ex", "https://ex.com",
                                    category_urls=["https://ex.com/broken", SAMSUNG_URL]), "Ex")
    fetcher = _StaticFetcher({SAMSUNG_URL: _read("samsung_galaxy_book_category.html")})
    refs = list(eng.discover(fetcher))
    assert len(refs) == 12


def test_discovery_no_itemlist_yields_nothing():
    eng = CategoryJsonLdEngine(_src("ex", "https://ex.com",
                                    category_urls=["https://ex.com/empty"]), "Ex")
    fetcher = _StaticFetcher({"https://ex.com/empty": "<html><body>no products here</body></html>"})
    assert list(eng.discover(fetcher)) == []


def test_discovery_itemlist_of_non_products_ignored():
    """A real-world negative case: an ItemList whose entries are plain
    ListItems (e.g. a breadcrumb-style nav list), not Products/offers — must
    not be mistaken for a product catalog."""
    html = """<html><head><script type="application/ld+json">
    {"@type":"ItemList","itemListElement":[
      {"@type":"ListItem","position":1,"name":"Home","item":"https://ex.com/"},
      {"@type":"ListItem","position":2,"name":"Computers","item":"https://ex.com/computers"}
    ]}
    </script></head><body></body></html>"""
    eng = CategoryJsonLdEngine(_src("ex", "https://ex.com", category_urls=["https://ex.com/nav"]), "Ex")
    fetcher = _StaticFetcher({"https://ex.com/nav": html})
    assert list(eng.discover(fetcher)) == []


# ============================================================================
# normalize: real fixture payloads
# ============================================================================

def _samsung_item(idx: int = 0) -> dict:
    eng = CategoryJsonLdEngine(_src("samsung-galaxybook", "https://www.samsung.com",
                                    category_urls=[SAMSUNG_URL]), "Samsung")
    fetcher = _StaticFetcher({SAMSUNG_URL: _read("samsung_galaxy_book_category.html")})
    refs = list(eng.discover(fetcher))
    return eng, refs[idx].inline_payload


def test_normalize_real_price_and_availability():
    eng, payload = _samsung_item(0)
    raw = RawProduct(source_id="samsung-galaxybook", url=payload["url"], payload=payload)
    product = eng.normalize(raw)
    assert product.prices
    assert product.prices[0].currency == "USD"
    assert product.prices[0].amount > 0
    from oem_radar.core.models import Availability
    assert product.prices[0].availability == Availability.IN_STOCK


def test_normalize_vendor_sku_from_url():
    eng, payload = _samsung_item(0)
    raw = RawProduct(source_id="samsung-galaxybook", url=payload["url"], payload=payload)
    product = eng.normalize(raw)
    assert product.vendor_sku == "NP960UJH-XG7US"
    assert "NP960UJH-XG7US" in product.aliases


def test_normalize_cpu_extraction_from_url_slug():
    eng, payload = _samsung_item(1)  # snapdragon x2 elite edge model
    raw = RawProduct(source_id="samsung-galaxybook", url=payload["url"], payload=payload)
    product = eng.normalize(raw)
    assert product.cpu is not None
    assert "snapdragon" in product.cpu.raw.lower()


def test_normalize_confidence_full_when_sku_and_price_present():
    eng, payload = _samsung_item(0)
    raw = RawProduct(source_id="samsung-galaxybook", url=payload["url"], payload=payload)
    product = eng.normalize(raw)
    assert product.confidence == 1.0


# ============================================================================
# malformed / missing-field robustness (hand-written, parser-only)
# ============================================================================

def test_missing_name_is_fatal():
    eng = CategoryJsonLdEngine(_src("ex", "https://ex.com"), "Ex")
    p = {"url": "https://ex.com/x"}
    product = eng.normalize(RawProduct(source_id="ex", url=p["url"], payload=p))
    issues = eng.validate(product)
    assert any(i.fatal for i in issues)


def test_missing_sku_no_url_match_is_non_fatal():
    eng = CategoryJsonLdEngine(_src("ex", "https://ex.com"), "Ex")
    p = {"name": "Widget", "url": "https://ex.com/widget"}
    product = eng.normalize(RawProduct(source_id="ex", url=p["url"], payload=p))
    assert product.vendor_sku is None
    issues = eng.validate(product)
    assert any(i.field == "vendor_sku" and not i.fatal for i in issues)


def test_malformed_price_string_degrades_gracefully():
    eng = CategoryJsonLdEngine(_src("ex", "https://ex.com"), "Ex")
    p = {"name": "Bad", "url": "https://ex.com/bad",
         "offers": {"price": "not-a-number", "priceCurrency": "USD"}}
    product = eng.normalize(RawProduct(source_id="ex", url=p["url"], payload=p))
    assert product.prices == []  # doesn't crash


def test_zero_price_dropped():
    eng = CategoryJsonLdEngine(_src("ex", "https://ex.com"), "Ex")
    p = {"name": "Quote", "url": "https://ex.com/q",
         "offers": {"price": "0", "priceCurrency": "USD"}}
    product = eng.normalize(RawProduct(source_id="ex", url=p["url"], payload=p))
    assert product.prices == []


def test_offers_as_list_uses_first():
    eng = CategoryJsonLdEngine(_src("ex", "https://ex.com"), "Ex")
    p = {"name": "Multi", "url": "https://ex.com/m",
         "offers": [{"price": "199.99", "priceCurrency": "USD", "availability": "InStock"}]}
    product = eng.normalize(RawProduct(source_id="ex", url=p["url"], payload=p))
    assert product.prices and product.prices[0].amount == 199.99


def test_non_product_denylist_filters_and_is_fatal():
    eng = CategoryJsonLdEngine(_src("ex", "https://ex.com", non_product_terms=["carrying case"]), "Ex")
    p = {"name": "Galaxy Book Carrying Case", "url": "https://ex.com/case",
         "offers": {"price": "39.99", "priceCurrency": "USD"}}
    product = eng.normalize(RawProduct(source_id="ex", url=p["url"], payload=p))
    assert product.raw_data["non_product"] is True
    issues = eng.validate(product)
    assert any(i.fatal for i in issues)


# ============================================================================
# HTTP failures / health / evidence — through the real pipeline
# ============================================================================

def test_zero_catalog_marks_health_failed(store):
    src = _src("ex", "https://ex.com", category_urls=["https://ex.com/empty"])
    eng = CategoryJsonLdEngine(src, "Ex")
    store.db.execute(
        "INSERT INTO crawler_runs(source_key, started_at, finished_at, status, stats_json) "
        "VALUES (?,?,?,?,?)",
        ("ex", "2026-01-01", "2026-01-01", "ok", '{"discovered": 10}'),
    )
    store.db.commit()
    fetcher = _StaticFetcher({"https://ex.com/empty": "<html></html>"})
    stats = run_source(src, eng, fetcher, store, ConsoleNotifier(),
                       health_cfg=CollectorHealthConfig())
    assert stats.health == "failed"
    assert stats.health_reason == "UNEXPECTED_ZERO"


def test_source_isolation_one_broken_product_does_not_abort_source(store):
    class BrokenNormalizeEngine(CategoryJsonLdEngine):
        def normalize(self, raw):
            if raw.payload.get("url", "").endswith("broken"):
                raise RuntimeError("simulated normalize failure")
            return super().normalize(raw)

    html = """<html><head><script type="application/ld+json">
    {"@type":"ItemList","numberOfItems":2,"itemListElement":[
      {"@type":"ListItem","position":1,"item":{"@type":"Product","name":"Broken",
        "url":"https://ex.com/broken","offers":{"price":"999","priceCurrency":"USD"}}},
      {"@type":"ListItem","position":2,"item":{"@type":"Product","name":"Fine",
        "url":"https://ex.com/fine","offers":{"price":"100","priceCurrency":"USD"}}}
    ]}
    </script></head></html>"""
    src = _src("ex", "https://ex.com", category_urls=["https://ex.com/cat"])
    eng = BrokenNormalizeEngine(src, "Ex")
    fetcher = _StaticFetcher({"https://ex.com/cat": html})
    stats = run_source(src, eng, fetcher, store, ConsoleNotifier(),
                       health_cfg=CollectorHealthConfig())
    assert stats.snapshots_written == 1
    assert len(stats.errors) == 1


def test_baseline_run_is_quiet(store):
    from oem_radar.core.config import ManufacturerConfig, OemConfig, RadarConfig
    src = _src("samsung-galaxybook", "https://www.samsung.com", category_urls=[SAMSUNG_URL])
    radar = RadarConfig(baseline_quiet=True)
    oems = {"Samsung": OemConfig(manufacturer=ManufacturerConfig(name="Samsung", country="KR"),
                                 sources=[src])}
    notifier = DiscordNotifier(store, "https://hook.example", 1, sender=lambda u, p: (True, None))
    fetcher = _StaticFetcher({SAMSUNG_URL: _read("samsung_galaxy_book_category.html")})
    run_all(radar, oems, store, notifier, fetcher, force=True)
    pending = store.db.execute(
        "SELECT COUNT(*) c FROM notifications WHERE status='pending'").fetchone()["c"]
    assert pending == 0


# ============================================================================
# config wiring
# ============================================================================

def test_samsung_loads_enabled():
    oems = load_oem_configs(Path("config/oems"))
    assert "Samsung" in oems
    src = next(s for s in oems["Samsung"].sources if s.id == "samsung-galaxybook")
    assert src.enabled is True
    assert src.engine == "category_jsonld"


def test_lenovo_loads_but_deliberately_not_enabled():
    """Lenovo's /buy/ landing pages have real, engine-compatible data (see
    the discovery tests below) — but they 403 the project's actual, honest
    crawler UA (only a spoofed browser UA gets 200), and this project does
    not spoof identity to defeat bot detection. Config is kept, real
    fixtures are kept, engine wiring is proven — enablement is not."""
    oems = load_oem_configs(Path("config/oems"))
    assert "Lenovo" in oems
    src = next(s for s in oems["Lenovo"].sources if s.id == "lenovo-buy-landing")
    assert src.enabled is False
    assert src.engine == "category_jsonld"
    assert len(src.category_urls) == 3


# ============================================================================
# Lenovo real fixtures (Stage 8 Phase 2) — confirms the engine generalizes
# to a second real OEM beyond Samsung with no code changes, and confirms
# the multi-SKU-same-name pattern that motivated the resolve_prior fix.
# Not enabled in production (see test above) — these tests exist to prove
# the engine/config side is genuinely correct, independent of the UA issue.
# ============================================================================

_LENOVO_URLS = {
    "thinkpad-p": "https://www.lenovo.com/buy/us/en/amd-ryzen-7-pro-thinkpad-p-series-laptops-0arz00a",
    "wide-screen": "https://www.lenovo.com/buy/us/en/intel/wide-screen-laptops-0abz00a",
    "under-800": "https://www.lenovo.com/buy/us/en/laptops-under-800-0akz00a",
}
_LENOVO_FIXTURES = {
    "thinkpad-p": "lenovo_buy_thinkpad_p_series.html",
    "wide-screen": "lenovo_buy_wide_screen_laptops.html",
    "under-800": "lenovo_buy_laptops_under_800.html",
}


def test_lenovo_discovery_across_three_real_landing_pages():
    eng = CategoryJsonLdEngine(_src("lenovo-buy-landing", "https://www.lenovo.com",
                                    category_urls=list(_LENOVO_URLS.values())), "Lenovo")
    fetcher = _StaticFetcher({_LENOVO_URLS[k]: _read(_LENOVO_FIXTURES[k]) for k in _LENOVO_URLS})
    refs = list(eng.discover(fetcher))
    assert len(refs) == 24 + 20 + 20  # 64 real SKUs across the 3 confirmed pages, no collisions


def test_lenovo_real_price_and_sku_from_item_fields():
    """Unlike Samsung, Lenovo's ItemList items DO carry a real sku field
    directly — no URL-suffix fallback needed for this OEM."""
    eng = CategoryJsonLdEngine(_src("lenovo-buy-landing", "https://www.lenovo.com",
                                    category_urls=[_LENOVO_URLS["thinkpad-p"]]), "Lenovo")
    fetcher = _StaticFetcher({_LENOVO_URLS["thinkpad-p"]: _read(_LENOVO_FIXTURES["thinkpad-p"])})
    refs = list(eng.discover(fetcher))
    ref = next(r for r in refs if r.handle == "21X00007US")
    product = eng.normalize(RawProduct(source_id="lenovo-buy-landing", url=ref.url,
                                       payload=ref.inline_payload))
    assert product.vendor_sku == "21X00007US"
    assert product.prices and product.prices[0].amount == 2905.56
    assert product.prices[0].currency == "USD"


def test_lenovo_same_model_name_different_skus_stay_distinct():
    """Real-world case: several ThinkPad P14s configs share the exact same
    display name at different prices/SKUs — the engine must keep them as
    distinct discovered refs (identity resolution, not discovery, is what
    keeps them from merging downstream — see test_sqlite_store.py)."""
    eng = CategoryJsonLdEngine(_src("lenovo-buy-landing", "https://www.lenovo.com",
                                    category_urls=[_LENOVO_URLS["thinkpad-p"]]), "Lenovo")
    fetcher = _StaticFetcher({_LENOVO_URLS["thinkpad-p"]: _read(_LENOVO_FIXTURES["thinkpad-p"])})
    refs = list(eng.discover(fetcher))
    same_name_skus = {r.handle for r in refs
                      if "ThinkPad P14s Gen 7 AMD" in (r.inline_payload or {}).get("name", "")}
    assert len(same_name_skus) > 1  # multiple distinct SKUs, not collapsed into one ref

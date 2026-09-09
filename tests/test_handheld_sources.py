"""Handheld expansion wave 1 (M1): six config-only Shopify sources.

Every source here is staged `enabled: false` — this file proves the
descriptors and their captured fixtures behave under the EXISTING engine,
identity, and baseline machinery, with no new engine and no schema change.

Fixtures are unmodified captures of real `/products.json` responses
(see tests/fixtures/shopify/PROVENANCE.md, 2026-09-09 entries). Tests
assert on representative products *by title substring* rather than exact
catalog counts, so re-capturing a fixture with a different catalog size
does not churn the suite.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from oem_radar.core.config import (
    ManufacturerConfig,
    OemConfig,
    RadarConfig,
    SourceConfig,
    load_oem_configs,
)
from oem_radar.core.knownhw import SEED_COMPONENTS
from oem_radar.core.models import FetchedDocument, RawProduct
from oem_radar.core.runner import run_all
from oem_radar.engines import shopify  # noqa: F401  (registers engine)
from oem_radar.engines.shopify import ShopifyEngine
from oem_radar.providers.discord import DiscordNotifier
from oem_radar.providers.sqlite import SqliteStore, _same_product, model_key
from test_models import make_product

REPO = Path(__file__).parent.parent

# manufacturer name -> (source id, fixture stem, base_url, kept handheld title
# substring, filtered accessory title substring)
SOURCES = {
    "Anbernic": ("anbernic-shopify", "anbernic", "https://anbernic.com",
                 "RG35XX H", "protective bag for RG35XXSP"),
    "AYANEO": ("ayaneo-shopify", "ayaneo", "https://shop.ayaneo.com",
               "KONKR Pocket ADVANCE", "Storage Bag For AYANEO 3"),
    "ONEXPLAYER": ("onexplayer-shopify", "onexplayer", "https://onexplayerstore.com",
                   "ONEXFLY APEX Air", "Refurbished OneXPlayer Super X"),
    "AYN": ("ayn-shopify", "ayn", "https://www.ayntec.com",
            "Odin 3 (Batch 8 Pre-order)", "Odin 3 Carrying Case"),
    "Retroid": ("retroid-shopify", "retroid", "https://www.goretroid.com",
                "Pocket 6 Handheld", "Retroid Pocket 6 Carrying Case"),
    "AOKZOE": ("aokzoe-shopify", "aokzoe", "https://aokzoestore.com",
               "A1X", "Refurbished AOKZOE A2"),
}


def _load(manufacturer: str) -> tuple[OemConfig, SourceConfig]:
    oems = load_oem_configs(REPO / "config" / "oems")
    oem = oems[manufacturer]
    return oem, next(s for s in oem.sources if s.id == SOURCES[manufacturer][0])


def _fixture(stem: str) -> dict:
    path = REPO / "tests" / "fixtures" / "shopify" / f"{stem}_products_p1.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _engine(manufacturer: str) -> ShopifyEngine:
    _, src = _load(manufacturer)
    return ShopifyEngine(src, manufacturer)


def _normalize_all(manufacturer: str):
    _, src = _load(manufacturer)
    engine = _engine(manufacturer)
    for p in _fixture(SOURCES[manufacturer][1])["products"]:
        product = engine.normalize(
            RawProduct(source_id=src.id,
                       url=f"{src.base_url}/products/{p['handle']}", payload=p)
        )
        yield p, product, engine.validate(product)


# -- A. descriptor / registration contract ------------------------------------

@pytest.mark.parametrize("manufacturer", sorted(SOURCES))
def test_descriptors_staged_disabled_on_shopify(manufacturer):
    stem = SOURCES[manufacturer][1]
    oem, src = _load(manufacturer)
    assert src.engine == "shopify"
    assert src.enabled is False, "wave-1 sources ship disabled; enablement is a later gate"
    assert src.base_url == SOURCES[manufacturer][2]
    assert src.id.endswith("-shopify")
    assert src.min_interval_s in (12 * 3600, 24 * 3600), "documented P1/P2 cadence only"
    assert _fixture(stem)["products"], "fixture must exist for every descriptor"


def test_ayaneo_retargeted_off_the_dead_surface():
    """Requirement J: no config path still treats www.ayaneo.com as the
    active Shopify collector; the store surface is the one descriptor."""
    oems = load_oem_configs(REPO / "config" / "oems")
    ayaneo = oems["AYANEO"]
    assert [s.base_url for s in ayaneo.sources] == ["https://shop.ayaneo.com"]
    for oem in oems.values():
        for src in oem.sources:
            assert "ayaneo.com" not in src.base_url or src.base_url.startswith("https://shop.")


# -- B/C/D. fixture normalization: handhelds kept + categorized, accessories
#     denied — config-only (per-source non_product_terms / category_map) ------

@pytest.mark.parametrize("manufacturer", sorted(SOURCES))
def test_handheld_kept_and_categorized_and_accessory_denied(manufacturer):
    keep_sub, acc_sub = SOURCES[manufacturer][3], SOURCES[manufacturer][4]
    kept, denied = {}, []
    for p, product, issues in _normalize_all(manufacturer):
        if any(i.fatal for i in issues):
            denied.append(p["title"].lower())
        else:
            kept[p["title"]] = product
    assert any(keep_sub.lower() in t.lower() for t in kept), "real handheld must survive"
    handhelds = [p for t, p in kept.items() if keep_sub.lower() in t.lower()]
    assert any(p.category == "handheld" for p in handhelds), (
        "feed taxonomy must map the handheld into the ratified category"
    )
    assert any(acc_sub.lower() in t for t in denied), "accessory must be denied"


def test_konkr_stays_visible_inside_the_ayaneo_namespace():
    """KONKR is a sub-brand arriving under vendor AYANEO: existing semantics
    keep it in the model name rather than forcing a separate manufacturer."""
    for p, product, issues in _normalize_all("AYANEO"):
        if "konkr" in p["title"].lower() and not any(i.fatal for i in issues):
            assert product.manufacturer == "AYANEO"
            assert "KONKR" in product.model.upper()
            break
    else:
        pytest.fail("no kept KONKR product in the AYANEO fixture")


# -- E. variants keep existing Configuration semantics ------------------------

def test_anbernic_variant_configurations_and_skus_preserved():
    for p, product, issues in _normalize_all("Anbernic"):
        if p["title"].strip().lower() == "anbernic rg 55g1":
            assert not any(i.fatal for i in issues)
            assert len(product.configurations) > 1
            assert any(c.sku for c in product.configurations)
            return
    pytest.fail("RG 55G1 fixture entry missing")


def test_ayn_batch_preorder_arrives_as_sold_out_not_a_special_state():
    """Batch-numbered pre-orders are ordinary variants with available=false;
    existing engine semantics map that to SOLD_OUT (no new availability
    machinery was added for handhelds)."""
    for p, product, issues in _normalize_all("AYN"):
        if "odin 3" in p["title"].lower() and "batch" in p["title"].lower():
            assert not any(i.fatal for i in issues)
            assert all(
                c.availability.value in ("sold_out", "in_stock")
                for c in product.configurations
            )
            assert any(c.availability.value == "sold_out" for c in product.configurations)
            return
    pytest.fail("Odin 3 batch pre-order fixture entry missing")


# -- F. identity: handheld naming against the existing resolver ---------------

def test_handheld_model_keys_and_tier_word_guards():
    # Real captured names. Coarse keys deliberately collide within a family
    # (candidate links); separation comes from the tier-word guard and the
    # vendor-SKU disagreement guard.
    assert model_key("Anbernic", "RG35XX") == model_key("Anbernic", "RG35XX H")
    assert _same_product("RG35XX Plus", "RG35XX H") is False  # 'plus' is a tier word
    assert model_key("Anbernic", "RG Cube") != model_key("Anbernic", "RG CubeXX")
    assert model_key("AYN", "Odin 2 Base") != model_key("AYN", "Odin2 Portal")
    assert model_key("Retroid", "Pocket 5") != model_key("Retroid", "Pocket 6")


def test_rg35xx_vs_rg35xx_h_is_documented_current_behaviour():
    """KNOWN CAVEAT (finding F-1, not changed here): 'H' is not a tier word,
    so RG35XX and RG35XX H share a coarse key and pass _same_product. In the
    live feed both listings carry distinct vendor SKUs, so resolve_prior's
    SKU-disagreement guard is what separates them; a SKU-less feed would
    collapse the second listing into DUPLICATE_LISTING. Fixture-level tests
    below pin that guard; a resolver change is a separate mission."""
    assert _same_product("RG35XX", "RG35XX H") is True


def test_distinct_sku_guards_rg35xx_variants(tmp_path):
    s = SqliteStore(str(tmp_path / "radar.db"), str(tmp_path / "raw"))
    try:
        s.append("anbernic-shopify:rg35xx-h",
                 make_product(manufacturer="Anbernic", model="RG35XX H",
                              vendor_sku="EN-China-RG35XXH-Black-32G"))
        prior, relation = s.resolve_prior(
            "anbernic-shopify:rg35xx-plus",
            make_product(manufacturer="Anbernic", model="RG35XX Plus",
                         vendor_sku="EN-China-RG35XXPLUS-Black-32G"),
        )
        assert relation == "none" and prior is None
    finally:
        s.close()


# -- G/I. baseline silence, second-crawl stability, real post-baseline novelty

BASE_URL = SOURCES["Anbernic"][2]


class CatalogFetcher:
    """Serves one catalog dict as products.json page 1 for BASE_URL; every
    later page is empty (same shape as test_runner.RouteFetcher, but bound
    to the handheld source's base URL)."""

    def __init__(self, catalog: dict):
        self.catalog = catalog

    def get(self, url: str) -> FetchedDocument:
        if url.startswith(f"{BASE_URL}/products.json"):
            page = url.rsplit("=", 1)[-1]
            body = self.catalog if page == "1" else {"products": []}
            return FetchedDocument(url=url, status=200, body=json.dumps(body))
        raise KeyError(url)


@pytest.fixture()
def anbernic_radar(tmp_path):
    radar = RadarConfig(db_path=str(tmp_path / "r.db"), raw_dir=str(tmp_path / "raw"),
                        baseline_quiet=True)
    oems = {"Anbernic": OemConfig(
        manufacturer=ManufacturerConfig(name="Anbernic", country="CN"),
        sources=[SourceConfig(id="anbernic-shopify", engine="shopify",
                              base_url=BASE_URL, discovery=["products_json"])],
    )}
    store = SqliteStore(radar.db_path, radar.raw_dir)
    store.seed_components(SEED_COMPONENTS)
    sent = []
    notifier = DiscordNotifier(store, "https://hook.example", 3,
                               sender=lambda u, p: (sent.append(p), None) and (True, None))
    yield radar, oems, store, notifier, sent
    store.close()


def test_baseline_silence_then_stability_then_real_novelty(anbernic_radar):
    radar, oems, store, notifier, sent = anbernic_radar
    catalog = _fixture("anbernic")

    # First-ever crawl: history recorded, nothing delivered.
    stats = run_all(radar, oems, store, notifier, CatalogFetcher(catalog), force=True)
    assert stats[0].snapshots_written > 0
    assert sent == []
    events = store.db.execute(
        "SELECT change_type, meta_json FROM change_events"
    ).fetchall()
    assert events, "baseline crawl must record history"
    assert all(json.loads(row["meta_json"]).get("baseline") for row in events)

    # Second identical crawl: no duplicate novelty.
    stats2 = run_all(radar, oems, store, notifier, CatalogFetcher(catalog), force=True)
    assert stats2[0].events == 0
    assert stats2[0].unchanged == stats[0].snapshots_written

    # A real post-baseline listing arrives: ordinary NEW_PRODUCT semantics,
    # not a baseline re-interpretation of first-seen history. Derived from a
    # real captured listing (new handle/SKU), mirroring the mutation style of
    # test_baseline_event_ux.
    newer = copy.deepcopy(catalog)
    template = copy.deepcopy(
        next(p for p in newer["products"] if p["title"].strip().lower() == "anbernic rg cube")
    )
    template["handle"] = "anbernic-rg-cube-2"
    template["title"] = "ANBERNIC RG Cube 2"
    for v in template["variants"]:
        v["sku"] = (v.get("sku") or "RG-CUBE2") + "-2"
    newer["products"].append(template)
    stats3 = run_all(radar, oems, store, notifier, CatalogFetcher(newer), force=True)
    assert stats3[0].events >= 1
    new_products = store.db.execute(
        "SELECT product_key, meta_json FROM change_events WHERE change_type='new_product' "
        "AND COALESCE(json_extract(meta_json,'$.baseline'),0)=0"
    ).fetchall()
    assert any("rg-cube-2" in row["product_key"] for row in new_products)
    assert sent, "post-baseline BREAKING new product must reach the outbox drain"

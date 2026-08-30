import json
from datetime import datetime, timezone

from oem_radar.core.models import FetchedDocument
from oem_radar.experimental.japan_mini_pc import (
    EPSON_CATALOGUE_URL,
    EPSON_PRESS_URL,
    GEEKOM_GLOBAL_PRODUCTS_URL,
    GEEKOM_JP_PRODUCTS_URL,
    MOUSEPRO_CR_URL,
    NEC_NEW_URL,
    THIRDWAVE_HG_URL,
    ExperimentalJapanMiniStore,
    JapanMiniProbeCollector,
    parse_epson_press,
    parse_geekom_global_products,
    parse_geekom_jp_products,
    parse_mousepro_cr,
    parse_nec_mate_new,
    parse_thirdwave_hg,
)


NOW = datetime(2026, 8, 31, tzinfo=timezone.utc)


class Fetch:
    def __init__(self, docs):
        self.docs = docs
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        return FetchedDocument(url=url, status=200, body=self.docs[url])


def geekom(title, handle, cpu):
    return {"id": 1, "title": title, "handle": handle, "body_html": "",
            "variants": [{"option1": cpu, "option2": "32GB RAM", "option3": "1TB SSD"}]}


def docs(jp_products=None, global_products=None):
    return {
        NEC_NEW_URL: "<h2>Mate type MC</h2><p>PC-M1X50CZGM Intel Core Ultra 7 155H 32GB 1TB Windows 11</p>",
        EPSON_CATALOGUE_URL: "%PDF fake catalogue bytes ST60E",
        EPSON_PRESS_URL: "<article>Endeavor ST60E Intel Core i5-1335U 発表</article>",
        MOUSEPRO_CR_URL: "<h2>MousePro CR-I5U01</h2><p>Intel Core i5-1235U 16GB RAM 512GB SSD</p>",
        THIRDWAVE_HG_URL: "<h2>THIRDWAVE HG3024</h2><p>Intel Core i5-1235U 32GB 1TB Windows 11</p>",
        GEEKOM_JP_PRODUCTS_URL: json.dumps({"products": jp_products or [
            geekom("GEEKOM A9 Max Mini PC", "a9-max", "AMD Ryzen AI 9 HX 370"),
        ]}),
        GEEKOM_GLOBAL_PRODUCTS_URL.format(page=1): json.dumps(global_products or [{
            "name": "GEEKOM A9 Max Mini PC AMD Ryzen AI 9 HX 370", "short_description": "", "description": "",
        }]),
    }


def test_parsers_use_base_model_plus_platform_not_bto_options():
    nec = parse_nec_mate_new(docs()[NEC_NEW_URL])
    mouse = parse_mousepro_cr(docs()[MOUSEPRO_CR_URL])
    thirdwave = parse_thirdwave_hg(docs()[THIRDWAVE_HG_URL])
    epson = parse_epson_press(docs()[EPSON_PRESS_URL])
    assert [x.model for x in nec] == ["Mate Type MC (PC-M1X50CZGM)"]
    assert [x.model for x in mouse] == ["MousePro CR-I5U01"]
    assert [x.model for x in thirdwave] == ["THIRDWAVE HG3024"]
    assert [x.model for x in epson] == ["Endeavor ST60E"]
    assert all("32GB" not in x.identity_key and "1TB" not in x.identity_key for x in nec + mouse + thirdwave + epson)


def test_geekom_jp_identity_is_shopify_id_independent_and_global_comparable():
    jp = parse_geekom_jp_products(docs()[GEEKOM_JP_PRODUCTS_URL])
    global_keys = parse_geekom_global_products(docs()[GEEKOM_GLOBAL_PRODUCTS_URL.format(page=1)])
    assert len(jp) == 1
    assert jp[0].identity_key in global_keys
    assert "shopify" not in jp[0].identity_key.lower()


def test_first_pass_baselines_all_five_without_candidates(tmp_path):
    store = ExperimentalJapanMiniStore(str(tmp_path / "jp.db"))
    result = JapanMiniProbeCollector(store).run(Fetch(docs()), NOW)
    assert result.baseline_identities == 5
    assert result.candidates == 0
    assert store.db.execute("SELECT COUNT(*) FROM japan_mini_candidates").fetchone()[0] == 0
    assert store.db.execute("SELECT COUNT(*) FROM japan_mini_identities").fetchone()[0] == 5
    store.close()


def test_second_pass_emits_only_a_new_base_model_platform(tmp_path):
    store = ExperimentalJapanMiniStore(str(tmp_path / "jp.db"))
    c = JapanMiniProbeCollector(store)
    c.run(Fetch(docs()), NOW)
    d = docs()
    d[MOUSEPRO_CR_URL] = (
        "MousePro CR-I5U01 Intel Core i5-1235U 16GB RAM 512GB SSD "
        "MousePro CR-I7U02 Intel Core i7-1360P 64GB RAM 2TB SSD Windows 11"
    )
    result = c.run(Fetch(d), NOW)
    rows = store.db.execute("SELECT source, model FROM japan_mini_candidates").fetchall()
    assert result.candidates == 1
    assert [(r[0], r[1]) for r in rows] == [("mousepro_cr", "MousePro CR-I7U02")]
    store.close()


def test_geekom_duplicate_global_is_recorded_but_not_a_japan_unique_candidate(tmp_path):
    store = ExperimentalJapanMiniStore(str(tmp_path / "jp.db"))
    result = JapanMiniProbeCollector(store).run(Fetch(docs()), NOW)
    row = store.db.execute(
        "SELECT global_overlap FROM japan_mini_identities WHERE source='geekom_jp'"
    ).fetchone()
    assert result.global_duplicates == 1
    assert row[0] == "duplicate_global"
    store.close()


def test_geekom_platform_delta_is_not_suppressed_by_model_only_overlap(tmp_path):
    store = ExperimentalJapanMiniStore(str(tmp_path / "jp.db"))
    d = docs(
        [geekom("GEEKOM A9 Max Mini PC", "a9-max", "AMD Ryzen AI 9 HX 470")],
        [{"name": "GEEKOM A9 Max Mini PC", "short_description": "", "description": ""}],
    )
    JapanMiniProbeCollector(store).run(Fetch(d), NOW)
    row = store.db.execute(
        "SELECT global_overlap FROM japan_mini_identities WHERE source='geekom_jp'"
    ).fetchone()
    assert row[0] == "global_model_overlap"
    store.close()


def test_partial_catalogue_does_not_replace_successful_baseline(tmp_path):
    store = ExperimentalJapanMiniStore(str(tmp_path / "jp.db"))
    c = JapanMiniProbeCollector(store)
    many = docs()
    many[MOUSEPRO_CR_URL] = " ".join(
        f"MousePro CR-I{i}U0{i} Intel Core i5-1235U" for i in range(1, 10)
    )
    c.run(Fetch(many), NOW)
    result = c.run(Fetch(docs()), NOW)
    assert any("mousepro_cr" in failure for failure in result.failures)
    assert store.previous_count("mousepro_cr") == 9
    store.close()


def test_experiment_store_has_no_production_tables(tmp_path):
    store = ExperimentalJapanMiniStore(str(tmp_path / "jp.db"))
    names = {r[0] for r in store.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert names == {"japan_mini_runs", "japan_mini_identities", "japan_mini_candidates", "japan_mini_artifacts"}
    store.close()

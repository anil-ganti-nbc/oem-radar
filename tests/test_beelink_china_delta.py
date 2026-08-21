import json
from datetime import datetime, timezone

from oem_radar.core.models import FetchedDocument
from oem_radar.experimental.beelink_china_delta import (
    BeelinkChinaCategory,
    BeelinkChinaDeltaCollector,
    ExperimentalBeelinkChinaStore,
    parse_catalog,
)

CAT = BeelinkChinaCategory(code="ME", cid="84", label="ME series", api_url="https://x/ajaxdata?cid=84")


def api(*products):
    return json.dumps({"status": "success", "data": list(products)})


def product(pid, spu="ME Pro", title="ME Pro", configs=None):
    return {
        "id": pid, "spu": spu, "title": title,
        "detailUrl": f"https://www.bee-link.com.cn/catalog/product/index?id={pid}",
        "configurations": configs if configs is not None else [
            {"id": pid, "CPU": "N150", "RAM": "16G", "Storage": "512G", "price": "￥609"}
        ],
    }


class Fetch:
    def __init__(self, body_by_url):
        self.body_by_url = body_by_url
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        return FetchedDocument(url=url, status=200, body=self.body_by_url[url])


NOW = datetime(2026, 8, 12, 18, 0, tzinfo=timezone.utc)


def test_1_initial_pass_baselines_silently(tmp_path):
    s = ExperimentalBeelinkChinaStore(str(tmp_path / "e.db"))
    f = Fetch({CAT.api_url: api(product("1294", "ME Pro N95"))})
    r = BeelinkChinaDeltaCollector(s, (CAT,)).run(f, NOW)
    assert r.baseline_products == 1
    assert r.valid_candidates == 0
    assert s.db.execute("SELECT COUNT(*) FROM beelink_cn_candidates").fetchone()[0] == 0
    s.close()


def test_2_repeated_unchanged_pass_emits_nothing(tmp_path):
    s = ExperimentalBeelinkChinaStore(str(tmp_path / "e.db"))
    f = Fetch({CAT.api_url: api(product("1294", "ME Pro N95"))})
    c = BeelinkChinaDeltaCollector(s, (CAT,))
    c.run(f, NOW)
    r = c.run(f, NOW)
    assert r.new_products == 0 and r.new_configurations == 0 and r.valid_candidates == 0
    s.close()


def test_3_new_product_after_baseline(tmp_path):
    s = ExperimentalBeelinkChinaStore(str(tmp_path / "e.db"))
    c = BeelinkChinaDeltaCollector(s, (CAT,))
    c.run(Fetch({CAT.api_url: api(product("1294", "ME Pro N95"))}), NOW)
    r = c.run(Fetch({CAT.api_url: api(
        product("1294", "ME Pro N95"),
        product("1999", "ME Pro HX470", configs=[
            {"id": "1999", "CPU": "AI9 HX 470", "RAM": "32G", "Storage": "1TB", "price": "￥4795"}
        ]),
    )}), NOW)
    assert r.new_products == 1 and r.valid_candidates == 1
    row = s.db.execute("SELECT candidate_type, cpu FROM beelink_cn_candidates").fetchone()
    assert row[0] == "NEW_CHINA_PRODUCT" and row[1] == "AI9 HX 470"
    s.close()


def test_4_new_configuration_after_baseline(tmp_path):
    s = ExperimentalBeelinkChinaStore(str(tmp_path / "e.db"))
    c = BeelinkChinaDeltaCollector(s, (CAT,))
    c.run(Fetch({CAT.api_url: api(product("1352", "SER10 MAX HX470", configs=[
        {"id": "1352", "CPU": "AI9 HX 470", "RAM": "0GB", "Storage": "0GB", "price": "￥4599"},
    ]))}), NOW)
    r = c.run(Fetch({CAT.api_url: api(product("1352", "SER10 MAX HX470", configs=[
        {"id": "1352", "CPU": "AI9 HX 470", "RAM": "0GB", "Storage": "0GB", "price": "￥4599"},
        {"id": "1354", "CPU": "AI9 HX 470", "RAM": "32G", "Storage": "1TB", "price": "￥8259"},
    ]))}), NOW)
    assert r.new_configurations == 1 and r.valid_candidates == 1
    assert s.db.execute("SELECT candidate_type FROM beelink_cn_candidates").fetchone()[0] == "NEW_CHINA_CONFIGURATION"
    s.close()


def test_5_existing_global_identity_marks_presence_yes(tmp_path):
    s = ExperimentalBeelinkChinaStore(str(tmp_path / "e.db"))
    c = BeelinkChinaDeltaCollector(s, (CAT,), known_global_identity_tokens=frozenset({"HX470", "N150"}))
    c.run(Fetch({CAT.api_url: api(product("1294", "ME Pro N95"))}), NOW)
    r = c.run(Fetch({CAT.api_url: api(
        product("1294", "ME Pro N95"),
        product("1999", "ME Pro HX470", configs=[{"id": "1999", "CPU": "AI9 HX 470", "RAM": "", "Storage": "", "price": ""}]),
    )}), NOW)
    assert r.valid_candidates == 1
    assert s.db.execute("SELECT global_source_presence FROM beelink_cn_candidates").fetchone()[0] == "yes"
    s.close()


def test_6_china_only_identity_marks_presence_no(tmp_path):
    s = ExperimentalBeelinkChinaStore(str(tmp_path / "e.db"))
    c = BeelinkChinaDeltaCollector(s, (CAT,), known_global_identity_tokens=frozenset({"N150"}))
    c.run(Fetch({CAT.api_url: api(product("1294", "ME Pro N95"))}), NOW)
    r = c.run(Fetch({CAT.api_url: api(
        product("1294", "ME Pro N95"),
        product("1999", "ME Pro China Exclusive", configs=[{"id": "1999", "CPU": "N200", "RAM": "", "Storage": "", "price": ""}]),
    )}), NOW)
    assert r.valid_candidates == 1
    assert s.db.execute("SELECT global_source_presence FROM beelink_cn_candidates").fetchone()[0] == "no"
    s.close()


def test_7_second_pass_does_not_reemit_same_candidate(tmp_path):
    s = ExperimentalBeelinkChinaStore(str(tmp_path / "e.db"))
    c = BeelinkChinaDeltaCollector(s, (CAT,))
    c.run(Fetch({CAT.api_url: api(product("1294", "ME Pro N95"))}), NOW)
    body_with_new = api(product("1294", "ME Pro N95"), product("1999", "ME Pro HX470"))
    c.run(Fetch({CAT.api_url: body_with_new}), NOW)
    r = c.run(Fetch({CAT.api_url: body_with_new}), NOW)
    assert r.new_products == 0 and r.valid_candidates == 0
    assert s.db.execute("SELECT COUNT(*) FROM beelink_cn_candidates").fetchone()[0] == 1
    s.close()


def test_8_partial_source_failure_does_not_replace_baseline(tmp_path):
    s = ExperimentalBeelinkChinaStore(str(tmp_path / "e.db"))
    c = BeelinkChinaDeltaCollector(s, (CAT,))
    c.run(Fetch({CAT.api_url: api(*(product(str(i)) for i in range(10)))}), NOW)
    r = c.run(Fetch({CAT.api_url: api(product("0"))}), NOW)
    assert r.failures and s.previous_count("ME") == 10
    s.close()


def test_9_empty_source_failure(tmp_path):
    s = ExperimentalBeelinkChinaStore(str(tmp_path / "e.db"))
    c = BeelinkChinaDeltaCollector(s, (CAT,))
    c.run(Fetch({CAT.api_url: api(product("1294"))}), NOW)
    r = c.run(Fetch({CAT.api_url: api()}), NOW)
    assert r.failures and s.previous_count("ME") == 1
    s.close()


def test_10_malformed_product_identity_is_skipped():
    parsed = parse_catalog(api({"spu": "no id here", "configurations": []}, product("1294")))
    assert len(parsed) == 1 and parsed[0]["product_id"] == "1294"


def test_11_missing_sku_falls_back_to_parent_id():
    body = api(product("1294", configs=[{"CPU": "N95", "RAM": "8G", "Storage": "256G", "price": "￥499"}]))
    parsed = parse_catalog(body)
    assert parsed[0]["configurations"][0]["config_id"] == "1294"


def test_12_candidate_dedup_key_is_unique_across_runs(tmp_path):
    s = ExperimentalBeelinkChinaStore(str(tmp_path / "e.db"))
    c = BeelinkChinaDeltaCollector(s, (CAT,))
    c.run(Fetch({CAT.api_url: api(product("1294"))}), NOW)
    c.run(Fetch({CAT.api_url: api(product("1294"), product("1999"))}), NOW)
    # Re-running with the same "new" product again must not raise or duplicate --
    # store already treats 1999 as known, so this exercises INSERT OR IGNORE safety
    # even if a bug ever caused a duplicate NEW_CHINA_PRODUCT candidate to be built.
    s.db.execute(
        "INSERT OR IGNORE INTO beelink_cn_candidates(category,candidate_type,product_id,config_id,spu,title,cpu,"
        "detail_url,global_source_presence,novelty_reason,dedup_key,first_observed_at) "
        "VALUES('ME','NEW_CHINA_PRODUCT','1999',NULL,'x','x','x','x','unknown','x','ME:NEW_CHINA_PRODUCT:1999','now')"
    )
    s.db.commit()
    assert s.db.execute("SELECT COUNT(*) FROM beelink_cn_candidates").fetchone()[0] == 1
    s.close()


def test_baseline_and_delta_never_touch_production_tables(tmp_path):
    s = ExperimentalBeelinkChinaStore(str(tmp_path / "e.db"))
    tables = {r[0] for r in s.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert tables == {
        "beelink_cn_runs", "beelink_cn_products", "beelink_cn_configurations", "beelink_cn_candidates",
    }
    s.close()

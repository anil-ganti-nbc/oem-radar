import json
from datetime import datetime, timezone

from oem_radar.core.models import FetchedDocument
from oem_radar.experimental.japan_mini_pc import GEEKOM_GLOBAL_PRODUCTS_URL, GEEKOM_JP_PRODUCTS_URL, MOUSEPRO_CR_URL
from oem_radar.experimental.japan_mini_pc_soak import (
    GLOBAL_DUPLICATE, NEW_HARDWARE, REGIONAL_VARIANT, JapanMiniPcSoak, JapanMiniPcSoakStore,
)


class Fetch:
    def __init__(self, docs):
        self.docs, self.stats = docs, {"requests": 0, "cache_hits_304": 0}
    def get(self, url):
        self.stats["requests"] += 1
        return FetchedDocument(url=url, status=200, body=self.docs[url])


def product(title, handle, cpu):
    return {"title": title, "handle": handle, "body_html": "", "variants": [{"option1": cpu}]}


def docs(mouse, jp, global_):
    return {
        MOUSEPRO_CR_URL: mouse,
        GEEKOM_JP_PRODUCTS_URL: json.dumps({"products": jp}),
        GEEKOM_GLOBAL_PRODUCTS_URL.format(page=1): json.dumps(global_),
    }


def empty_history(tmp_path):
    path = tmp_path / "history.db"
    import sqlite3
    db = sqlite3.connect(path)
    db.executescript("CREATE TABLE sources(id INTEGER PRIMARY KEY, source_key TEXT); CREATE TABLE products(id INTEGER PRIMARY KEY, canonical_model TEXT); CREATE TABLE listings(source_id INTEGER, product_id INTEGER, vendor_handle TEXT);")
    db.commit(); db.close()
    return path


def test_baseline_is_quiet_and_persists_first_seen(tmp_path):
    history = empty_history(tmp_path)
    store = JapanMiniPcSoakStore(str(tmp_path / "soak.db"))
    r = JapanMiniPcSoak(store, history).run(Fetch(docs(
        "MousePro CR-I5U01 Intel Core i5-1235U", [product("GEEKOM A9 Max", "a9", "AMD Ryzen AI 9 HX 370")],
        [{"name": "GEEKOM A9 Max AMD Ryzen AI 9 HX 370"}],
    )), datetime(2026, 8, 31, tzinfo=timezone.utc))
    assert r.baselined == 2 and r.new_identities == 0 and r.http_requests == 3
    assert store.db.execute("SELECT COUNT(*) FROM jp_mini_soak_observations").fetchone()[0] == 0
    assert store.db.execute("SELECT first_seen_at FROM jp_mini_soak_identities").fetchone()[0]
    store.close()


def test_new_mouse_and_geekom_are_classified_after_baseline(tmp_path):
    history = empty_history(tmp_path)
    store = JapanMiniPcSoakStore(str(tmp_path / "soak.db"))
    soak = JapanMiniPcSoak(store, history)
    base = docs("MousePro CR-I5U01 Intel Core i5-1235U", [product("GEEKOM A9 Max", "a9", "AMD Ryzen AI 9 HX 370")], [{"name": "GEEKOM A9 Max AMD Ryzen AI 9 HX 370"}])
    soak.run(Fetch(base), datetime(2026, 8, 31, tzinfo=timezone.utc))
    changed = docs(
        "MousePro CR-I5U01 Intel Core i5-1235U MousePro CR-I7U02 Intel Core i7-1360P",
        [product("GEEKOM A9 Max", "a9", "AMD Ryzen AI 9 HX 370"), product("GEEKOM GT13 Max", "gt13", "Intel Core Ultra 9 185H")],
        [{"name": "GEEKOM A9 Max AMD Ryzen AI 9 HX 370"}, {"name": "GEEKOM GT13 Max"}],
    )
    r = soak.run(Fetch(changed), datetime(2026, 9, 1, tzinfo=timezone.utc))
    rows = {row[0]: row[1] for row in store.db.execute("SELECT source,classification FROM jp_mini_soak_observations")}
    assert r.new_identities == 2
    assert rows["mousepro_cr"] == NEW_HARDWARE
    assert rows["geekom_jp"] == REGIONAL_VARIANT
    store.close()


def test_geekom_exact_global_duplicate_is_retained_as_classified_observation(tmp_path):
    history = empty_history(tmp_path)
    store = JapanMiniPcSoakStore(str(tmp_path / "soak.db"))
    soak = JapanMiniPcSoak(store, history)
    base = docs("MousePro CR-I5U01 Intel Core i5-1235U", [product("GEEKOM A9 Max", "a9", "AMD Ryzen AI 9 HX 370")], [{"name": "GEEKOM A9 Max AMD Ryzen AI 9 HX 370"}])
    soak.run(Fetch(base), datetime(2026, 8, 31, tzinfo=timezone.utc))
    changed = docs("MousePro CR-I5U01 Intel Core i5-1235U", [product("GEEKOM A9 Max", "a9", "AMD Ryzen AI 9 HX 370"), product("GEEKOM IT15", "it15", "Intel Core Ultra 9 285H")], [{"name": "GEEKOM A9 Max AMD Ryzen AI 9 HX 370"}, {"name": "GEEKOM IT15 Intel Core Ultra 9 285H"}])
    soak.run(Fetch(changed), datetime(2026, 9, 1, tzinfo=timezone.utc))
    assert store.db.execute("SELECT classification FROM jp_mini_soak_observations WHERE source='geekom_jp'").fetchone()[0] == GLOBAL_DUPLICATE
    store.close()

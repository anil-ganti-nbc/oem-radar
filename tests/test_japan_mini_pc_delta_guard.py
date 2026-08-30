import json
from datetime import datetime, timezone

from oem_radar.core.models import FetchedDocument
from oem_radar.experimental.japan_mini_pc import (
    EPSON_PRESS_URL,
    GEEKOM_GLOBAL_PRODUCTS_URL,
    GEEKOM_JP_PRODUCTS_URL,
    MOUSEPRO_CR_URL,
    NEC_NEW_URL,
    THIRDWAVE_HG_URL,
    ExperimentalJapanMiniStore,
    JapanMiniProbeCollector,
)


class Fetch:
    def __init__(self, docs):
        self.docs = docs

    def get(self, url):
        return FetchedDocument(url=url, status=200, body=self.docs[url])


def product(title, handle, cpu):
    return {"title": title, "handle": handle, "body_html": "",
            "variants": [{"option1": cpu}]}


def documents(jp):
    return {
        NEC_NEW_URL: "Mate type MC Intel Core i5-1235U",
        EPSON_PRESS_URL: "Endeavor ST60E Intel Core i5-1335U",
        MOUSEPRO_CR_URL: "MousePro CR-I5U01 Intel Core i5-1235U",
        THIRDWAVE_HG_URL: "THIRDWAVE HG3024 Intel Core i5-1235U",
        GEEKOM_JP_PRODUCTS_URL: json.dumps({"products": jp}),
        GEEKOM_GLOBAL_PRODUCTS_URL.format(page=1): json.dumps([
            {"name": "GEEKOM A9 Max Mini PC", "short_description": "", "description": ""},
            {"name": "GEEKOM GT13 Max Mini PC", "short_description": "", "description": ""},
        ]),
    }


def test_geekom_global_model_overlap_is_never_emitted_as_a_jp_delta(tmp_path):
    store = ExperimentalJapanMiniStore(str(tmp_path / "jp.db"))
    collector = JapanMiniProbeCollector(store)
    now = datetime(2026, 8, 31, tzinfo=timezone.utc)
    collector.run(Fetch(documents([product("GEEKOM A9 Max", "a9", "AMD Ryzen AI 9 HX 370")])), now)
    result = collector.run(Fetch(documents([
        product("GEEKOM A9 Max", "a9", "AMD Ryzen AI 9 HX 370"),
        product("GEEKOM GT13 Max", "gt13", "Intel Core Ultra 9 185H"),
    ])), now)
    assert result.new_identities == 1
    assert result.candidates == 0
    assert store.db.execute("SELECT COUNT(*) FROM japan_mini_candidates").fetchone()[0] == 0
    store.close()

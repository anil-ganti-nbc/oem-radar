"""Isolated Beelink China (bee-link.com.cn) baseline/delta collector.

Reconnaissance basis: the "BEELINK CHINA PROOF-OF-CONCEPT" investigation
(2026-08-12), triggered by the ME Pro Ryzen AI 9 HX 470 live miss. That
investigation found that bee-link.com.cn exposes a first-party,
unauthenticated JSON catalogue API --
``/catalog/category/ajaxdata?cid=<series>`` -- with numeric product/config
identity, honestly reachable with a plain GET (no auth, no CAPTCHA, no
sitemap to lean on: bee-link.com.cn's sitemap.xml resolves 200 but is
empty). No field anywhere on this API can be trusted as a launch or
publication timestamp (verified during recon: the only date-shaped value is
a CDN image-filename epoch, which is an upload/edit time, not a launch
time). Because of that, this collector uses the BASELINE -> DELTA model,
not a timestamped-feed model.

The collector owns an isolated SQLite file; it never receives the normal
SnapshotStore, notifier, or health counters, and is never imported by
src/oem_radar/core/runner.py or wired into production run_all.

Scope is intentionally narrow: only the ME series (cid=84 -- the NAS / ME
mini family implicated in the incident) is polled. Other series (GT/SE/EQ)
use the same API shape and could be added later, but this module does not
generalize to them yet -- see docs/BEELINK_CHINA_POC.md.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class BeelinkChinaCategory:
    code: str
    cid: str
    label: str
    api_url: str


# The product family implicated in the ME Pro HX 470 miss. DO NOT
# GENERALIZE to the rest of the Beelink China catalogue in this module --
# that is future, separately-scoped work.
ME_SERIES = BeelinkChinaCategory(
    code="ME",
    cid="84",
    label="ME series (NAS / ME mini)",
    api_url="https://www.bee-link.com.cn/catalog/category/ajaxdata?cid=84",
)

DEFAULT_CATEGORIES = (ME_SERIES,)


def _safe_str(value) -> str:
    return "" if value is None else str(value)


def parse_catalog(body: str) -> list[dict]:
    """Parse one ajaxdata response into normalized product records.

    Identity: the spu-level ``id`` for the product family, and the
    config-level ``id`` inside ``configurations[]`` for each SKU/CPU
    variant. Neither the URL nor the free-text Chinese title/spu string is
    used as identity -- both are cosmetic and have been observed to be
    inconsistent (e.g. "...-clone-1" suffixes on some spu strings).
    """
    data = json.loads(body)
    if data.get("status") != "success":
        raise ValueError(f"unexpected API status: {data.get('status')!r}")
    products = []
    for raw in data.get("data") or []:
        pid = raw.get("id")
        if not pid:
            continue  # malformed product identity: no numeric id, unusable
        configs = []
        for craw in raw.get("configurations") or []:
            cid = craw.get("id") or pid  # missing SKU fallback: parent id
            configs.append({
                "config_id": _safe_str(cid),
                "cpu": _safe_str(craw.get("CPU")),
                "ram": _safe_str(craw.get("RAM")),
                "storage": _safe_str(craw.get("Storage")),
                "price": _safe_str(craw.get("price")),
            })
        products.append({
            "product_id": _safe_str(pid),
            "spu": _safe_str(raw.get("spu")),
            "title": _safe_str(raw.get("title")),
            "detail_url": _safe_str(raw.get("detailUrl")),
            "configurations": configs,
        })
    return products


class ExperimentalBeelinkChinaStore:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS beelink_cn_runs(
          id INTEGER PRIMARY KEY, category TEXT NOT NULL, started_at TEXT NOT NULL,
          status TEXT NOT NULL, product_count INTEGER NOT NULL DEFAULT 0, error TEXT);
        CREATE TABLE IF NOT EXISTS beelink_cn_products(
          category TEXT NOT NULL, product_id TEXT NOT NULL, spu TEXT, title TEXT,
          detail_url TEXT, first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
          PRIMARY KEY(category, product_id));
        CREATE TABLE IF NOT EXISTS beelink_cn_configurations(
          category TEXT NOT NULL, product_id TEXT NOT NULL, config_id TEXT NOT NULL,
          cpu TEXT, ram TEXT, storage TEXT, first_seen_at TEXT NOT NULL,
          last_seen_at TEXT NOT NULL, PRIMARY KEY(category, config_id));
        CREATE TABLE IF NOT EXISTS beelink_cn_candidates(
          id INTEGER PRIMARY KEY, category TEXT NOT NULL, candidate_type TEXT NOT NULL,
          product_id TEXT NOT NULL, config_id TEXT, spu TEXT, title TEXT, cpu TEXT,
          detail_url TEXT, global_source_presence TEXT NOT NULL,
          novelty_reason TEXT NOT NULL, dedup_key TEXT NOT NULL,
          first_observed_at TEXT NOT NULL, UNIQUE(dedup_key));
        """)
        self.db.commit()

    def previous_count(self, category: str) -> int | None:
        row = self.db.execute(
            "SELECT product_count FROM beelink_cn_runs WHERE category=? AND status='ok' "
            "ORDER BY id DESC LIMIT 1", (category,)).fetchone()
        return None if row is None else row[0]

    def known_product_ids(self, category: str) -> set[str]:
        return {r[0] for r in self.db.execute(
            "SELECT product_id FROM beelink_cn_products WHERE category=?", (category,))}

    def known_config_ids(self, category: str) -> set[str]:
        return {r[0] for r in self.db.execute(
            "SELECT config_id FROM beelink_cn_configurations WHERE category=?", (category,))}

    def save_success(self, category: str, products: list[dict], candidates: list[dict], now: str) -> None:
        for p in products:
            self.db.execute(
                "INSERT INTO beelink_cn_products(category,product_id,spu,title,detail_url,first_seen_at,last_seen_at) "
                "VALUES(?,?,?,?,?,?,?) ON CONFLICT(category,product_id) DO UPDATE SET "
                "last_seen_at=excluded.last_seen_at",
                (category, p["product_id"], p["spu"], p["title"], p["detail_url"], now, now))
            for c in p["configurations"]:
                self.db.execute(
                    "INSERT INTO beelink_cn_configurations(category,product_id,config_id,cpu,ram,storage,first_seen_at,last_seen_at) "
                    "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(category,config_id) DO UPDATE SET "
                    "last_seen_at=excluded.last_seen_at",
                    (category, p["product_id"], c["config_id"], c["cpu"], c["ram"], c["storage"], now, now))
        for cand in candidates:
            self.db.execute(
                "INSERT OR IGNORE INTO beelink_cn_candidates(category,candidate_type,product_id,config_id,spu,"
                "title,cpu,detail_url,global_source_presence,novelty_reason,dedup_key,first_observed_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (category, cand["candidate_type"], cand["product_id"], cand.get("config_id"), cand.get("spu"),
                 cand.get("title"), cand.get("cpu"), cand.get("detail_url"), cand["global_source_presence"],
                 cand["novelty_reason"], cand["dedup_key"], now))
        self.db.execute(
            "INSERT INTO beelink_cn_runs(category,started_at,status,product_count) VALUES(?,?, 'ok',?)",
            (category, now, len(products)))
        self.db.commit()

    def save_failure(self, category: str, now: str, error: str) -> None:
        self.db.execute(
            "INSERT INTO beelink_cn_runs(category,started_at,status,error) VALUES(?,?, 'failed',?)",
            (category, now, error))
        self.db.commit()

    def close(self):
        self.db.close()


@dataclass
class DeltaStats:
    categories_polled: int = 0
    baseline_products: int = 0
    new_products: int = 0
    new_configurations: int = 0
    valid_candidates: int = 0
    failures: list[str] = field(default_factory=list)


class BeelinkChinaDeltaCollector:
    """BASELINE -> DELTA collector, mirroring the safety shape of
    LenovoRegionalSitemapDeltaCollector: never replaces a healthy baseline
    with a partial/empty run, never fetches a second endpoint per candidate
    (unlike Lenovo, the catalogue API already returns full product+config
    detail -- no per-URL follow-up fetch is needed or performed).
    """

    def __init__(self, store: ExperimentalBeelinkChinaStore, categories=DEFAULT_CATEGORIES,
                 minimum_fraction: float = .35, known_global_identity_tokens: frozenset[str] = frozenset()):
        self.store = store
        self.categories = tuple(categories)
        self.minimum_fraction = minimum_fraction
        # Best-effort corroboration only (Phase 9: "existing global Beelink
        # identity should be used for corroboration where safe"). Never used
        # to merge or suppress a China candidate's identity -- only to
        # annotate global_source_presence on the emitted candidate.
        self._known_global_tokens = {t.upper().replace(" ", "").replace("-", "") for t in known_global_identity_tokens}

    def _global_presence(self, cpu: str) -> str:
        if not self._known_global_tokens:
            return "unknown"
        token = cpu.upper().replace(" ", "").replace("-", "")
        if not token:
            return "unknown"
        return "yes" if any(token in g or g in token for g in self._known_global_tokens) else "no"

    def run(self, fetcher, now: datetime | None = None) -> DeltaStats:
        now = now or datetime.now(timezone.utc)
        stamp = now.isoformat()
        stats = DeltaStats()
        for cat in self.categories:
            stats.categories_polled += 1
            try:
                doc = fetcher.get(cat.api_url)
                products = parse_catalog(doc.body)
                previous = self.store.previous_count(cat.code)
                if not products or (previous and len(products) / previous < self.minimum_fraction):
                    raise ValueError(f"unsafe product count {len(products)} (previous={previous})")

                if previous is None:
                    stats.baseline_products += len(products)
                    self.store.save_success(cat.code, products, [], stamp)
                    continue

                known_products = self.store.known_product_ids(cat.code)
                known_configs = self.store.known_config_ids(cat.code)
                candidates = []
                for p in products:
                    if p["product_id"] not in known_products:
                        stats.new_products += 1
                        primary_cpu = p["configurations"][0]["cpu"] if p["configurations"] else ""
                        candidates.append({
                            "candidate_type": "NEW_CHINA_PRODUCT",
                            "product_id": p["product_id"], "config_id": None, "spu": p["spu"],
                            "title": p["title"], "cpu": primary_cpu, "detail_url": p["detail_url"],
                            "global_source_presence": self._global_presence(primary_cpu),
                            "novelty_reason": "product_id_not_previously_seen_in_china_catalogue",
                            "dedup_key": f"{cat.code}:NEW_CHINA_PRODUCT:{p['product_id']}",
                        })
                        stats.valid_candidates += 1
                        continue
                    for c in p["configurations"]:
                        if c["config_id"] not in known_configs:
                            stats.new_configurations += 1
                            candidates.append({
                                "candidate_type": "NEW_CHINA_CONFIGURATION",
                                "product_id": p["product_id"], "config_id": c["config_id"], "spu": p["spu"],
                                "title": p["title"], "cpu": c["cpu"], "detail_url": p["detail_url"],
                                "global_source_presence": self._global_presence(c["cpu"]),
                                "novelty_reason": "config_id_not_previously_seen_under_known_product",
                                "dedup_key": f"{cat.code}:NEW_CHINA_CONFIGURATION:{c['config_id']}",
                            })
                            stats.valid_candidates += 1
                self.store.save_success(cat.code, products, candidates, stamp)
            except Exception as exc:
                stats.failures.append(f"{cat.code}: {exc!r}")
                self.store.save_failure(cat.code, stamp, str(exc))
        return stats

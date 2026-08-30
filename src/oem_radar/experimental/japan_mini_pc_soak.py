"""Five-day, local-only Japan mini-PC soak: MousePro CR and GEEKOM JP.

This is intentionally separate from the production runner, notifications and
the earlier multi-source feasibility probe.  ``radar.db`` is opened read-only
solely to enrich the GEEKOM global comparison; all mutable state lives in the
experiment database passed to :class:`JapanMiniPcSoak`.
"""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .japan_mini_pc import (
    GEEKOM_GLOBAL_PRODUCTS_URL,
    GEEKOM_JP_PRODUCTS_URL,
    MOUSEPRO_CR_URL,
    JapanIdentity,
    geekom_model_key,
    global_geekom_model_keys_from_db,
    parse_geekom_global_products,
    parse_geekom_jp_products,
    parse_mousepro_cr,
)

NEW_HARDWARE = "NEW_HARDWARE"
GLOBAL_DUPLICATE = "GLOBAL_DUPLICATE"
REGIONAL_VARIANT = "REGIONAL_VARIANT"
LEGACY = "LEGACY"
UNKNOWN = "UNKNOWN"


def _legacy_geekom(item: JapanIdentity) -> bool:
    """Conservative legacy bucket: old Intel generations / named old families.

    It is deliberately narrower than “not current”: anything not clearly old
    remains UNKNOWN rather than being silently discarded.
    """
    value = f"{item.model} {item.platform or ''}".upper()
    return any(token in value for token in (
        "IT11", "MINI AIR11", "MEGAMINI G1", "GT12", "XT12", "I9-13900", "I7-11390",
    ))


def classify_mousepro(item: JapanIdentity) -> str:
    # A new CR base model with an explicit CPU/platform is a new hardware
    # candidate.  If the storefront card omits the CPU, retain it for review
    # rather than inferring specs from RAM/SSD/OS configuration text.
    return NEW_HARDWARE if item.platform else UNKNOWN


def classify_geekom(item: JapanIdentity, global_keys: set[str], global_models: set[str]) -> str:
    if item.identity_key in global_keys:
        return GLOBAL_DUPLICATE
    if geekom_model_key(item.identity_key) in global_models:
        return REGIONAL_VARIANT
    if _legacy_geekom(item):
        return LEGACY
    return UNKNOWN


@dataclass
class SoakStats:
    run_started_at: str
    runtime_ms: int = 0
    documents: int = 0
    http_requests: int = 0
    cache_hits_304: int = 0
    baselined: int = 0
    new_identities: int = 0
    classifications: dict[str, int] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)


class JapanMiniPcSoakStore:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS jp_mini_soak_runs(
          id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT NOT NULL,
          status TEXT NOT NULL, runtime_ms INTEGER NOT NULL, documents INTEGER NOT NULL,
          http_requests INTEGER NOT NULL, cache_hits_304 INTEGER NOT NULL,
          identities INTEGER NOT NULL, new_identities INTEGER NOT NULL, errors_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS jp_mini_soak_identities(
          source TEXT NOT NULL, identity_key TEXT NOT NULL, model TEXT NOT NULL,
          platform TEXT, source_url TEXT NOT NULL, first_seen_at TEXT NOT NULL,
          last_seen_at TEXT NOT NULL, PRIMARY KEY(source, identity_key));
        CREATE TABLE IF NOT EXISTS jp_mini_soak_observations(
          id INTEGER PRIMARY KEY, source TEXT NOT NULL, identity_key TEXT NOT NULL,
          classification TEXT NOT NULL, model TEXT NOT NULL, platform TEXT,
          source_url TEXT NOT NULL, first_seen_at TEXT NOT NULL,
          UNIQUE(source, identity_key));
        """)
        self.db.commit()

    def has_baseline(self) -> bool:
        return self.db.execute("SELECT 1 FROM jp_mini_soak_runs WHERE status='ok' LIMIT 1").fetchone() is not None

    def known(self, source: str) -> set[str]:
        return {r[0] for r in self.db.execute(
            "SELECT identity_key FROM jp_mini_soak_identities WHERE source=?", (source,))}

    def persist(self, items: list[JapanIdentity], new: list[tuple[JapanIdentity, str]], stats: SoakStats,
                finished_at: str) -> None:
        for item in items:
            self.db.execute(
                "INSERT INTO jp_mini_soak_identities(source,identity_key,model,platform,source_url,first_seen_at,last_seen_at) "
                "VALUES(?,?,?,?,?,?,?) ON CONFLICT(source,identity_key) DO UPDATE SET "
                "model=excluded.model,platform=excluded.platform,source_url=excluded.source_url,last_seen_at=excluded.last_seen_at",
                (item.source, item.identity_key, item.model, item.platform, item.url,
                 stats.run_started_at, finished_at),
            )
        for item, classification in new:
            self.db.execute(
                "INSERT OR IGNORE INTO jp_mini_soak_observations(source,identity_key,classification,model,platform,source_url,first_seen_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (item.source, item.identity_key, classification, item.model, item.platform,
                 item.url, stats.run_started_at),
            )
        status = "ok" if not stats.failures else "partial"
        self.db.execute(
            "INSERT INTO jp_mini_soak_runs(started_at,finished_at,status,runtime_ms,documents,http_requests,cache_hits_304,identities,new_identities,errors_json) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (stats.run_started_at, finished_at, status, stats.runtime_ms, stats.documents,
             stats.http_requests, stats.cache_hits_304, len(items), stats.new_identities,
             json.dumps(stats.failures)),
        )
        self.db.commit()

    def close(self) -> None:
        self.db.close()


class JapanMiniPcSoak:
    """One bounded pass.  No SourceConfig, SnapshotStore, or notifier enters here."""

    def __init__(self, store: JapanMiniPcSoakStore, global_history_db: str | Path):
        self.store = store
        self.global_history_db = global_history_db

    def run(self, fetcher, now: datetime | None = None) -> SoakStats:
        now = now or datetime.now(timezone.utc)
        started = now.isoformat()
        wall_start = time.perf_counter()
        stats = SoakStats(run_started_at=started)
        before = dict(getattr(fetcher, "stats", {}))
        items: list[JapanIdentity] = []
        new: list[tuple[JapanIdentity, str]] = []
        baseline = not self.store.has_baseline()

        try:
            body = fetcher.get(MOUSEPRO_CR_URL).body
            stats.documents += 1
            mouse = parse_mousepro_cr(body, MOUSEPRO_CR_URL)
            if not mouse:
                raise ValueError("unsafe zero MousePro CR identities")
            known = self.store.known("mousepro_cr")
            for item in mouse:
                if not baseline and item.identity_key not in known:
                    new.append((item, classify_mousepro(item)))
            items.extend(mouse)
        except Exception as exc:
            stats.failures.append(f"mousepro_cr: {exc!r}")

        try:
            jp_body = fetcher.get(GEEKOM_JP_PRODUCTS_URL).body
            stats.documents += 1
            global_keys: set[str] = set()
            for page in range(1, 4):
                body = fetcher.get(GEEKOM_GLOBAL_PRODUCTS_URL.format(page=page)).body
                stats.documents += 1
                parsed = json.loads(body)
                global_keys.update(parse_geekom_global_products(body))
                if not isinstance(parsed, list) or len(parsed) < 100:
                    break
            global_models = {geekom_model_key(key) for key in global_keys}
            # Required local, read-only comparison prevents a delisted global
            # model from falsely becoming a Japan-first candidate.
            global_models.update(global_geekom_model_keys_from_db(self.global_history_db))
            geekom = parse_geekom_jp_products(jp_body)
            if not geekom:
                raise ValueError("unsafe zero GEEKOM JP identities")
            known = self.store.known("geekom_jp")
            for item in geekom:
                if not baseline and item.identity_key not in known:
                    new.append((item, classify_geekom(item, global_keys, global_models)))
            items.extend(geekom)
        except Exception as exc:
            stats.failures.append(f"geekom_jp: {exc!r}")

        stats.runtime_ms = int((time.perf_counter() - wall_start) * 1000)
        after = getattr(fetcher, "stats", {})
        stats.http_requests = int(after.get("requests", 0)) - int(before.get("requests", 0))
        stats.cache_hits_304 = int(after.get("cache_hits_304", 0)) - int(before.get("cache_hits_304", 0))
        stats.baselined = len(items) if baseline else 0
        stats.new_identities = len(new)
        for _, classification in new:
            stats.classifications[classification] = stats.classifications.get(classification, 0) + 1
        self.store.persist(items, new, stats, datetime.now(timezone.utc).isoformat())
        return stats

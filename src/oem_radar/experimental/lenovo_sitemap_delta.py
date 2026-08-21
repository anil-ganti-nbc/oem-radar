"""Isolated regional Lenovo sitemap baseline/delta collector.

The collector owns an experimental SQLite file; it never receives the normal
SnapshotStore, notifier, health counters, or production configuration.
"""
from __future__ import annotations

import json
import re
import sqlite3
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
_PRODUCT_PATH = re.compile(r"/p/(?:laptops|desktops)/", re.I)
_JSONLD = re.compile(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.I | re.S)
_CANONICAL = re.compile(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)', re.I)


@dataclass(frozen=True)
class LenovoRegion:
    code: str
    locale: str
    sitemap_url: str


P0_REGIONS = (
    LenovoRegion("US", "us-en", "https://www.lenovo.com/sitemap-auto/089-intsitemap-us-en.xml"),
    LenovoRegion("CA", "ca-en", "https://www.lenovo.com/sitemap-auto/014-intsitemap-ca-en.xml"),
    LenovoRegion("UK", "gb-en", "https://www.lenovo.com/sitemap-auto/088-intsitemap-gb-en.xml"),
    LenovoRegion("AU", "au-en", "https://www.lenovo.com/sitemap-auto/004-intsitemap-au-en.xml"),
    LenovoRegion("SG", "sg-en", "https://www.lenovo.com/sitemap-auto/071-intsitemap-sg-en.xml"),
    LenovoRegion("HK", "hk-en", "https://www.lenovo.com/sitemap-auto/034-intsitemap-hk-en.xml"),
    LenovoRegion("MY", "my-en", "https://www.lenovo.com/sitemap-auto/051-intsitemap-my-en.xml"),
)


def normalize_url(url: str) -> str:
    p = urlsplit(url)
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/"), "", ""))


def product_urls(xml: str) -> set[str]:
    root = ET.fromstring(xml)
    return {normalize_url(x.text) for x in root.findall(".//sm:loc", _NS)
            if x.text and _PRODUCT_PATH.search(urlsplit(x.text).path)}


def url_identity(url: str) -> str:
    """Stable Lenovo URL tail is provisional identity until page metadata wins."""
    return "lenovo-url:" + urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1].lower()


def _walk(value):
    if isinstance(value, dict):
        yield value
        for x in value.values():
            yield from _walk(x)
    elif isinstance(value, list):
        for x in value:
            yield from _walk(x)


def extract_product_identity(html: str, url: str) -> dict | None:
    """Extract only explicit Product JSON-LD facts; no title guessing."""
    canonical = (_CANONICAL.search(html).group(1) if _CANONICAL.search(html) else url)
    for raw in _JSONLD.findall(html):
        try:
            data = json.loads(raw.strip())
        except json.JSONDecodeError:
            continue
        for obj in _walk(data):
            typ = obj.get("@type")
            if typ == "Product" or (isinstance(typ, list) and "Product" in typ):
                sku = obj.get("sku") or obj.get("mpn")
                offers = obj.get("offers") or {}
                if isinstance(offers, list):
                    offers = offers[0] if offers else {}
                return {
                    "model": obj.get("name"), "sku": sku,
                    "canonical_url": normalize_url(canonical),
                    "price": offers.get("price") if isinstance(offers, dict) else None,
                    "availability": offers.get("availability") if isinstance(offers, dict) else None,
                    "identity_key": "sku:" + str(sku).lower() if sku else url_identity(url),
                    "confidence": "high" if sku else "medium",
                }
    return None


class ExperimentalSitemapStore:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS regional_sitemap_runs(
          id INTEGER PRIMARY KEY, region TEXT NOT NULL, started_at TEXT NOT NULL,
          status TEXT NOT NULL, url_count INTEGER NOT NULL DEFAULT 0, error TEXT);
        CREATE TABLE IF NOT EXISTS regional_sitemap_urls(
          region TEXT NOT NULL, url TEXT NOT NULL, identity_key TEXT NOT NULL,
          first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
          PRIMARY KEY(region,url));
        CREATE TABLE IF NOT EXISTS regional_sitemap_candidates(
          id INTEGER PRIMARY KEY, region TEXT NOT NULL, url TEXT NOT NULL,
          identity_key TEXT NOT NULL, candidate_type TEXT NOT NULL, model TEXT,
          sku TEXT, canonical_url TEXT, confidence TEXT NOT NULL,
          reason TEXT NOT NULL, first_seen_at TEXT NOT NULL,
          UNIQUE(region,url));
        """)
        self.db.commit()

    def previous_count(self, region: str) -> int | None:
        row = self.db.execute("SELECT url_count FROM regional_sitemap_runs WHERE region=? AND status='ok' ORDER BY id DESC LIMIT 1", (region,)).fetchone()
        return None if row is None else row[0]

    def known_urls(self, region: str) -> set[str]:
        return {r[0] for r in self.db.execute("SELECT url FROM regional_sitemap_urls WHERE region=?", (region,))}

    def identity_seen_elsewhere(self, identity: str, region: str) -> bool:
        return self.db.execute("SELECT 1 FROM regional_sitemap_urls WHERE identity_key=? AND region<>? LIMIT 1", (identity, region)).fetchone() is not None

    def save_success(self, region: str, urls: set[str], candidates: list[dict], now: str) -> None:
        for url in urls:
            self.db.execute("INSERT INTO regional_sitemap_urls(region,url,identity_key,first_seen_at,last_seen_at) VALUES(?,?,?,?,?) ON CONFLICT(region,url) DO UPDATE SET last_seen_at=excluded.last_seen_at", (region, url, url_identity(url), now, now))
        for c in candidates:
            self.db.execute("INSERT OR IGNORE INTO regional_sitemap_candidates(region,url,identity_key,candidate_type,model,sku,canonical_url,confidence,reason,first_seen_at) VALUES(?,?,?,?,?,?,?,?,?,?)", (c['region'],c['url'],c['identity_key'],c['candidate_type'],c.get('model'),c.get('sku'),c.get('canonical_url'),c['confidence'],c['reason'],now))
            if c['identity_key'] != url_identity(c['url']):
                self.db.execute("UPDATE regional_sitemap_urls SET identity_key=? WHERE region=? AND url=?", (c['identity_key'],c['region'],c['url']))
        self.db.execute("INSERT INTO regional_sitemap_runs(region,started_at,status,url_count) VALUES(?,?, 'ok',?)", (region, now, len(urls)))
        self.db.commit()

    def save_failure(self, region: str, now: str, error: str) -> None:
        self.db.execute("INSERT INTO regional_sitemap_runs(region,started_at,status,error) VALUES(?,?, 'failed',?)", (region,now,error)); self.db.commit()

    def close(self): self.db.close()


@dataclass
class DeltaStats:
    regions_polled: int = 0
    baseline_urls: int = 0
    new_urls: int = 0
    fetched_new_urls: int = 0
    valid_candidates: int = 0
    mirror_duplicates_suppressed: int = 0
    failures: list[str] = field(default_factory=list)


class LenovoRegionalSitemapDeltaCollector:
    def __init__(self, store: ExperimentalSitemapStore, regions=P0_REGIONS, minimum_fraction: float = .35):
        self.store, self.regions, self.minimum_fraction = store, tuple(regions), minimum_fraction

    def run(self, fetcher, now: datetime | None = None) -> DeltaStats:
        now = now or datetime.now(timezone.utc); stamp = now.isoformat(); stats = DeltaStats()
        emitted_identities: set[str] = set()
        for region in self.regions:
            stats.regions_polled += 1
            try:
                urls = product_urls(fetcher.get(region.sitemap_url).body)
                previous = self.store.previous_count(region.code)
                if not urls or (previous and len(urls) / previous < self.minimum_fraction):
                    raise ValueError(f"unsafe sitemap count {len(urls)} (previous={previous})")
                known = self.store.known_urls(region.code)
                new = urls - known
                if previous is None:
                    stats.baseline_urls += len(urls)
                    self.store.save_success(region.code, urls, [], stamp)
                    continue
                candidates=[]
                for url in sorted(new):
                    stats.new_urls += 1
                    doc = fetcher.get(url); stats.fetched_new_urls += 1
                    facts = extract_product_identity(doc.body, url)
                    if facts is None:
                        continue
                    identity = facts['identity_key']
                    # Same identity newly appearing in multiple polled regions is
                    # one global discovery, not seven launch candidates.
                    if identity in emitted_identities:
                        stats.mirror_duplicates_suppressed += 1; continue
                    elsewhere = self.store.identity_seen_elsewhere(identity, region.code)
                    candidates.append({**facts, 'region':region.code, 'url':url,
                        'candidate_type': 'regional_page_appearance' if elsewhere else 'new_model_from_regional_sitemap',
                        'reason': 'official_lenovo_sitemap_url_delta'})
                    emitted_identities.add(identity); stats.valid_candidates += 1
                self.store.save_success(region.code, urls, candidates, stamp)
            except Exception as exc:
                stats.failures.append(f"{region.code}: {exc!r}")
                self.store.save_failure(region.code, stamp, str(exc))
        return stats

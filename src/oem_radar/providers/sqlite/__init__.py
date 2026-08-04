"""SQLite provider (M3): SnapshotStore + outbox + telemetry + components.

Single writer (ADR-1), WAL mode, append-only snapshots with hash dedup
(ADR-4), resolution v1 (ADR-3): URL identity → (manufacturer, model-key)
match → new product.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ...core.knownhw import canonicalize
from ...core.models import ChangeEvent, NormalizedProduct
from ...core.registry import stores

_SCHEMA = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
_MODEL_KEY_RE = re.compile(r"[^a-z0-9]+")

SCHEMA_VERSION = 3
# Idempotent-ish migrations for databases created at earlier versions.
# Fresh databases get the current schema.sql directly and record all versions.
_MIGRATIONS: dict[int, list[str]] = {
    2: [
        "ALTER TABLE snapshots ADD COLUMN normalized_zjson BLOB",
        "ALTER TABLE listings ADD COLUMN vendor_sku TEXT",
        "ALTER TABLE listings ADD COLUMN region TEXT",
    ],
    3: [
        "CREATE TABLE IF NOT EXISTS stories ("
        "id INTEGER PRIMARY KEY, rule_id TEXT NOT NULL, story_key TEXT NOT NULL, "
        "dedup_key TEXT NOT NULL UNIQUE, title TEXT NOT NULL, score INTEGER NOT NULL, "
        "manufacturers_json TEXT NOT NULL DEFAULT '[]', evidence_json TEXT NOT NULL DEFAULT '[]', "
        "score_reasons_json TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL DEFAULT (datetime('now')))",
        "CREATE INDEX IF NOT EXISTS idx_stories_created ON stories(created_at)",
    ],
}


def product_from_snapshot_row(row: sqlite3.Row) -> NormalizedProduct:
    """Decode a snapshot row (compressed or plaintext) to a product.
    Shared by the store's read path and the read-only dashboard."""
    try:
        zjson = row["normalized_zjson"]
    except (KeyError, IndexError):
        zjson = None
    raw = zlib.decompress(zjson).decode("utf-8") if zjson else row["normalized_json"]
    return NormalizedProduct.model_validate_json(raw)


def connect_readonly(db_path: str) -> sqlite3.Connection:
    """Open the DB read-only (won't lock or migrate; safe during a live
    crawl thanks to WAL). Raises sqlite3.OperationalError if absent."""
    uri = f"file:{Path(db_path).as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


# Tokens that distinguish product variants sharing a base name. If two models
# with the same coarse key differ by one of these, they are DIFFERENT products
# (SER9 vs SER9 PRO), not a rename — do not merge them.
_TIER_WORDS = frozenset({
    "pro", "max", "plus", "ultra", "air", "lite", "se", "gt", "gtx", "ti",
    "mini", "nano", "prime", "elite", "advanced", "super", "x",
})
_TOKEN_RE = re.compile(r"[^a-z0-9]+")


def _same_product(model_a: str, model_b: str) -> bool:
    """Do two model strings (already sharing a coarse key) denote the SAME
    product? False if they differ by a tier word — that's a distinct variant."""
    ta = {t for t in _TOKEN_RE.split(model_a.lower()) if t}
    tb = {t for t in _TOKEN_RE.split(model_b.lower()) if t}
    if (ta ^ tb) & _TIER_WORDS:
        return False
    return True


def model_key(manufacturer: str, model: str) -> str:
    """Identity key: tokens up to and including the first digit-bearing one
    ('K12 Mini PC AMD Ryzen 7 H 255' → 'k12', 'EVO-X1 AI Mini PC …' →
    'evo-x1'). Deliberately coarse — coarse keys create candidate links,
    which resolution surfaces for review, rather than silently splitting
    one product into many."""
    tokens = _MODEL_KEY_RE.sub(" ", model.lower()).split()
    key_tokens: list[str] = []
    for t in tokens[:4]:
        key_tokens.append(t)
        if any(c.isdigit() for c in t):
            break
    else:
        key_tokens = tokens[:2]  # no numeric token: fall back to first two words
    return f"{manufacturer.lower()}::{'-'.join(key_tokens)}"


@stores.register("sqlite")
class SqliteStore:
    def __init__(self, db_path: str = "data/radar.db", raw_dir: str = "data/raw") -> None:
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.raw_dir = Path(raw_dir)
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(db_path)
        self.db.row_factory = sqlite3.Row
        try:
            self.db.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError:
            pass  # some filesystems (network mounts) can't do WAL; default journal is fine
        self.db.execute("PRAGMA foreign_keys=ON")
        self.migrate()
        self._source_ctx: int | None = None  # sources.id during a run

    # -- lifecycle -----------------------------------------------------------

    def migrate(self) -> None:
        fresh = self.db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        ).fetchone() is None
        self.db.executescript(_SCHEMA)  # CREATE IF NOT EXISTS throughout
        if fresh:
            for v in range(1, SCHEMA_VERSION + 1):
                self.db.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)", (v,))
        else:
            current = self.db.execute(
                "SELECT COALESCE(MAX(version), 0) v FROM schema_migrations"
            ).fetchone()["v"]
            for v in range(current + 1, SCHEMA_VERSION + 1):
                for stmt in _MIGRATIONS.get(v, []):
                    try:
                        self.db.execute(stmt)
                    except sqlite3.OperationalError as exc:
                        if "duplicate column" not in str(exc).lower():
                            raise
                self.db.execute("INSERT INTO schema_migrations(version) VALUES (?)", (v,))
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    # -- registration of config entities ------------------------------------

    def ensure_manufacturer(self, name: str, country: str | None, aliases: list[str]) -> int:
        self.db.execute(
            "INSERT INTO manufacturers(name, country, aliases_json) VALUES (?,?,?) "
            "ON CONFLICT(name) DO UPDATE SET country=excluded.country, "
            "aliases_json=excluded.aliases_json",
            (name, country, json.dumps(aliases)),
        )
        return self.db.execute(
            "SELECT id FROM manufacturers WHERE name=?", (name,)
        ).fetchone()["id"]

    def ensure_source(self, source_key: str, manufacturer_id: int, engine: str,
                      base_url: str, config: dict) -> int:
        self.db.execute(
            "INSERT INTO sources(source_key, manufacturer_id, engine, base_url, config_json) "
            "VALUES (?,?,?,?,?) ON CONFLICT(source_key) DO UPDATE SET "
            "engine=excluded.engine, base_url=excluded.base_url, config_json=excluded.config_json",
            (source_key, manufacturer_id, engine, base_url, json.dumps(config, default=str)),
        )
        row = self.db.execute("SELECT id FROM sources WHERE source_key=?", (source_key,)).fetchone()
        self._source_ctx = row["id"]
        return row["id"]

    def has_completed_run(self, source_key: str) -> bool:
        return self.db.execute(
            "SELECT 1 FROM crawler_runs WHERE source_key=? AND status='ok' LIMIT 1",
            (source_key,),
        ).fetchone() is not None

    def source_due(self, source_key: str, min_interval_s: int) -> bool:
        row = self.db.execute(
            "SELECT started_at FROM crawler_runs WHERE source_key=? AND status='ok' "
            "ORDER BY started_at DESC LIMIT 1", (source_key,),
        ).fetchone()
        if row is None:
            return True
        last = datetime.fromisoformat(row["started_at"])
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - last).total_seconds() >= min_interval_s

    # -- SnapshotStore protocol ----------------------------------------------

    def _listing(self, product_key: str) -> sqlite3.Row | None:
        return self.db.execute(
            "SELECT * FROM listings WHERE product_key=?", (product_key,)
        ).fetchone()

    def _latest_snapshot_row(self, listing_id: int) -> sqlite3.Row | None:
        return self.db.execute(
            "SELECT * FROM snapshots WHERE listing_id=? ORDER BY id DESC LIMIT 1",
            (listing_id,),
        ).fetchone()

    _snap_product = staticmethod(product_from_snapshot_row)

    def latest(self, product_key: str) -> NormalizedProduct | None:
        listing = self._listing(product_key)
        if not listing:
            return None
        snap = self._latest_snapshot_row(listing["id"])
        return self._snap_product(snap) if snap else None

    def resolve_prior(self, product_key: str, product: NormalizedProduct):
        prior = self.latest(product_key)
        if prior is not None:
            return prior, "same_listing"
        # Cross-listing resolution (ADR-3). Strongest signal first: vendor SKU.
        if product.vendor_sku:
            row = self.db.execute(
                "SELECT id FROM listings WHERE vendor_sku=? AND product_key<>? "
                "ORDER BY last_seen_at DESC LIMIT 1",
                (product.vendor_sku, product_key),
            ).fetchone()
            if row:
                snap = self._latest_snapshot_row(row["id"])
                if snap:
                    return self._snap_product(snap), "existing_product"
        # Coarse model-key candidate — but only MERGE if it's plausibly the same
        # product. Two models sharing a key but differing by a tier word
        # (SER9 vs SER9 PRO) are DIFFERENT products; merging them produced
        # phantom component-change events. Guard against that.
        mk = model_key(product.manufacturer, product.model)
        row = self.db.execute(
            "SELECT l.id FROM listings l JOIN products p ON l.product_id=p.id "
            "WHERE p.canonical_model=? ORDER BY l.last_seen_at DESC LIMIT 1", (mk,),
        ).fetchone()
        if row:
            snap = self._latest_snapshot_row(row["id"])
            if snap:
                cand = self._snap_product(snap)
                if _same_product(cand.model, product.model):
                    return cand, "existing_product"
        return None, "none"

    def touch(self, product_key: str) -> None:
        self.db.execute(
            "UPDATE listings SET last_seen_at=datetime('now') WHERE product_key=?",
            (product_key,),
        )
        self.db.commit()

    def append(self, product_key: str, product: NormalizedProduct) -> None:
        mk = model_key(product.manufacturer, product.model)
        man_id = self.ensure_manufacturer(product.manufacturer, None, [])
        self.db.execute(
            "INSERT OR IGNORE INTO products(manufacturer_id, canonical_model, category) "
            "VALUES (?,?,?)", (man_id, mk, product.category),
        )
        prod_id = self.db.execute(
            "SELECT id FROM products WHERE manufacturer_id=? AND canonical_model=?",
            (man_id, mk),
        ).fetchone()["id"]

        listing = self._listing(product_key)
        if listing is None:
            src_id = self._source_ctx
            if src_id is None:  # standalone use (tests): synthesize a source
                src_id = self.ensure_source(product_key.split(":")[0], man_id, "unknown", "", {})
            self.db.execute(
                "INSERT INTO listings(source_id, product_id, product_key, url, vendor_handle, "
                "vendor_sku, region) VALUES (?,?,?,?,?,?,?)",
                (src_id, prod_id, product_key, product.source_url,
                 product_key.split(":", 1)[-1], product.vendor_sku, product.region),
            )
            listing = self._listing(product_key)
        listing_id = listing["id"]
        self.db.execute(  # SKU/region may arrive or improve on later crawls
            "UPDATE listings SET vendor_sku=COALESCE(?, vendor_sku), "
            "region=COALESCE(?, region) WHERE id=?",
            (product.vendor_sku, product.region, listing_id),
        )

        raw_ref = None
        if product.raw_data:
            raw_body = json.dumps(product.raw_data, ensure_ascii=False, default=str)
            digest = hashlib.sha256(raw_body.encode()).hexdigest()[:24]  # short: Windows MAX_PATH
            raw_path = self.raw_dir / f"{digest}.json"
            try:
                if not raw_path.exists():
                    raw_path.write_text(raw_body, encoding="utf-8")
                raw_ref = raw_path.name
            except OSError:
                raw_ref = None  # raw archive is a nice-to-have, never blocks a snapshot

        zjson = zlib.compress(product.model_dump_json().encode("utf-8"), 6)
        self.db.execute(
            "INSERT OR IGNORE INTO snapshots(listing_id, content_hash, normalized_json, "
            "normalized_zjson, confidence, raw_ref) VALUES (?,?,'',?,?,?)",
            (listing_id, product.content_hash(), zjson, product.confidence, raw_ref),
        )
        for price in product.prices:  # observation stream
            self.db.execute(
                "INSERT INTO prices(listing_id, amount, currency, region, availability) "
                "VALUES (?,?,?,?,?)",
                (listing_id, price.amount, price.currency, price.region,
                 price.availability.value),
            )
        for alias in product.aliases:
            self.db.execute(
                "INSERT OR IGNORE INTO aliases(product_id, alias) VALUES (?,?)",
                (prod_id, alias),
            )
        self.db.execute(
            "UPDATE listings SET last_seen_at=datetime('now') WHERE id=?", (listing_id,)
        )
        self.db.commit()

    # -- story detection ------------------------------------------------------

    def event_rows_for_stories(self, window_s: int):
        """Recent change_events joined to manufacturer/model/URL, as
        (ChangeEvent, manufacturer, model, url) tuples for the story detector."""
        import json as _json

        from ...core.models import ChangeEvent, ChangeType, Severity
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=window_s)).isoformat()
        rows = self.db.execute(
            "SELECT e.*, m.name AS manufacturer, p.canonical_model, l.url "
            "FROM change_events e "
            "LEFT JOIN listings l ON e.product_key = l.product_key "
            "LEFT JOIN products p ON l.product_id = p.id "
            "LEFT JOIN manufacturers m ON p.manufacturer_id = m.id "
            "WHERE e.detected_at >= ? ORDER BY e.detected_at", (cutoff,),
        ).fetchall()
        out = []
        for r in rows:
            event = ChangeEvent(
                product_key=r["product_key"],
                change_type=ChangeType(r["change_type"]),
                field=r["field"],
                old_value=_json.loads(r["old_value_json"]) if r["old_value_json"] else None,
                new_value=_json.loads(r["new_value_json"]) if r["new_value_json"] else None,
                severity=Severity(r["severity"]),
                detected_at=datetime.fromisoformat(r["detected_at"]),
                meta=_json.loads(r["meta_json"]) if r["meta_json"] else {},
            )
            model = r["canonical_model"] or r["product_key"].split(":", 1)[-1]
            out.append((event, r["manufacturer"] or "Unknown", model, r["url"]))
        return out

    def story_exists(self, dedup_key: str) -> bool:
        return self.db.execute(
            "SELECT 1 FROM stories WHERE dedup_key=?", (dedup_key,)
        ).fetchone() is not None

    def save_story(self, story) -> int:
        cur = self.db.execute(
            "INSERT OR IGNORE INTO stories(rule_id, story_key, dedup_key, title, score, "
            "manufacturers_json, evidence_json, score_reasons_json, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (story.rule_id, story.key, story.dedup_key(), story.title, story.score,
             json.dumps(story.manufacturers),
             json.dumps([e.model_dump() for e in story.evidence]),
             json.dumps(story.score_reasons), story.created_at.isoformat()),
        )
        self.db.commit()
        return cur.lastrowid

    def demote_events_for_products(self, product_keys: list) -> int:
        """A story fired: suppress its constituent products' still-pending
        individual notifications (one story embed, not N pings)."""
        if not product_keys:
            return 0
        qs = ",".join("?" * len(product_keys))
        cur = self.db.execute(
            f"UPDATE notifications SET status='demoted' WHERE status='pending' "
            f"AND change_event_id IN (SELECT id FROM change_events WHERE product_key IN ({qs}))",
            product_keys,
        )
        self.db.commit()
        return cur.rowcount

    def recent_stories(self, limit: int = 50):
        return self.db.execute(
            "SELECT * FROM stories ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()

    # -- known hardware -------------------------------------------------------

    def seed_components(self, seed: list[tuple[str, str]]) -> None:
        """Seed is (kind, RAW vendor string); canonicalized here through the
        same function the crawler uses, so seed slugs can't drift from runtime
        slugs. Accepts already-canonical slugs too (idempotent)."""
        rows = []
        for kind, raw in seed:
            slug = canonicalize(raw)
            if slug:
                rows.append((kind, slug, raw))
        self.db.executemany(
            "INSERT OR IGNORE INTO components(kind, canonical_name, first_raw, source) "
            "VALUES (?,?,?,'seeded')", rows,
        )
        self.db.commit()

    def mark_component_seen(self, names: list[str] | None = None) -> int:
        """Human curation from the dashboard: flip discovered components to
        'seen' so they leave the unseen feed. They stay 'known' (the row
        exists), so they never re-trigger an unseen-component alert. Passing
        None marks every currently-discovered component seen."""
        if names:
            cur = self.db.executemany(
                "UPDATE components SET source='seen' "
                "WHERE canonical_name=? AND source='discovered'",
                [(n,) for n in names],
            )
        else:
            cur = self.db.execute(
                "UPDATE components SET source='seen' WHERE source='discovered'")
        self.db.commit()
        return cur.rowcount

    def known_component(self, canonical: str) -> bool:
        return self.db.execute(
            "SELECT 1 FROM components WHERE canonical_name=?", (canonical,)
        ).fetchone() is not None

    def learn_component(self, kind: str, canonical: str, raw: str) -> None:
        self.db.execute(
            "INSERT OR IGNORE INTO components(kind, canonical_name, first_raw, source) "
            "VALUES (?,?,?,'discovered')", (kind, canonical, raw),
        )
        self.db.commit()

    # -- events + outbox ------------------------------------------------------

    def record_event(self, event: ChangeEvent) -> int:
        cur = self.db.execute(
            "INSERT INTO change_events(product_key, change_type, field, old_value_json, "
            "new_value_json, severity, meta_json, detected_at) VALUES (?,?,?,?,?,?,?,?)",
            (event.product_key, event.change_type.value, event.field,
             json.dumps(event.old_value, default=str), json.dumps(event.new_value, default=str),
             int(event.severity), json.dumps(event.meta), event.detected_at.isoformat()),
        )
        self.db.commit()
        return cur.lastrowid

    def outbox_put(self, provider: str, dedup_key: str, payload: dict,
                   event_id: int | None = None, status: str = "pending") -> None:
        self.db.execute(
            "INSERT OR IGNORE INTO notifications(change_event_id, provider, dedup_key, "
            "payload_json, status) VALUES (?,?,?,?,?)",
            (event_id, provider, dedup_key, json.dumps(payload), status),
        )
        self.db.commit()

    def outbox_pending(self, provider: str) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT * FROM notifications WHERE provider=? AND status='pending' "
            "ORDER BY id", (provider,),
        ).fetchall()

    def outbox_mark(self, notif_id: int, status: str, error: str | None = None) -> None:
        self.db.execute(
            "UPDATE notifications SET status=?, attempts=attempts+1, last_error=?, "
            "sent_at=CASE WHEN ?='sent' THEN datetime('now') ELSE sent_at END WHERE id=?",
            (status, error, status, notif_id),
        )
        self.db.commit()

    # -- telemetry ------------------------------------------------------------

    def run_started(self, source_key: str) -> int:
        cur = self.db.execute(
            "INSERT INTO crawler_runs(source_key, started_at) VALUES (?,?)",
            (source_key, datetime.now(timezone.utc).isoformat()),
        )
        self.db.commit()
        return cur.lastrowid

    def run_finished(self, run_id: int, status: str, stats: dict,
                     errors: list[str] | None = None) -> None:
        self.db.execute(
            "UPDATE crawler_runs SET finished_at=?, status=?, stats_json=? WHERE id=?",
            (datetime.now(timezone.utc).isoformat(), status, json.dumps(stats), run_id),
        )
        for err in errors or []:
            self.db.execute(
                "INSERT INTO run_errors(run_id, message) VALUES (?,?)", (run_id, err)
            )
        self.db.commit()

    def recent_runs(self, limit: int = 20) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT * FROM crawler_runs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()

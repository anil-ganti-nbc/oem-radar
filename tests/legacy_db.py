"""Honest legacy database fixtures for migration-compatibility tests.

`apply_legacy_schema` replays the project's own historical schema: the v1
base tables at their v1 column shapes, then the canonical `_MIGRATIONS` SQL
for each requested version, then the version stamps. A fixture built this
way is real old-shaped persistent state — the same class of state a
pre-upgrade production database has.

Marker-only stubs (a `schema_migrations` table plus nothing else) are NOT
valid legacy state: the marker would claim versions whose structures do not
exist. The pre-M15 store admitted such stubs only because it layered the
full current schema over them and swallowed the duplicate-column errors —
exactly the laundering the M15 compatibility barrier exists to prevent, so
these fixtures build the real shapes instead.
"""

BASE_V1_DDL = """
CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT DEFAULT '');

CREATE TABLE manufacturers (id INTEGER PRIMARY KEY, name TEXT UNIQUE, country TEXT,
  aliases_json TEXT DEFAULT '[]', created_at TEXT DEFAULT '');
CREATE TABLE sources (id INTEGER PRIMARY KEY, source_key TEXT UNIQUE, manufacturer_id INTEGER,
  engine TEXT, base_url TEXT, config_json TEXT DEFAULT '{}', enabled INTEGER DEFAULT 1,
  created_at TEXT DEFAULT '');
CREATE TABLE products (id INTEGER PRIMARY KEY, manufacturer_id INTEGER, canonical_model TEXT,
  series TEXT, category TEXT, status TEXT DEFAULT 'active', first_seen_at TEXT DEFAULT '',
  UNIQUE(manufacturer_id, canonical_model));
CREATE TABLE listings (id INTEGER PRIMARY KEY, source_id INTEGER, product_id INTEGER,
  product_key TEXT UNIQUE, url TEXT, vendor_handle TEXT,
  resolution_method TEXT DEFAULT 'url', resolution_confidence REAL DEFAULT 1.0,
  needs_review INTEGER DEFAULT 0, first_seen_at TEXT DEFAULT '', last_seen_at TEXT DEFAULT '');
CREATE TABLE snapshots (id INTEGER PRIMARY KEY, listing_id INTEGER, content_hash TEXT,
  normalized_json TEXT NOT NULL, confidence REAL DEFAULT 1.0,
  validation_issues_json TEXT DEFAULT '[]', raw_ref TEXT, captured_at TEXT DEFAULT '',
  UNIQUE(listing_id, content_hash));
CREATE TABLE change_events (id INTEGER PRIMARY KEY, product_key TEXT NOT NULL,
  change_type TEXT NOT NULL, field TEXT, old_value_json TEXT, new_value_json TEXT,
  severity INTEGER NOT NULL, meta_json TEXT DEFAULT '{}', detected_at TEXT DEFAULT '');
CREATE TABLE notifications (id INTEGER PRIMARY KEY, change_event_id INTEGER,
  provider TEXT, dedup_key TEXT UNIQUE, payload_json TEXT, status TEXT DEFAULT 'pending',
  attempts INTEGER DEFAULT 0, last_error TEXT, sent_at TEXT);
CREATE TABLE aliases (id INTEGER PRIMARY KEY, product_id INTEGER, alias TEXT,
  kind TEXT DEFAULT 'marketing', created_at TEXT DEFAULT '', UNIQUE(product_id, alias));
CREATE TABLE prices (id INTEGER PRIMARY KEY, listing_id INTEGER, amount REAL, currency TEXT,
  region TEXT, availability TEXT, observed_at TEXT DEFAULT '');
CREATE TABLE components (id INTEGER PRIMARY KEY, kind TEXT, canonical_name TEXT UNIQUE,
  first_raw TEXT, source TEXT DEFAULT 'seeded', first_seen_at TEXT DEFAULT '');
CREATE TABLE crawler_runs (id INTEGER PRIMARY KEY, source_key TEXT, started_at TEXT,
  finished_at TEXT, status TEXT DEFAULT 'running', stats_json TEXT DEFAULT '{}');
CREATE TABLE run_errors (id INTEGER PRIMARY KEY, run_id INTEGER, stage TEXT, url TEXT,
  message TEXT, occurred_at TEXT DEFAULT '');
"""


def apply_legacy_schema(con, upto_version: int) -> None:
    """Create the honest v1 shape, then canonically migrate it to
    `upto_version` using the store's own `_MIGRATIONS` SQL, stamping each
    version as it lands."""
    from oem_radar.providers.sqlite import _MIGRATIONS

    con.executescript(BASE_V1_DDL)
    con.execute("INSERT INTO schema_migrations(version) VALUES (1)")
    for version in range(2, upto_version + 1):
        for statement in _MIGRATIONS.get(version, []):
            con.execute(statement)
        con.execute("INSERT INTO schema_migrations(version) VALUES (?)", (version,))
    con.commit()

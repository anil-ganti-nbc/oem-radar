-- OEM Radar schema v1. See docs/DATABASE.md for semantics.
-- Append-only product data; only observation/workflow columns mutate.

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS manufacturers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    country TEXT,
    aliases_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY,
    source_key TEXT NOT NULL UNIQUE,          -- config id, e.g. 'gmktec-shopify'
    manufacturer_id INTEGER NOT NULL REFERENCES manufacturers(id),
    engine TEXT NOT NULL,
    base_url TEXT NOT NULL,
    config_json TEXT NOT NULL DEFAULT '{}',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY,
    manufacturer_id INTEGER NOT NULL REFERENCES manufacturers(id),
    canonical_model TEXT NOT NULL,            -- normalized identity key
    series TEXT,
    category TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    first_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(manufacturer_id, canonical_model)
);

CREATE TABLE IF NOT EXISTS listings (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    product_id INTEGER REFERENCES products(id),
    product_key TEXT NOT NULL UNIQUE,         -- '<source_key>:<handle>'
    url TEXT NOT NULL,
    vendor_handle TEXT,
    vendor_sku TEXT,
    region TEXT,
    resolution_method TEXT NOT NULL DEFAULT 'url',
    resolution_confidence REAL NOT NULL DEFAULT 1.0,
    needs_review INTEGER NOT NULL DEFAULT 0,
    first_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_listings_source ON listings(source_id, last_seen_at);
CREATE INDEX IF NOT EXISTS idx_listings_product ON listings(product_id);

CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY,
    listing_id INTEGER NOT NULL REFERENCES listings(id),
    content_hash TEXT NOT NULL,
    normalized_json TEXT NOT NULL,            -- '' when normalized_zjson is used
    normalized_zjson BLOB,                    -- zlib-compressed JSON (schema v2)
    confidence REAL NOT NULL DEFAULT 1.0,
    validation_issues_json TEXT NOT NULL DEFAULT '[]',
    raw_ref TEXT,
    captured_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(listing_id, content_hash)
);
CREATE INDEX IF NOT EXISTS idx_snapshots_listing ON snapshots(listing_id, captured_at);

CREATE TABLE IF NOT EXISTS change_events (
    id INTEGER PRIMARY KEY,
    product_key TEXT NOT NULL,
    change_type TEXT NOT NULL,
    field TEXT,
    old_value_json TEXT,
    new_value_json TEXT,
    severity INTEGER NOT NULL,
    meta_json TEXT NOT NULL DEFAULT '{}',
    detected_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_events_key ON change_events(product_key, detected_at);
CREATE INDEX IF NOT EXISTS idx_events_sev ON change_events(severity, detected_at);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY,
    change_event_id INTEGER REFERENCES change_events(id),
    provider TEXT NOT NULL,
    dedup_key TEXT NOT NULL UNIQUE,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',   -- pending | sent | failed | suppressed
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    sent_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_notifications_status ON notifications(status);

CREATE TABLE IF NOT EXISTS stories (
    id INTEGER PRIMARY KEY,
    rule_id TEXT NOT NULL,
    story_key TEXT NOT NULL,
    dedup_key TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    score INTEGER NOT NULL,
    manufacturers_json TEXT NOT NULL DEFAULT '[]',
    evidence_json TEXT NOT NULL DEFAULT '[]',
    score_reasons_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_stories_created ON stories(created_at);

CREATE TABLE IF NOT EXISTS aliases (
    id INTEGER PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(id),
    alias TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'marketing',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(product_id, alias)
);

CREATE TABLE IF NOT EXISTS prices (
    id INTEGER PRIMARY KEY,
    listing_id INTEGER NOT NULL REFERENCES listings(id),
    amount REAL NOT NULL,
    currency TEXT NOT NULL,
    region TEXT,
    availability TEXT,
    observed_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_prices_listing ON prices(listing_id, observed_at);

CREATE TABLE IF NOT EXISTS components (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    canonical_name TEXT NOT NULL UNIQUE,
    first_raw TEXT,
    source TEXT NOT NULL DEFAULT 'seeded',    -- seeded | discovered
    first_seen_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_components_kind ON components(kind, canonical_name);

CREATE TABLE IF NOT EXISTS crawler_runs (
    id INTEGER PRIMARY KEY,
    source_key TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',   -- running | ok | failed
    stats_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_runs_source ON crawler_runs(source_key, started_at);

CREATE TABLE IF NOT EXISTS run_errors (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES crawler_runs(id),
    stage TEXT,
    url TEXT,
    message TEXT NOT NULL,
    occurred_at TEXT NOT NULL DEFAULT (datetime('now'))
);

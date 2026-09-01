"""M15 persistent-state compatibility barrier (STD-DEPLOY-COM-002).

Second validation of the current-schema / bootstrap SQLite family (the
first was Feature Phone M14). Only the contract is shared: everything here
is OEM Radar's own mechanism — `inspect_schema` + the `SqliteStore`
admission gate — exercised end to end.

Every test runs against disposable local SQLite files: no production
database is touched, no crawler reaches the network, no deployment action
is taken. The legacy fixtures are honest old-shaped databases built by
tests/legacy_db.py (the project's own historical DDL), not marker-only
stubs — a marker-only stub is contradictory state the barrier rightly
refuses.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from http.client import HTTPConnection
from pathlib import Path

import pytest

from oem_radar.cli import main
from oem_radar.core.crawl_service import CrawlController, execute_crawl
from oem_radar.core.config import RadarConfig
from oem_radar.core.registry import notifiers, stores
from oem_radar.dashboard import _Handler
from oem_radar.providers.sqlite import (
    SCHEMA_VERSION,
    UNADMITTABLE_STATES,
    IncompatibleDatabaseError,
    SqliteStore,
    _MIGRATIONS,
)
from oem_radar.providers.sqlite.compatibility import (
    EXPECTED_TABLES,
    SchemaCompatibility,
    inspect_schema,
)
from oem_radar.runtime_bridge import _probe_sqlite
from legacy_db import apply_legacy_schema


# -- fixtures ----------------------------------------------------------------


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _marker_version(db_path: Path) -> int:
    con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    try:
        return con.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()[0]
    finally:
        con.close()


@pytest.fixture
def v6_db(tmp_path) -> Path:
    """An honest v6-shaped database carrying real legacy data, including an
    evidence observation recorded the Stage-11 way (as a product alert) so
    the canonical v7 migration's move-back proves data integrity."""
    db = tmp_path / "v6.db"
    con = sqlite3.connect(str(db))
    apply_legacy_schema(con, 6)
    con.execute(
        "INSERT INTO manufacturers(name) VALUES ('Lenovo')"
    )
    con.execute(
        "INSERT INTO sources(source_key, manufacturer_id, engine, base_url) "
        "VALUES ('src', 1, 'shopify', 'https://example.test')"
    )
    con.execute(
        "INSERT INTO listings(source_id, product_key, url) "
        "VALUES (1, 'src:k12', 'https://example.test/k12')"
    )
    con.execute(
        "INSERT INTO snapshots(listing_id, content_hash, normalized_json) "
        "VALUES (1, 'hash-1', '{\"legacy\": true}')"
    )
    con.execute(
        "INSERT INTO evidence_items(source_id, manufacturer, evidence_kind, provenance, "
        "canonical_url, external_id, content_hash) "
        "VALUES ('lenovo-psref', 'Lenovo', 'BIOS', 'OFFICIAL_SUPPORT', "
        "'https://example.test/bios', 'bios-1', 'ehash-1')"
    )
    con.execute(
        "INSERT INTO change_events(product_key, change_type, severity) "
        "VALUES ('evidence:lenovo-psref:bios-1', 'support_artifact_added', 3)"
    )
    event_id = con.execute("SELECT id FROM change_events").fetchone()[0]
    con.execute(
        "INSERT INTO notifications(change_event_id, provider, dedup_key, payload_json) "
        "VALUES (?, 'discord', 'dk-1', '{}')", (event_id,)
    )
    con.commit()
    con.close()
    return db


@pytest.fixture
def config_dir(tmp_path) -> Path:
    """A minimal operational config pointing every store path at tmp."""
    (tmp_path / "oems").mkdir()
    (tmp_path / "radar.yaml").write_text(
        "store: sqlite\n"
        f"db_path: {(tmp_path / 'radar.db').as_posix()}\n"
        f"raw_dir: {(tmp_path / 'raw').as_posix()}\n"
        f"run_lock_path: {(tmp_path / 'run.lock').as_posix()}\n",
        encoding="utf-8",
    )
    return tmp_path


def _make_incompatible(tmp_path: Path, kind: str) -> Path:
    db = tmp_path / f"{kind}.db"
    if kind == "newer":
        SqliteStore(str(db)).close()
        con = sqlite3.connect(str(db))
        con.execute("INSERT INTO schema_migrations(version) VALUES (?)", (SCHEMA_VERSION + 1,))
        con.commit()
        con.close()
    elif kind == "unknown":
        con = sqlite3.connect(str(db))
        con.execute("CREATE TABLE leftovers (id INTEGER PRIMARY KEY)")
        con.commit()
        con.close()
    elif kind == "corrupt":
        db.write_bytes(b"this is not a sqlite database file" * 32)
    else:
        raise ValueError(kind)
    return db


# -- 1-3: fresh identification, canonical bootstrap, expected state ----------


def test_truly_fresh_db_classified_fresh(tmp_path):
    empty = tmp_path / "empty.db"
    empty.write_bytes(b"")  # a 0-byte file is a valid, untouched SQLite db
    con = sqlite3.connect(f"file:{empty.as_posix()}?mode=ro", uri=True)
    try:
        report = inspect_schema(con)
    finally:
        con.close()
    assert report.state is SchemaCompatibility.FRESH
    assert report.observed_version is None


def test_fresh_db_bootstraps_canonically(tmp_path):
    db = tmp_path / "fresh.db"
    store = SqliteStore(str(db))
    try:
        assert store.compatibility_report.state is SchemaCompatibility.COMPATIBLE
        versions = [r["version"] for r in store.db.execute(
            "SELECT version FROM schema_migrations ORDER BY version")]
        assert versions == list(range(1, SCHEMA_VERSION + 1))
        tables = {r[0] for r in store.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        assert tables == set(EXPECTED_TABLES)
    finally:
        store.close()


def test_expected_v7_state_is_compatible(tmp_path):
    db = tmp_path / "current.db"
    SqliteStore(str(db)).close()
    store = SqliteStore(str(db))
    try:
        report = store.compatibility_report
        assert report.state is SchemaCompatibility.COMPATIBLE
        assert report.observed_version == SCHEMA_VERSION == report.expected_version
        # TABLE_EXISTS != COMPATIBLE: the marker is corroborated structurally
        assert EXPECTED_TABLES <= set(report.evidence["user_tables"])
    finally:
        store.close()


# -- 4: non-destructive inspection -------------------------------------------


def test_compatible_open_is_non_destructive(tmp_path):
    db = tmp_path / "stable.db"
    SqliteStore(str(db)).close()  # create + checkpoint
    before = _sha(db)
    store = SqliteStore(str(db))
    try:
        assert store.compatibility_report.state is SchemaCompatibility.COMPATIBLE
    finally:
        store.close()
    assert _sha(db) == before  # a compatible open performs no mutation


def test_refused_states_remain_byte_identical(tmp_path):
    db = _make_incompatible(tmp_path, "newer")
    before = _sha(db)
    with pytest.raises(IncompatibleDatabaseError):
        SqliteStore(str(db))
    assert _sha(db) == before  # refusal left the file byte-identical


# -- 5-7: valid older state (honest v6 shape, real legacy data) ---------------


def test_old_state_cannot_work_before_migration(v6_db, monkeypatch):
    assert _marker_version(v6_db) == 6

    def sabotaged(self, from_version):
        raise sqlite3.OperationalError("sabotaged canonical migration")

    monkeypatch.setattr(SqliteStore, "_migrate_incremental", sabotaged)
    with pytest.raises(IncompatibleDatabaseError):
        SqliteStore(str(v6_db))
    assert _marker_version(v6_db) == 6  # no normal work possible pre-migration
    monkeypatch.undo()
    store = SqliteStore(str(v6_db))  # preserved state still admits canonically
    try:
        assert store.compatibility_report.state is SchemaCompatibility.COMPATIBLE
    finally:
        store.close()


def test_old_state_migrates_only_through_canonical_mechanism(v6_db):
    store = SqliteStore(str(v6_db))
    try:
        versions = [r["version"] for r in store.db.execute(
            "SELECT version FROM schema_migrations ORDER BY version")]
        assert versions == list(range(1, SCHEMA_VERSION + 1))
        # legacy snapshot survived migration untouched
        row = store.db.execute(
            "SELECT normalized_json FROM snapshots WHERE content_hash='hash-1'"
        ).fetchone()
        assert row is not None and row["normalized_json"] == '{"legacy": true}'
        # canonical v7 backfill MOVED the stage-11 evidence alert: the
        # evidence_events log gained it, the alert stream lost it, and the
        # notification hanging off it was removed with it
        moved = store.db.execute(
            "SELECT ee.event_type, ei.external_id FROM evidence_events ee "
            "JOIN evidence_items ei ON ei.id = ee.evidence_item_id"
        ).fetchone()
        assert moved is not None and moved["event_type"] == "added"
        assert moved["external_id"] == "bios-1"
        assert store.db.execute(
            "SELECT COUNT(*) c FROM change_events WHERE product_key LIKE 'evidence:%'"
        ).fetchone()["c"] == 0
        assert store.db.execute(
            "SELECT COUNT(*) c FROM notifications WHERE dedup_key='dk-1'"
        ).fetchone()["c"] == 0
    finally:
        store.close()


def test_migrated_state_is_explicitly_reverified(v6_db):
    store = SqliteStore(str(v6_db))
    try:
        report = store.compatibility_report
        assert report.state is SchemaCompatibility.COMPATIBLE
        assert report.observed_version == SCHEMA_VERSION
    finally:
        store.close()


# -- 8-12: fail-closed refusals ------------------------------------------------


def test_newer_v8_state_fails_closed(tmp_path):
    db = _make_incompatible(tmp_path, "newer")
    before = _sha(db)
    with pytest.raises(IncompatibleDatabaseError) as excinfo:
        SqliteStore(str(db))
    report = excinfo.value.report
    assert report.state is SchemaCompatibility.INCOMPATIBLE_NEWER
    assert report.observed_version == SCHEMA_VERSION + 1
    assert "FORWARD_ONLY_EXPLICIT" in report.reason
    evidence = json.loads(json.dumps(report.as_evidence()))  # JSON-serializable
    assert evidence["compatibility_state"] == "INCOMPATIBLE_NEWER"
    assert _sha(db) == before
    assert _marker_version(db) == SCHEMA_VERSION + 1  # nothing downgraded/removed


def test_missing_marker_on_existing_db_fails_closed(tmp_path):
    db = tmp_path / "unknown.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE products (id INTEGER PRIMARY KEY, model TEXT)")
    con.execute("INSERT INTO products(model) VALUES ('kept for diagnosis')")
    con.commit()
    con.close()
    with pytest.raises(IncompatibleDatabaseError) as excinfo:
        SqliteStore(str(db))
    assert excinfo.value.report.state is SchemaCompatibility.UNKNOWN
    # unknown state preserved for diagnosis, never deleted or stamped
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        assert con.execute("SELECT model FROM products").fetchone()[0] == "kept for diagnosis"
    finally:
        con.close()


def test_malformed_marker_fails_closed(tmp_path):
    db = tmp_path / "malformed.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE schema_migrations (version TEXT, applied_at TEXT)")
    con.execute("CREATE TABLE products (id INTEGER PRIMARY KEY)")
    con.execute("INSERT INTO schema_migrations(version) VALUES ('garbage')")
    con.commit()
    con.close()
    with pytest.raises(IncompatibleDatabaseError) as excinfo:
        SqliteStore(str(db))
    assert excinfo.value.report.state is SchemaCompatibility.UNKNOWN


def test_contradictory_schema_version_fails_closed(tmp_path):
    # (a) a marker table without the expected version column
    db = tmp_path / "contradictory.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE schema_migrations (something_else TEXT)")
    con.execute("CREATE TABLE products (id INTEGER PRIMARY KEY)")
    con.commit()
    con.close()
    with pytest.raises(IncompatibleDatabaseError) as excinfo:
        SqliteStore(str(db))
    assert excinfo.value.report.state is SchemaCompatibility.UNKNOWN

    # (b) marker behind the actual structure: migration 5 would re-add a
    # column that already exists. The pre-M15 store SWALLOWED that error and
    # stamped forward; the barrier now refuses — contradictory authority.
    db2 = tmp_path / "duplicate_column.db"
    con = sqlite3.connect(str(db2))
    apply_legacy_schema(con, 4)
    con.execute("ALTER TABLE rule_suggestions ADD COLUMN fingerprint TEXT")
    con.close()
    with pytest.raises(IncompatibleDatabaseError) as excinfo:
        SqliteStore(str(db2))
    report = excinfo.value.report
    assert report.state is SchemaCompatibility.MIGRATION_REQUIRED
    assert "duplicate column" in report.evidence.get("admission_failure", "")
    assert _marker_version(db2) == 4  # version authority not advanced


def test_partial_migration_state_fails_closed(tmp_path):
    db = tmp_path / "partial.db"
    SqliteStore(str(db)).close()
    con = sqlite3.connect(str(db))
    con.execute("DROP TABLE notifications")
    con.commit()
    con.close()
    with pytest.raises(IncompatibleDatabaseError) as excinfo:
        SqliteStore(str(db))
    report = excinfo.value.report
    assert report.state is SchemaCompatibility.PARTIAL
    assert "notifications" in report.evidence["missing_tables"]


def test_corrupt_file_fails_closed(tmp_path):
    db = _make_incompatible(tmp_path, "corrupt")
    with pytest.raises(IncompatibleDatabaseError) as excinfo:
        SqliteStore(str(db))
    assert excinfo.value.report.state is SchemaCompatibility.CORRUPT


def test_failed_migration_cannot_mark_state_ready(tmp_path):
    """A v1 database whose snapshots already carry the v2 column: canonical
    migration 2 fails (duplicate column), rolls back, and the version
    authority stays at 1 — ready is never reached, and retry re-enters
    compatibility inspection rather than auto-repairing."""
    db = tmp_path / "v1_broken.db"
    con = sqlite3.connect(str(db))
    apply_legacy_schema(con, 1)
    con.execute("ALTER TABLE snapshots ADD COLUMN normalized_zjson BLOB")
    con.close()
    with pytest.raises(IncompatibleDatabaseError) as excinfo:
        SqliteStore(str(db))
    report = excinfo.value.report
    assert report.state is SchemaCompatibility.MIGRATION_REQUIRED
    assert "duplicate column" in report.evidence.get("admission_failure", "")
    assert _marker_version(db) == 1  # version authority not advanced
    # retry crosses compatibility inspection again and still refuses
    with pytest.raises(IncompatibleDatabaseError):
        SqliteStore(str(db))


# -- 14-15: CLI paths (scheduler and CLI both use `oem-radar run`) -------------


def _write_config(config_dir: Path, db_path: Path) -> Path:
    (config_dir / "oems").mkdir(parents=True, exist_ok=True)
    (config_dir / "radar.yaml").write_text(
        "store: sqlite\n"
        f"db_path: {db_path.as_posix()}\n"
        f"raw_dir: {(config_dir / 'raw').as_posix()}\n"
        f"run_lock_path: {(config_dir / 'run.lock').as_posix()}\n",
        encoding="utf-8",
    )
    return config_dir


def test_scheduler_and_cli_run_path_crosses_barrier(tmp_path, capsys):
    """The hourly scheduled task and a manual `oem-radar run` are the same
    one-shot command: it refuses incompatible state before any crawl."""
    db = _make_incompatible(tmp_path, "newer")
    before = _sha(db)
    config_dir = _write_config(tmp_path / "config", db)
    rc = main(["--config", str(config_dir), "run", "--no-lock"])
    assert rc == 3
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "state_incompatible"
    assert payload["gate"] == "persistent_state_compatibility"
    assert payload["compatibility_state"] == "INCOMPATIBLE_NEWER"
    assert _sha(db) == before


def test_cli_status_path_crosses_barrier(tmp_path, capsys):
    db = _make_incompatible(tmp_path, "unknown")
    config_dir = _write_config(tmp_path / "config", db)
    rc = main(["--config", str(config_dir), "status"])
    assert rc == 3
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "state_incompatible"


# -- 16: dashboard/operator paths cross the barrier -----------------------------


def test_dashboard_http_refuses_with_503_and_evidence(tmp_path):
    db = _make_incompatible(tmp_path, "unknown")
    from http.server import ThreadingHTTPServer

    handler = _Handler
    handler.db_path = str(db)
    handler.raw_dir = str(tmp_path / "raw")
    handler.max_body = 16384
    handler.csrf_token = "test-token"
    handler.crawl = None
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever)
    thread.start()
    try:
        conn = HTTPConnection("127.0.0.1", httpd.server_port, timeout=5)
        conn.request("GET", "/api/data")
        response = conn.getresponse()
        body = json.loads(response.read().decode())
        conn.close()
        assert response.status == 503
        assert body["error"]["code"] == "state_incompatible"
        assert body["error"]["gate"] == "persistent_state_compatibility"
        assert body["error"]["compatibility_state"] == "UNKNOWN"
    finally:
        httpd.shutdown()
        thread.join(timeout=5)


# -- 17-18: no bypass for direct consumers or one-shot persistence --------------


def test_direct_store_construction_cannot_bypass(tmp_path):
    db = _make_incompatible(tmp_path, "newer")
    # the registry-dispatched constructor every consumer uses is the gated one
    assert stores.get("sqlite") is SqliteStore
    radar = RadarConfig(db_path=str(db), raw_dir=str(tmp_path / "raw"))
    with pytest.raises(IncompatibleDatabaseError):
        stores.get(radar.store)(radar.db_path, radar.raw_dir)
    # and the crawl assembly raises before building any notifier
    from oem_radar.core.crawl_service import build_store_and_notifier
    with pytest.raises(IncompatibleDatabaseError):
        build_store_and_notifier(radar, tmp_path)


def test_event_persistence_cannot_precede_compatibility(tmp_path, config_dir):
    """A one-shot run cannot touch incompatible persistent state merely
    because it is short-lived: nothing is written, no crawler_runs row."""
    db = _make_incompatible(tmp_path / "sub", "newer")
    before = _sha(db)
    config = _write_config(config_dir, db)
    with pytest.raises(IncompatibleDatabaseError):
        execute_crawl(config, use_lock=False)
    assert _sha(db) == before
    # a durable crawler_runs.id proves nothing about compatibility — and
    # none was created: the refused store never got far enough to record one
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        assert con.execute("SELECT COUNT(*) FROM crawler_runs").fetchone()[0] == 0
    finally:
        con.close()


def test_dashboard_triggered_crawl_records_compatibility_refusal(tmp_path, config_dir):
    db = _make_incompatible(tmp_path / "sub", "newer")
    config = _write_config(config_dir, db)
    controller = CrawlController(config)
    accepted, reason, _ = controller.trigger()
    assert accepted is True
    controller.join(timeout=10)
    state = controller.status()
    assert state["status"] == "failed"
    assert "persistent-state compatibility refused" in state["message"]
    assert state["outcome"]["compatibility_state"] == "INCOMPATIBLE_NEWER"


# -- 19: health reports incompatibility honestly --------------------------------


def test_health_probe_reports_incompatible_state_without_mutation(tmp_path):
    db = _make_incompatible(tmp_path, "newer")
    before = _sha(db)
    writable, last, reasons, compat = _probe_sqlite(db)
    assert compat is SchemaCompatibility.INCOMPATIBLE_NEWER
    assert any(r.startswith("persistent_state: INCOMPATIBLE_NEWER") for r in reasons)
    assert _sha(db) == before  # the probe never mutates


def test_health_probe_reports_compatible_state_clean(tmp_path):
    db = tmp_path / "current.db"
    SqliteStore(str(db)).close()
    writable, last, reasons, compat = _probe_sqlite(db)
    assert compat is SchemaCompatibility.COMPATIBLE
    assert not any(r.startswith("persistent_state:") for r in reasons)


# -- 20: normal current-version one-shot execution remains intact ----------------


def test_normal_current_version_one_shot_execution_intact(tmp_path, config_dir):
    db = tmp_path / "radar.db"
    config = _write_config(config_dir, db)
    (config_dir / "oems").mkdir(exist_ok=True)
    outcome = execute_crawl(config, use_lock=False)
    assert outcome.sources == 0  # no OEMs configured: a clean empty pass
    store = SqliteStore(str(db))
    try:
        assert store.compatibility_report.state is SchemaCompatibility.COMPATIBLE
        versions = [r["version"] for r in store.db.execute(
            "SELECT version FROM schema_migrations ORDER BY version")]
        assert versions == list(range(1, SCHEMA_VERSION + 1))
    finally:
        store.close()
    # the dry-run in-memory path bootstraps through the same gate
    outcome_dry = execute_crawl(config, use_lock=False, dry_run=True)
    assert outcome_dry.sources == 0


# -- 21-22: OPS-COM-003 decision preserved; existing behavior intact -------------


def test_no_qualification_machinery_appears():
    """OPS-COM-003 stays NOT_APPLICABLE for OEM Radar: the compatibility
    barrier must not grow qualification epochs, maturity gates, or any of
    that machinery."""
    schema_sql = (Path(__file__).resolve().parents[1] / "src" / "oem_radar" / "providers"
                  / "sqlite" / "schema.sql").read_text(encoding="utf-8")
    assert "qualification" not in schema_sql.lower()
    assert "qualification" not in json.dumps(_MIGRATIONS).lower()
    assert SCHEMA_VERSION == 7
    assert sorted(_MIGRATIONS) == [2, 3, 4, 5, 6, 7]
    assert not any("qualification" in t for t in EXPECTED_TABLES)


def test_existing_remediation_behavior_remains_intact(tmp_path):
    """M3 run-lock semantics and the read-only lifecycle audit survive the
    barrier unchanged."""
    from oem_radar.core.run_lock import RunLock
    from oem_radar.providers.discord import DiscordNotifier

    assert notifiers.get("discord") is DiscordNotifier
    lock = RunLock.acquire(tmp_path / "run.lock")
    try:
        assert (tmp_path / "run.lock").exists()
    finally:
        lock.release()
    db = tmp_path / "current.db"
    SqliteStore(str(db)).close()
    from oem_radar.providers.sqlite import connect_readonly
    from oem_radar.core.db_lifecycle import integrity_report
    report = integrity_report(db)  # read-only audit still works
    assert report["integrity_check"] == "ok"
    assert report["schema_version"] == SCHEMA_VERSION


# -- semantics pin ----------------------------------------------------------------


def test_state_vocabulary_is_distinct():
    values = {s.value for s in SchemaCompatibility}
    assert values == {
        "FRESH", "MIGRATION_REQUIRED", "COMPATIBLE", "INCOMPATIBLE_NEWER",
        "UNKNOWN", "CORRUPT", "PARTIAL",
    }
    assert SchemaCompatibility.FRESH is not SchemaCompatibility.UNKNOWN
    assert SchemaCompatibility.UNKNOWN is not SchemaCompatibility.COMPATIBLE
    bad = {s for s in SchemaCompatibility} - {
        SchemaCompatibility.FRESH, SchemaCompatibility.MIGRATION_REQUIRED,
        SchemaCompatibility.COMPATIBLE,
    }
    assert bad == UNADMITTABLE_STATES

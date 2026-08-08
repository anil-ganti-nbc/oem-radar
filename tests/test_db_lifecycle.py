"""Stage 11.3 (Epoch 1 -> Epoch 2 cutover): tests for the reusable
archive/reset primitives in core/db_lifecycle.py.

Every test uses a temp-directory database — never the real
data/radar.db and never the real archive under data/archive/. The
cutover itself (2026-08-08) ran these checks by hand against the real
files; this pins the primitives so the next cutover can trust them
instead of re-deriving the same PRAGMA calls.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from oem_radar.core.db_lifecycle import (
    OPERATIONAL_TABLES,
    assert_all_operational_tables_empty,
    integrity_report,
    sha256_file,
    verify_archive,
)
from oem_radar.core.models import ChangeEvent, ChangeType, Severity
from oem_radar.providers.sqlite import SqliteStore


@pytest.fixture()
def store(tmp_path):
    s = SqliteStore(str(tmp_path / "r.db"), str(tmp_path / "raw"))
    yield s, tmp_path
    s.close()


def test_integrity_report_on_a_fresh_database(store):
    s, tmp_path = store
    report = integrity_report(tmp_path / "r.db")
    assert report["integrity_check"] == "ok"
    assert report["foreign_key_violations"] == 0
    assert report["schema_version"] >= 1
    assert set(report["row_counts"]) == set(OPERATIONAL_TABLES)
    assert all(c == 0 for c in report["row_counts"].values())


def test_integrity_report_counts_real_rows(store):
    s, tmp_path = store
    s.record_event(ChangeEvent(product_key="src:k1", change_type=ChangeType.NEW_PRODUCT,
                               severity=Severity.BREAKING))
    s.ensure_manufacturer("Acme", "US", [])
    report = integrity_report(tmp_path / "r.db")
    assert report["row_counts"]["change_events"] == 1
    assert report["row_counts"]["manufacturers"] == 1


def test_integrity_report_never_opens_the_file_read_write(store):
    """A read-only audit must not mutate the file it's inspecting."""
    s, tmp_path = store
    s.ensure_manufacturer("Acme", "US", [])
    s.close()
    before = sha256_file(tmp_path / "r.db")
    integrity_report(tmp_path / "r.db")
    integrity_report(tmp_path / "r.db")
    after = sha256_file(tmp_path / "r.db")
    assert before == after


def test_integrity_report_missing_table_reports_none_not_raise(tmp_path):
    """An old-schema database audited with this function should say
    what's missing, not crash — the whole point of a pre-flight check."""
    raw_db = sqlite3.connect(str(tmp_path / "bare.db"))
    raw_db.execute("CREATE TABLE schema_migrations(version INTEGER)")
    raw_db.execute("INSERT INTO schema_migrations VALUES (1)")
    raw_db.commit()
    raw_db.close()

    report = integrity_report(tmp_path / "bare.db")
    assert report["integrity_check"] == "ok"
    assert report["schema_version"] == 1
    assert report["row_counts"]["products"] is None
    assert report["row_counts"]["change_events"] is None


def _write_manifest(tmp_path, db_path, row_counts, **overrides):
    manifest = {
        "sha256": sha256_file(db_path),
        "schema_version": integrity_report(db_path)["schema_version"],
        "row_counts": row_counts,
    }
    manifest.update(overrides)
    p = tmp_path / "MANIFEST.json"
    p.write_text(json.dumps(manifest), encoding="utf-8")
    return p


def test_verify_archive_clean_returns_no_problems(store):
    s, tmp_path = store
    s.ensure_manufacturer("Acme", "US", [])
    s.close()
    manifest = _write_manifest(tmp_path, tmp_path / "r.db",
                               integrity_report(tmp_path / "r.db")["row_counts"])
    assert verify_archive(tmp_path / "r.db", manifest) == []


def test_verify_archive_catches_a_checksum_mismatch(store):
    s, tmp_path = store
    s.close()
    manifest = _write_manifest(tmp_path, tmp_path / "r.db",
                               integrity_report(tmp_path / "r.db")["row_counts"],
                               sha256="0" * 64)
    problems = verify_archive(tmp_path / "r.db", manifest)
    assert any("sha256 mismatch" in p for p in problems)


def test_verify_archive_catches_a_row_count_mismatch(store):
    s, tmp_path = store
    s.close()
    counts = integrity_report(tmp_path / "r.db")["row_counts"]
    counts["products"] = counts["products"] + 5
    manifest = _write_manifest(tmp_path, tmp_path / "r.db", counts)
    problems = verify_archive(tmp_path / "r.db", manifest)
    assert any("products" in p and "expected" in p for p in problems)


def test_verify_archive_catches_a_schema_version_mismatch(store):
    s, tmp_path = store
    s.close()
    manifest = _write_manifest(tmp_path, tmp_path / "r.db",
                               integrity_report(tmp_path / "r.db")["row_counts"],
                               schema_version=999)
    problems = verify_archive(tmp_path / "r.db", manifest)
    assert any("schema_version mismatch" in p for p in problems)


def test_verify_archive_reports_multiple_problems_at_once(store):
    s, tmp_path = store
    s.close()
    manifest = _write_manifest(tmp_path, tmp_path / "r.db", {"products": 999},
                               sha256="0" * 64, schema_version=999)
    problems = verify_archive(tmp_path / "r.db", manifest)
    assert len(problems) >= 3


def test_assert_all_operational_tables_empty_on_fresh_db(store):
    s, tmp_path = store
    assert assert_all_operational_tables_empty(tmp_path / "r.db") == []


def test_assert_all_operational_tables_empty_catches_leftover_data(store):
    s, tmp_path = store
    s.ensure_manufacturer("Acme", "US", [])
    problems = assert_all_operational_tables_empty(tmp_path / "r.db")
    assert any("manufacturers" in p for p in problems)


def test_sha256_file_is_deterministic(store):
    s, tmp_path = store
    s.close()
    assert sha256_file(tmp_path / "r.db") == sha256_file(tmp_path / "r.db")

"""Fleet-wide QC-archive contract for OEM Radar's alert review queue.

Modeled on korean-tech-wire's storage/qc_archive.py pattern: a physically
separate SQLite file, full item snapshot + provenance, UNIQUE(alert_id) as
the race guard, no in-memory state (restart-safe by construction).
"""
from __future__ import annotations

import sqlite3

import pytest

from oem_radar.core.qc_archive import (
    QC_DECISIONS,
    AlreadyQCed,
    QCArchive,
    source_key_of,
)


def _event(alert_id=1, product_key="gmktec-shopify:k12"):
    return {
        "id": alert_id,
        "product_key": product_key,
        "change_type": "new_product",
        "field": None,
        "old_value_json": None,
        "new_value_json": '{"model": "K12"}',
        "severity": 3,
        "meta_json": "{}",
        "detected_at": "2026-08-27T10:00:00+00:00",
    }


def test_source_key_of_parses_the_documented_product_key_format():
    assert source_key_of("gmktec-shopify:k12") == "gmktec-shopify"
    assert source_key_of("no-colon-here") is None
    assert source_key_of("") is None
    assert source_key_of(None) is None


def test_qc_decisions_are_oem_radars_own_four_terminal_outcomes():
    assert QC_DECISIONS == ("HIT", "INTERESTING", "NOISE", "BUG")


def test_archive_writes_a_full_snapshot_and_provenance(tmp_path):
    archive = QCArchive(tmp_path / "qc.db")
    archive.archive(_event(), "HIT", reason_codes=["VALID_CONFIRMATION_SIGNAL"],
                    note="confirmed on vendor site", decided_by="anil")
    row = archive.decision_for(1)
    assert row is not None
    assert row["alert_id"] == 1
    assert row["product_key"] == "gmktec-shopify:k12"
    assert row["source_key"] == "gmktec-shopify"  # provenance derived, not guessed
    assert row["change_type"] == "new_product"
    assert row["new_value_json"] == '{"model": "K12"}'
    assert row["decision"] == "HIT"
    assert row["note"] == "confirmed on vendor site"
    assert row["decided_by"] == "anil"
    assert row["decided_at"]


def test_archive_is_the_race_guard_not_a_pre_check(tmp_path):
    """Two concurrent QC submissions for the same alert can both attempt
    the INSERT; only one may commit. The second call must raise
    AlreadyQCed, never silently duplicate or corrupt the row."""
    archive = QCArchive(tmp_path / "qc.db")
    archive.archive(_event(), "HIT")
    with pytest.raises(AlreadyQCed):
        archive.archive(_event(), "NOISE")  # same alert_id, different decision
    # the original decision is untouched
    assert archive.decision_for(1)["decision"] == "HIT"
    assert len(archive.recent(10)) == 1


def test_archive_rejects_unknown_decisions(tmp_path):
    archive = QCArchive(tmp_path / "qc.db")
    with pytest.raises(ValueError):
        archive.archive(_event(), "MAYBE")


def test_archived_alert_ids_and_recent_and_status(tmp_path):
    archive = QCArchive(tmp_path / "qc.db")
    archive.archive(_event(1, "a:x"), "HIT")
    archive.archive(_event(2, "a:y"), "NOISE")
    archive.archive(_event(3, "b:z"), "NOISE")

    assert archive.archived_alert_ids() == {1, 2, 3}

    recent = archive.recent(limit=2)
    assert len(recent) == 2
    assert recent[0]["alert_id"] == 3  # most recently decided first

    status = archive.status()
    assert status["total"] == 3
    assert status["NOISE"] == 2 and status["HIT"] == 1


def test_state_persists_across_a_new_instance_same_path(tmp_path):
    """No in-memory state: a fresh QCArchive object pointed at the same
    file sees everything a prior instance wrote -- restart-safe."""
    path = tmp_path / "qc.db"
    QCArchive(path).archive(_event(), "BUG")

    reopened = QCArchive(path)
    assert reopened.archived_alert_ids() == {1}
    assert reopened.decision_for(1)["decision"] == "BUG"


def test_archive_creates_a_separate_file_not_the_live_db(tmp_path):
    live_db = tmp_path / "radar.db"
    sqlite3.connect(live_db).close()  # simulate an existing live DB
    archive_path = tmp_path / "oem_radar_qc.db"
    QCArchive(archive_path).archive(_event(), "HIT")
    assert archive_path.exists()
    assert archive_path != live_db

    con = sqlite3.connect(live_db)
    tables = con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    con.close()
    assert tables == []  # no qc_decisions table leaked into the live DB

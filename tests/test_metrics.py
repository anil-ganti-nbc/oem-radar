"""Stage 7 Phase 6: platform-wide metrics (core.metrics), surfaced via the
new `oem-radar coverage` CLI command. Config-derived metrics use a
temporary descriptor directory (never the real config/oems/); DB-derived
metrics use a temporary SQLite store — no reliance on live repo state, so
these stay correct as the real config/oems/ grows."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from oem_radar.core.metrics import (
    compute_coverage_metrics,
    compute_engine_stability,
    compute_fixture_coverage,
    compute_health_metrics,
    compute_platform_metrics,
    compute_signal_metrics,
)
from oem_radar.core.models import ChangeEvent, ChangeType, Severity
from oem_radar.providers.sqlite import SqliteStore, connect_readonly

_OEM_A = """
manufacturer:
  name: OemA
  country: US
sources:
  - id: oema-shopify
    engine: shopify
    base_url: https://oema.example
    enabled: true
"""

_OEM_B = """
# support_status: LIVE_VALIDATED — probed 2026-08-07.
manufacturer:
  name: OemB
  country: DE
sources:
  - id: oemb-sitemap
    engine: sitemap_jsonld
    base_url: https://oemb.example
    enabled: true
"""

_OEM_C_DISABLED = """
# support_status: NEEDS_OWNER_PROBE
manufacturer:
  name: OemC
  country: JP
sources:
  - id: oemc-shopify
    engine: shopify
    base_url: https://oemc.example
    enabled: false
"""


@pytest.fixture()
def oems_dir(tmp_path):
    d = tmp_path / "oems"
    d.mkdir()
    (d / "oema.yaml").write_text(_OEM_A, encoding="utf-8")
    (d / "oemb.yaml").write_text(_OEM_B, encoding="utf-8")
    (d / "oemc.yaml").write_text(_OEM_C_DISABLED, encoding="utf-8")
    return d


def test_coverage_counts_descriptors_and_enabled_sources(oems_dir):
    m = compute_coverage_metrics(oems_dir)
    assert m["total_oem_descriptors"] == 3
    assert m["total_oems_loaded"] == 3
    assert m["enabled_sources"] == 2
    assert m["disabled_sources"] == 1


def test_coverage_engine_usage_grouping(oems_dir):
    m = compute_coverage_metrics(oems_dir)
    assert m["sources_per_engine"] == {"shopify": 1, "sitemap_jsonld": 1}
    assert m["enabled_oems_per_engine"]["shopify"] == ["OemA"]
    assert m["enabled_oems_per_engine"]["sitemap_jsonld"] == ["OemB"]
    # disabled OemC must not appear as an enabled user of shopify
    assert "OemC" not in m["enabled_oems_per_engine"].get("shopify", [])


def test_coverage_status_breakdown_from_comments(oems_dir):
    m = compute_coverage_metrics(oems_dir)
    assert m["status_breakdown"]["LIVE_VALIDATED"] == 1
    assert m["status_breakdown"]["NEEDS_OWNER_PROBE"] == 1
    assert m["status_breakdown"]["UNDOCUMENTED"] == 1  # OemA has no status comment


def test_fixture_coverage_counts_files_per_engine_dir(tmp_path):
    fixtures = tmp_path / "fixtures"
    (fixtures / "shopify").mkdir(parents=True)
    (fixtures / "shopify" / "a.json").write_text("{}")
    (fixtures / "shopify" / "b.json").write_text("{}")
    (fixtures / "shopify" / "PROVENANCE.md").write_text("# notes")
    (fixtures / "dell").mkdir()
    m = compute_fixture_coverage(fixtures)
    assert m["shopify"] == 2  # PROVENANCE.md excluded
    assert m["dell"] == 0


def test_fixture_coverage_missing_dir_returns_empty(tmp_path):
    assert compute_fixture_coverage(tmp_path / "does-not-exist") == {}


@pytest.fixture()
def store(tmp_path):
    s = SqliteStore(str(tmp_path / "m.db"), str(tmp_path / "raw"))
    yield s, tmp_path / "m.db"
    s.close()


def test_health_metrics_from_real_runs(store):
    s, db_path = store
    s.db.execute(
        "INSERT INTO crawler_runs(source_key, started_at, finished_at, status, stats_json) "
        "VALUES (?,?,?,?,?)",
        ("src-a", "2026-01-01", "2026-01-01", "ok", json.dumps({"health": "ok", "discovered": 40})),
    )
    s.db.execute(
        "INSERT INTO crawler_runs(source_key, started_at, finished_at, status, stats_json) "
        "VALUES (?,?,?,?,?)",
        ("src-b", "2026-01-01", "2026-01-01", "failed", json.dumps({"health": "failed", "discovered": 0})),
    )
    s.db.commit()
    conn = connect_readonly(str(db_path))
    m = compute_health_metrics(conn)
    conn.close()
    assert m["total_runs"] == 2
    assert m["ok_runs"] == 1
    assert m["failed_runs"] == 1
    assert m["run_failure_rate"] == 0.5
    assert m["collectors_currently_healthy"] == 1
    assert m["collectors_currently_failed"] == 1
    assert m["average_catalog_size"] == 20.0  # (40+0)/2


def test_health_metrics_empty_db_degrades_gracefully(tmp_path):
    SqliteStore(str(tmp_path / "e.db"), str(tmp_path / "raw")).close()
    conn = connect_readonly(str(tmp_path / "e.db"))
    m = compute_health_metrics(conn)
    conn.close()
    assert m["total_runs"] == 0
    assert m["run_failure_rate"] is None
    assert m["average_catalog_size"] is None


def test_signal_metrics_reuses_feedback_analytics(store):
    s, db_path = store
    eid = s.record_event(ChangeEvent(product_key="src:k1", change_type=ChangeType.NEW_PRODUCT,
                                     severity=Severity.BREAKING))
    s.upsert_review(eid, outcome="HIT", reason_codes=["VALID_CONFIRMATION_SIGNAL"])
    conn = connect_readonly(str(db_path))
    m = compute_signal_metrics(conn)
    conn.close()
    assert m["total_change_events"] == 1
    assert m["hit_count"] == 1
    assert m["reviewed_alerts"] == 1


def test_platform_metrics_without_db_degrades_gracefully(oems_dir, tmp_path):
    m = compute_platform_metrics(oems_dir, tmp_path / "no-fixtures", conn=None)
    assert "note" in m["health"]
    assert "note" in m["signals"]
    assert m["coverage"]["total_oems_loaded"] == 3
    assert m["engine_stability"] == {}


# ============================================================================
# Stage 8 Phase 7: average crawl duration, per-day rates, engine stability.
# All computed from real, already-stored columns — no schema change, no
# fabricated numbers when the DB genuinely has no data yet.
# ============================================================================

def test_average_crawl_duration_from_real_timestamps(store):
    s, db_path = store
    s.db.execute(
        "INSERT INTO crawler_runs(source_key, started_at, finished_at, status, stats_json) "
        "VALUES (?,?,?,?,?)",
        ("src-a", "2026-01-01T00:00:00", "2026-01-01T00:00:10", "ok", "{}"),
    )
    s.db.execute(
        "INSERT INTO crawler_runs(source_key, started_at, finished_at, status, stats_json) "
        "VALUES (?,?,?,?,?)",
        ("src-b", "2026-01-01T00:00:00", "2026-01-01T00:00:30", "ok", "{}"),
    )
    s.db.commit()
    conn = connect_readonly(str(db_path))
    m = compute_health_metrics(conn)
    conn.close()
    assert m["average_crawl_duration_seconds"] == 20.0  # (10 + 30) / 2


def test_average_crawl_duration_none_when_no_finished_runs(tmp_path):
    SqliteStore(str(tmp_path / "e2.db"), str(tmp_path / "raw")).close()
    conn = connect_readonly(str(tmp_path / "e2.db"))
    m = compute_health_metrics(conn)
    conn.close()
    assert m["average_crawl_duration_seconds"] is None


def test_per_day_rates_use_real_event_span(store):
    s, db_path = store
    base = ChangeEvent(product_key="src:k1", change_type=ChangeType.NEW_PRODUCT,
                       severity=Severity.BREAKING)
    s.record_event(base)
    s.record_event(ChangeEvent(product_key="src:k2", change_type=ChangeType.PRICE_CHANGED,
                               severity=Severity.NOTABLE))
    conn = connect_readonly(str(db_path))
    m = compute_signal_metrics(conn)
    conn.close()
    # Both events recorded ~now, so the real span is < 1 day -> divisor clamps to 1.0
    assert m["new_products_per_day"] == 1.0
    assert m["changed_products_per_day"] == 1.0
    assert m["alerts_per_day"] == 2.0


def test_per_day_rates_none_with_no_events(tmp_path):
    SqliteStore(str(tmp_path / "e3.db"), str(tmp_path / "raw")).close()
    conn = connect_readonly(str(tmp_path / "e3.db"))
    m = compute_signal_metrics(conn)
    conn.close()
    assert m["new_products_per_day"] is None
    assert m["alerts_per_day"] is None


def test_false_positive_rate_aliases_noise_rate(store):
    s, db_path = store
    eid = s.record_event(ChangeEvent(product_key="src:k1", change_type=ChangeType.NEW_PRODUCT,
                                     severity=Severity.BREAKING))
    s.upsert_review(eid, outcome="NOISE", reason_codes=["ACCESSORY_OR_COMPONENT"])
    conn = connect_readonly(str(db_path))
    m = compute_signal_metrics(conn)
    conn.close()
    assert m["false_positive_rate"] == m["noise_rate"] == 1.0


def test_engine_stability_per_engine_latest_run(oems_dir, store):
    s, db_path = store
    # oema-shopify's latest run ok, oemb-sitemap's latest run failed
    s.db.execute(
        "INSERT INTO crawler_runs(source_key, started_at, finished_at, status, stats_json) "
        "VALUES (?,?,?,?,?)", ("oema-shopify", "2026-01-01", "2026-01-01", "ok", "{}"),
    )
    s.db.execute(
        "INSERT INTO crawler_runs(source_key, started_at, finished_at, status, stats_json) "
        "VALUES (?,?,?,?,?)", ("oemb-sitemap", "2026-01-01", "2026-01-01", "failed", "{}"),
    )
    s.db.commit()
    conn = connect_readonly(str(db_path))
    m = compute_engine_stability(oems_dir, conn)
    conn.close()
    assert m["shopify"] == 1.0
    assert m["sitemap_jsonld"] == 0.0


def test_engine_stability_ignores_runs_for_removed_sources(oems_dir, store):
    s, db_path = store
    s.db.execute(
        "INSERT INTO crawler_runs(source_key, started_at, finished_at, status, stats_json) "
        "VALUES (?,?,?,?,?)", ("no-longer-configured", "2026-01-01", "2026-01-01", "ok", "{}"),
    )
    s.db.commit()
    conn = connect_readonly(str(db_path))
    m = compute_engine_stability(oems_dir, conn)
    conn.close()
    assert m == {}

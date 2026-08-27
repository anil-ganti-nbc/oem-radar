"""Collector census/classification framework tests (campaign deliverable E).

All fixtures here are synthetic; the framework itself stamps local datasets
UNVERIFIED_PENDING_HETZNER so no production tier can be smuggled in.
"""

from datetime import datetime, timedelta, timezone

from oem_radar.core.census import (
    Disposition,
    RuntimeClass,
    YieldClass,
    classify_runtime,
    classify_source,
    classify_yield,
)

T0 = datetime(2026, 8, 27, tzinfo=timezone.utc)


def run_row(source: str, minutes: float, status: str = "ok",
            discovered: int = 50, offset_h: int = 0) -> dict:
    start = T0 - timedelta(hours=offset_h)
    return {
        "source_key": source,
        "started_at": start.isoformat(),
        "finished_at": (start + timedelta(minutes=minutes)).isoformat(),
        "status": status,
        "stats_json": '{"discovered": %d, "unchanged": 49, "events": 1}' % discovered
            if status == "ok" else '{"errors": 1}',
    }


def test_hard_rule_over_ten_minutes_is_daily():
    assert classify_runtime(601) == RuntimeClass.DAILY
    assert classify_runtime(10 * 60 + 0.001) == RuntimeClass.DAILY


def test_tier_boundaries():
    assert classify_runtime(119) == RuntimeClass.FAST
    assert classify_runtime(121) == RuntimeClass.STANDARD
    assert classify_runtime(299) == RuntimeClass.STANDARD
    assert classify_runtime(301) == RuntimeClass.HEAVY
    assert classify_runtime(600) == RuntimeClass.HEAVY  # exactly 10m stays HEAVY


def test_yield_classes():
    assert classify_yield(1, 20) == YieldClass.HIGH_YIELD       # >= .05/run
    assert classify_yield(2, 300) == YieldClass.NORMAL          # > 0 but rare
    assert classify_yield(0, 300) == YieldClass.LOW_YIELD
    assert classify_yield(3, 0) == YieldClass.DEAD


def test_local_epoch_dataset_is_stamped_unverified():
    rows = [run_row("khadas-sitemap", 8.35, offset_h=h * 12) for h in range(5)]
    census = classify_source(rows)  # default verification flag
    assert census.verification == "UNVERIFIED_PENDING_HETZNER"
    assert "non-authoritative" in " ".join(census.notes)


def test_slow_never_completed_run_counts_as_failure_signal():
    """lg-us-gram-sitemap pattern: runs started, never finished."""
    rows = [{
        "source_key": "lg-us-gram-sitemap",
        "started_at": (T0 - timedelta(hours=48)).isoformat(),
        "finished_at": None,
        "status": "running",
        "stats_json": "{}",
    }]
    census = classify_source(rows)
    assert census.ok_runs == 0
    assert census.yield_class == YieldClass.DEAD


def test_fast_zero_yield_source_recommended_for_replacement():
    rows = [run_row("kamrui-shopify", 0.7, offset_h=h) for h in range(30)]
    census = classify_source(rows)
    assert census.runtime_class == RuntimeClass.FAST
    assert census.yield_class == YieldClass.LOW_YIELD
    assert census.disposition == Disposition.REPLACE


def test_slow_high_yield_deserves_daily_slot():
    rows = [run_row("lenovo-psref", 14.0, offset_h=h * 24) for h in range(10)]
    # inject editorial yield via stats keys the framework understands
    for r in rows:
        r["stats_json"] = r["stats_json"].replace("}", ', "editorial_new_skus": 1}')
    census = classify_source(rows)
    assert census.runtime_class == RuntimeClass.DAILY
    assert census.yield_class == YieldClass.HIGH_YIELD
    assert census.disposition == Disposition.DEMOTE


def test_blocked_rate_detected_from_403_failures():
    rows = [run_row("dell-us-laptops", 1.0, status="failed",
                    offset_h=h) for h in range(4)]
    for r in rows:
        r["stats_json"] = '{"errors": 1, "http_status": 403, "error": "HTTP 403 Forbidden"}'
    census = classify_source(rows)
    assert census.blocked_rate == 1.0

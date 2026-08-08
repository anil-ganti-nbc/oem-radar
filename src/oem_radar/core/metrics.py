"""Platform-wide metrics (Stage 7 Phase 6).

Deliberately a standalone `core` module, not a dashboard feature — per the
stage's "do not redesign the dashboard" boundary, this lives behind a new
CLI command (`oem-radar coverage`) instead. Every number here is computed
from real config/DB state; nothing is estimated or guessed. Where a
requested metric genuinely isn't tracked anywhere (e.g. per-run wall-clock
duration isn't stored as its own column), that's reported as "not tracked"
rather than approximated.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

_STATUS_RE = re.compile(r"#\s*support_status:\s*([A-Z_]+)", re.IGNORECASE)


def _leading_status(yaml_path: Path) -> str | None:
    """Best-effort read of a descriptor's `# support_status: X` header
    comment. Not a structured config field (deliberately — it's
    documentation for humans, not policy the engine reads), so this is a
    convention scan, not a schema requirement; files without the comment
    just don't contribute to the status breakdown."""
    try:
        text = yaml_path.read_text(encoding="utf-8")
    except OSError:
        return None
    m = _STATUS_RE.search(text)
    return m.group(1).upper() if m else None


def compute_coverage_metrics(oems_dir: Path) -> dict[str, Any]:
    """OEM/source/engine counts purely from config/oems/*.yaml — no network,
    no DB. Distinguishes *configured* descriptors (every .yaml file, whether
    or not it defines an enabled source) from *enabled* sources."""
    from .config import load_oem_configs

    oems = load_oem_configs(oems_dir)
    total_oems = len(oems)
    enabled_sources = 0
    disabled_sources = 0
    engine_usage: Counter[str] = Counter()
    enabled_oems_by_engine: dict[str, set[str]] = {}

    for name, oem in oems.items():
        for src in oem.sources:
            if src.enabled:
                enabled_sources += 1
                engine_usage[src.engine] += 1
                enabled_oems_by_engine.setdefault(src.engine, set()).add(name)
            else:
                disabled_sources += 1

    status_breakdown: Counter[str] = Counter()
    all_yaml = sorted(oems_dir.glob("*.yaml"))
    for path in all_yaml:
        status = _leading_status(path)
        status_breakdown[status or "UNDOCUMENTED"] += 1

    return {
        "total_oem_descriptors": len(all_yaml),
        "total_oems_loaded": total_oems,
        "enabled_sources": enabled_sources,
        "disabled_sources": disabled_sources,
        "engines_in_use": sorted(engine_usage),
        "sources_per_engine": dict(engine_usage),
        "enabled_oems_per_engine": {k: sorted(v) for k, v in enabled_oems_by_engine.items()},
        "status_breakdown": dict(status_breakdown),
    }


def compute_health_metrics(conn: sqlite3.Connection) -> dict[str, Any]:
    """Collector health/run metrics from `crawler_runs` — the same
    `stats_json` payload the dashboard reads (see dashboard/data.py), but
    queried independently here since core must not import the dashboard
    layer."""
    def scalar(sql: str, params: tuple = ()) -> int:
        try:
            row = conn.execute(sql, params).fetchone()
            return row[0] if row else 0
        except sqlite3.OperationalError:
            return 0

    total_runs = scalar("SELECT COUNT(*) FROM crawler_runs")
    failed_runs = scalar("SELECT COUNT(*) FROM crawler_runs WHERE status='failed'")
    ok_runs = scalar("SELECT COUNT(*) FROM crawler_runs WHERE status='ok'")

    # Latest run per source -> current health/catalog-size snapshot.
    try:
        rows = conn.execute(
            "SELECT source_key, stats_json FROM crawler_runs "
            "WHERE id IN (SELECT MAX(id) FROM crawler_runs GROUP BY source_key)"
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []

    degraded = failed = healthy = 0
    catalog_sizes: list[int] = []
    for r in rows:
        stats = json.loads(r["stats_json"] or "{}")
        health = stats.get("health")
        if health == "degraded":
            degraded += 1
        elif health == "failed":
            failed += 1
        elif health == "ok":
            healthy += 1
        discovered = stats.get("discovered")
        if isinstance(discovered, int):
            catalog_sizes.append(discovered)

    avg_catalog = round(sum(catalog_sizes) / len(catalog_sizes), 1) if catalog_sizes else None

    # Average crawl duration (Stage 8 Phase 7): `crawler_runs.started_at`/
    # `finished_at` are both real ISO timestamps already stored for every
    # run (see run_started/run_finished) — no schema change needed. Stage 7
    # assumed a new column would be required to compute this honestly; that
    # assumption was wrong, corrected here rather than carried forward.
    avg_duration = None
    try:
        row = conn.execute(
            "SELECT AVG((julianday(finished_at) - julianday(started_at)) * 86400.0) "
            "FROM crawler_runs WHERE finished_at IS NOT NULL"
        ).fetchone()
        if row and row[0] is not None:
            avg_duration = round(row[0], 2)
    except sqlite3.OperationalError:
        pass

    # Per-engine run stability: of each engine's sources' most recent run,
    # what fraction succeeded (status='ok')? Requires joining crawler_runs'
    # source_key back to config, so this is computed by the caller
    # (compute_platform_metrics) where the OEM config is available — see
    # `engine_stability` there.

    return {
        "total_runs": total_runs,
        "ok_runs": ok_runs,
        "failed_runs": failed_runs,
        "run_failure_rate": round(failed_runs / total_runs, 4) if total_runs else None,
        "collectors_currently_healthy": healthy,
        "collectors_currently_degraded": degraded,
        "collectors_currently_failed": failed,
        "average_catalog_size": avg_catalog,
        "average_crawl_duration_seconds": avg_duration,
        "collector_stability": round(healthy / len(rows), 4) if rows else None,
    }


def compute_signal_metrics(conn: sqlite3.Connection) -> dict[str, Any]:
    """Reuses core.feedback_analytics.compute_summary — no metric math
    duplicated here, same rule the dashboard follows."""
    from .feedback_analytics import compute_summary

    try:
        summary = compute_summary(conn)
    except sqlite3.OperationalError:
        return {"note": "feedback tables not present (pre-v4 DB)"}

    def scalar(sql: str) -> int:
        try:
            row = conn.execute(sql).fetchone()
            return row[0] if row else 0
        except sqlite3.OperationalError:
            return 0

    total_events = scalar("SELECT COUNT(*) FROM change_events")

    # Review completion rate and false-positive rate (Stage 8 Phase 7) are
    # already computed by feedback_analytics.compute_summary as
    # `review_completion_rate` and `noise_rate` respectively (noise-outcome
    # reviews / reviewed alerts — the working definition of "alerts a human
    # marked as not real signal") — reused via `summary` below rather than
    # recomputed, so this can never disagree with the numbers `oem-radar`
    # already prints elsewhere.

    # new/changed products per day and alerts per day: real span computed
    # from the actual first/last event timestamps in the DB, not an assumed
    # fixed window — a DB with 3 days of history reports a 3-day average,
    # not a 30-day one.
    span_row = conn.execute(
        "SELECT MIN(detected_at), MAX(detected_at) FROM change_events"
    ).fetchone()
    per_day: dict[str, float | None] = {
        "new_products_per_day": None,
        "changed_products_per_day": None,
        "alerts_per_day": None,
    }
    if span_row and span_row[0] and span_row[1]:
        days = conn.execute(
            "SELECT MAX(1.0, (julianday(?) - julianday(?)))", (span_row[1], span_row[0])
        ).fetchone()[0]
        new_count = scalar("SELECT COUNT(*) FROM change_events WHERE change_type='new_product'")
        changed_count = scalar(
            "SELECT COUNT(*) FROM change_events WHERE change_type != 'new_product' "
            "AND change_type != 'product_removed'"
        )
        per_day["new_products_per_day"] = round(new_count / days, 2)
        per_day["changed_products_per_day"] = round(changed_count / days, 2)
        per_day["alerts_per_day"] = round(total_events / days, 2)

    return {
        "total_change_events": total_events,
        **per_day,
        **summary,
        "false_positive_rate": summary.get("noise_rate"),  # alias for Phase 7's requested metric name
    }


def compute_fixture_coverage(fixtures_dir: Path) -> dict[str, Any]:
    """Real fixture-file counts per engine's fixture directory — a rough
    proxy for how much of the enabled catalog is backed by a captured,
    provenance-recorded real response (see each PROVENANCE.md)."""
    counts: dict[str, int] = {}
    if not fixtures_dir.exists():
        return counts
    for sub in sorted(fixtures_dir.iterdir()):
        if not sub.is_dir():
            continue
        files = [f for f in sub.iterdir() if f.is_file() and f.name != "PROVENANCE.md"]
        counts[sub.name] = len(files)
    return counts


def compute_engine_stability(oems_dir: Path, conn: sqlite3.Connection) -> dict[str, Any]:
    """Per-engine share of sources whose *most recent* run succeeded
    (status='ok'). Requires joining `crawler_runs.source_key` back to each
    source's configured engine, so — unlike `compute_health_metrics` — this
    needs the OEM config, not just the DB."""
    from .config import load_oem_configs

    oems = load_oem_configs(oems_dir)
    engine_by_source: dict[str, str] = {}
    for oem in oems.values():
        for src in oem.sources:
            if src.enabled:
                engine_by_source[src.id] = src.engine

    try:
        rows = conn.execute(
            "SELECT source_key, status FROM crawler_runs "
            "WHERE id IN (SELECT MAX(id) FROM crawler_runs GROUP BY source_key)"
        ).fetchall()
    except sqlite3.OperationalError:
        return {}

    totals: Counter[str] = Counter()
    ok: Counter[str] = Counter()
    for r in rows:
        engine = engine_by_source.get(r["source_key"])
        if engine is None:
            continue  # a run for a source no longer in config (renamed/removed)
        totals[engine] += 1
        if r["status"] == "ok":
            ok[engine] += 1

    return {engine: round(ok[engine] / totals[engine], 4) for engine in totals}


def compute_platform_metrics(oems_dir: Path, fixtures_dir: Path,
                             conn: sqlite3.Connection | None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "coverage": compute_coverage_metrics(oems_dir),
        "fixture_coverage": compute_fixture_coverage(fixtures_dir),
    }
    if conn is not None:
        result["health"] = compute_health_metrics(conn)
        result["signals"] = compute_signal_metrics(conn)
        result["engine_stability"] = compute_engine_stability(oems_dir, conn)
    else:
        result["health"] = {"note": "no database available — run `oem-radar run` first"}
        result["signals"] = {"note": "no database available — run `oem-radar run` first"}
        result["engine_stability"] = {}
    return result

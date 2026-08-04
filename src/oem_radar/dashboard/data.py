"""Dashboard data layer (M12). Pure read-only queries over the SQLite DB;
returns plain JSON-serializable dicts so it is trivially testable and the
render layer needs no DB knowledge. No writes, no migration — opens the DB
read-only (safe during a live crawl)."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from ..providers.sqlite import product_from_snapshot_row


def _loads(s, default=None):
    try:
        return json.loads(s) if s else default
    except (TypeError, json.JSONDecodeError):
        return default


def _latest_product_brief(conn: sqlite3.Connection, product_key: str,
                          cache: dict) -> dict:
    """The current display facts for a product_key: model, silicon, price,
    image, and the all-important store URL. Cached per call."""
    if product_key in cache:
        return cache[product_key]
    row = conn.execute(
        "SELECT s.* FROM snapshots s JOIN listings l ON s.listing_id = l.id "
        "WHERE l.product_key = ? ORDER BY s.id DESC LIMIT 1", (product_key,),
    ).fetchone()
    brief: dict = {}
    if row:
        p = product_from_snapshot_row(row)
        price = p.prices[0] if p.prices else None
        brief = {
            "manufacturer": p.manufacturer,
            "model": p.model,
            "cpu": (p.cpu.raw if p.cpu else None),
            "cpu_unseen": (p.cpu.known is False if p.cpu else False),
            "gpu": (p.gpu.raw if p.gpu else None),
            "memory": p.memory,
            "storage": p.storage,
            "price": (f"{price.amount:g} {price.currency}" if price else None),
            "region": (price.region if price else None),
            "image": (p.images[0] if p.images else None),
            "url": p.source_url,
            "confidence": p.confidence,
            "configs": len(p.configurations),
        }
    cache[product_key] = brief
    return brief


def collect(conn: sqlite3.Connection, limit: int = 300) -> dict:
    brief_cache: dict = {}

    def brief(key):
        return _latest_product_brief(conn, key, brief_cache)

    # ---- events (the heart of the view) ----
    event_rows = conn.execute(
        "SELECT e.id, e.product_key, e.change_type, e.field, e.old_value_json, "
        "e.new_value_json, e.severity, e.meta_json, e.detected_at, "
        "n.status AS notif_status "
        "FROM change_events e "
        "LEFT JOIN notifications n ON n.change_event_id = e.id "
        "ORDER BY e.detected_at DESC, e.id DESC LIMIT ?", (limit,),
    ).fetchall()
    events = []
    for r in event_rows:
        b = brief(r["product_key"])
        meta = _loads(r["meta_json"], {})
        events.append({
            "id": r["id"],
            "product_key": r["product_key"],
            "type": r["change_type"],
            "field": r["field"],
            "old": _loads(r["old_value_json"]),
            "new": _loads(r["new_value_json"]),
            "severity": r["severity"],
            "detected_at": r["detected_at"],
            "notified": r["notif_status"] in ("pending", "sent"),
            "unseen_component": bool(meta.get("unseen_component")),
            "hidden": bool(meta.get("hidden")),
            "magnitude_pct": meta.get("magnitude_pct"),
            "direction": meta.get("direction"),
            "added": meta.get("added"),
            "removed": meta.get("removed"),
            "manufacturer": b.get("manufacturer"),
            "model": b.get("model"),
            "cpu": b.get("cpu"),
            "cpu_unseen": b.get("cpu_unseen"),
            "gpu": b.get("gpu"),
            "memory": b.get("memory"),
            "storage": b.get("storage"),
            "price": b.get("price"),
            "region": b.get("region"),
            "image": b.get("image"),
            "url": b.get("url"),
            "confidence": b.get("confidence"),
        })

    # ---- unseen / discovered hardware feed ----
    comp_rows = conn.execute(
        "SELECT kind, canonical_name, first_raw, source, first_seen_at "
        "FROM components WHERE source = 'discovered' "
        "ORDER BY first_seen_at DESC, id DESC LIMIT 100"
    ).fetchall()
    components = [dict(r) for r in comp_rows]

    # ---- manufacturers overview ----
    man_rows = conn.execute(
        "SELECT m.name, COUNT(DISTINCT p.id) AS products "
        "FROM manufacturers m LEFT JOIN products p ON p.manufacturer_id = m.id "
        "GROUP BY m.id ORDER BY products DESC"
    ).fetchall()
    manufacturers = [dict(r) for r in man_rows]

    # ---- run telemetry ----
    run_rows = conn.execute(
        "SELECT source_key, started_at, finished_at, status, stats_json "
        "FROM crawler_runs ORDER BY id DESC LIMIT 40"
    ).fetchall()
    runs = []
    for r in run_rows:
        stats = _loads(r["stats_json"], {})
        runs.append({
            "source": r["source_key"], "started_at": r["started_at"],
            "status": r["status"],
            "snapshots": stats.get("snapshots_written"),
            "events": stats.get("events"),
            "discovered": stats.get("discovered"),
            "errors": stats.get("errors"),
        })

    def scalar(sql):
        try:
            return conn.execute(sql).fetchone()[0]
        except sqlite3.OperationalError:
            return 0  # table not present in an older DB

    last_run = conn.execute(
        "SELECT started_at FROM crawler_runs WHERE status='ok' "
        "ORDER BY id DESC LIMIT 1"
    ).fetchone()

    summary = {
        "products": scalar("SELECT COUNT(*) FROM products"),
        "stories": scalar("SELECT COUNT(*) FROM stories"),
        "snapshots": scalar("SELECT COUNT(*) FROM snapshots"),
        "events": scalar("SELECT COUNT(*) FROM change_events"),
        "unseen_components": scalar(
            "SELECT COUNT(*) FROM components WHERE source='discovered'"),
        "manufacturers": scalar("SELECT COUNT(*) FROM manufacturers"),
        "pending_notifications": scalar(
            "SELECT COUNT(*) FROM notifications WHERE status='pending'"),
        "last_run": (last_run["started_at"] if last_run else None),
    }

    try:
        story_rows = conn.execute(
            "SELECT rule_id, story_key, title, score, manufacturers_json, evidence_json, "
            "score_reasons_json, created_at FROM stories ORDER BY id DESC LIMIT 50"
        ).fetchall()
    except sqlite3.OperationalError:
        story_rows = []  # pre-v3 DB not yet re-crawled; degrade to empty tab
    stories = []
    for r in story_rows:
        stories.append({
            "rule_id": r["rule_id"], "key": r["story_key"], "title": r["title"],
            "score": r["score"], "created_at": r["created_at"],
            "manufacturers": _loads(r["manufacturers_json"], []),
            "evidence": _loads(r["evidence_json"], []),
            "reasons": _loads(r["score_reasons_json"], []),
        })

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "summary": summary,
        "events": events,
        "components": components,
        "manufacturers": manufacturers,
        "runs": runs,
        "stories": stories,
    }

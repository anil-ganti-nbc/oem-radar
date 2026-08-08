"""Dashboard data layer (M12). Pure read-only queries over the SQLite DB;
returns plain JSON-serializable dicts so it is trivially testable and the
render layer needs no DB knowledge. No writes, no migration — opens the DB
read-only (safe during a live crawl)."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from ..providers.sqlite import product_from_snapshot_row
from ..core.feedback_analytics import compute_summary
from ..core.models import (
    EVIDENCE_CHANGE_TYPES,
    EVIDENCE_PRODUCT_KEY_PREFIX,
    EXCLUDE_BASELINE_EVENTS_SQL,
)

# The one SQL predicate for "this is a product alert". Everything that
# renders or counts the alert stream goes through it, so the definition
# cannot drift between the events list, the summary counters and the type
# filter. Belt and braces: schema v7 physically moves evidence rows out of
# change_events, but a DB that hasn't migrated yet still reads clean.
_PRODUCT_EVENTS_WHERE = (
    "e.change_type NOT IN ({}) AND e.product_key NOT LIKE '{}%'".format(
        ",".join(f"'{t}'" for t in sorted(EVIDENCE_CHANGE_TYPES)),
        EVIDENCE_PRODUCT_KEY_PREFIX,
    )
)

# The default "All changes" / Alerts view, and everything counted from it,
# excludes baseline events on top of the product/evidence split above: a
# baseline event is a real product alert, but it was generated because a
# source was crawled for the first time, not because anything actually
# changed -- 1,875 of them appearing to be "1,875 fresh discoveries" the
# first time the dashboard was opened against Epoch 2 is exactly the
# failure this predicate exists to prevent. Diagnostics (summary
# ["baseline_events"], GET /api/baseline-events) use _PRODUCT_EVENTS_WHERE
# alone, without this addition, so baseline events are never actually
# hidden -- just excluded from the view that would otherwise misread them
# as new signal.
_DEFAULT_EVENTS_WHERE = f"{_PRODUCT_EVENTS_WHERE} AND {EXCLUDE_BASELINE_EVENTS_SQL}"


def _loads(s, default=None):
    try:
        return json.loads(s) if s else default
    except (TypeError, json.JSONDecodeError):
        return default


def collect_oem_registry(conn: sqlite3.Connection) -> list[dict]:
    """The authoritative OEM list for every manufacturer control in the UI.

    Reads `manufacturers` — which `core.runner.sync_oem_registry` keeps in
    step with `config/oems/*.yaml` — and never a LIMIT-bounded, filtered or
    event-derived set. This is the *only* place the dashboard learns which
    OEMs exist; the filter dropdown and the Manufacturers tab both consume
    its output, so they can never disagree.
    """
    rows = conn.execute(
        "SELECT m.name, COUNT(DISTINCT p.id) AS products "
        "FROM manufacturers m LEFT JOIN products p ON p.manufacturer_id = m.id "
        "GROUP BY m.id ORDER BY m.name COLLATE NOCASE"
    ).fetchall()
    return [{"name": r["name"], "products": r["products"]} for r in rows]


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

    # ---- product change events (the heart of the view) ----
    # Product changes only — evidence has its own stream and its own tab.
    # Review join is optional: older DBs without alert_reviews still work.
    try:
        event_rows = conn.execute(
            "SELECT e.id, e.product_key, e.change_type, e.field, e.old_value_json, "
            "e.new_value_json, e.severity, e.meta_json, e.detected_at, "
            "n.status AS notif_status, r.outcome AS review_outcome "
            "FROM change_events e "
            "LEFT JOIN notifications n ON n.change_event_id = e.id "
            "LEFT JOIN alert_reviews r ON r.alert_id = e.id "
            f"WHERE {_DEFAULT_EVENTS_WHERE} "
            "ORDER BY e.detected_at DESC, e.id DESC LIMIT ?", (limit,),
        ).fetchall()
    except sqlite3.OperationalError:
        event_rows = conn.execute(
            "SELECT e.id, e.product_key, e.change_type, e.field, e.old_value_json, "
            "e.new_value_json, e.severity, e.meta_json, e.detected_at, "
            "n.status AS notif_status "
            "FROM change_events e "
            "LEFT JOIN notifications n ON n.change_event_id = e.id "
            f"WHERE {_DEFAULT_EVENTS_WHERE} "
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
            "review_outcome": (r["review_outcome"] if "review_outcome" in r.keys() else None),
            "review_status": (
                (r["review_outcome"] if "review_outcome" in r.keys() and r["review_outcome"] else None)
                or "UNREVIEWED"
            ),
        })

    # ---- unseen / discovered hardware feed ----
    comp_rows = conn.execute(
        "SELECT kind, canonical_name, first_raw, source, first_seen_at "
        "FROM components WHERE source = 'discovered' "
        "ORDER BY first_seen_at DESC, id DESC LIMIT 100"
    ).fetchall()
    components = [dict(r) for r in comp_rows]

    # ---- manufacturers: the one authoritative OEM registry read ----
    manufacturers = collect_oem_registry(conn)

    # ---- change-type registry: every product change type ever recorded,
    # unbounded. Also not derived from the visible event window, for the
    # same reason the OEM list isn't. ----
    change_types = [
        r["change_type"] for r in conn.execute(
            "SELECT DISTINCT e.change_type FROM change_events e "
            f"WHERE {_DEFAULT_EVENTS_WHERE} ORDER BY e.change_type"
        ).fetchall()
    ]

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
            "health": stats.get("health"),
            "health_reason": stats.get("health_reason"),
        })

    # ---- collector health: most recent run per enabled source ----
    collector_health = []
    for r in runs:
        if r["health"] is None:
            continue
        existing = next((c for c in collector_health if c["source"] == r["source"]), None)
        if existing is None:
            collector_health.append({
                "source": r["source"], "health": r["health"],
                "health_reason": r["health_reason"], "checked_at": r["started_at"],
            })
    # runs are already ordered most-recent-first, so the first hit per
    # source above is the latest — no separate ORDER BY needed here.

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
        "events": scalar(
            f"SELECT COUNT(*) FROM change_events e WHERE {_DEFAULT_EVENTS_WHERE}"),
        "baseline_events": scalar(
            f"SELECT COUNT(*) FROM change_events e WHERE {_PRODUCT_EVENTS_WHERE} "
            f"AND NOT ({EXCLUDE_BASELINE_EVENTS_SQL})"),
        "evidence_items": scalar("SELECT COUNT(*) FROM evidence_items"),
        "unseen_components": scalar(
            "SELECT COUNT(*) FROM components WHERE source='discovered'"),
        "manufacturers": scalar("SELECT COUNT(*) FROM manufacturers"),
        "pending_notifications": scalar(
            "SELECT COUNT(*) FROM notifications WHERE status='pending'"),
        "unreviewed_events": scalar(
            "SELECT COUNT(*) FROM change_events e "
            f"WHERE {_DEFAULT_EVENTS_WHERE} AND "
            "NOT EXISTS (SELECT 1 FROM alert_reviews r WHERE r.alert_id = e.id)"),
        "enabled_sources": scalar("SELECT COUNT(*) FROM sources WHERE enabled=1"),
        "last_run": (last_run["started_at"] if last_run else None),
    }

    # ---- feedback / review analytics (reuses core.feedback_analytics; no
    # metric math duplicated here) ----
    try:
        feedback_summary = compute_summary(conn)
    except sqlite3.OperationalError:
        feedback_summary = None  # pre-v4 DB, no alert_reviews table yet

    summary["proposed_suggestions"] = scalar(
        "SELECT COUNT(*) FROM rule_suggestions WHERE status='PROPOSED'")
    summary["degraded_collectors"] = sum(
        1 for c in collector_health if c["health"] == "degraded")
    summary["failed_collectors"] = sum(
        1 for c in collector_health if c["health"] == "failed")

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

    # ---- evidence (Stage 11: alternate official-source intelligence) ----
    # Optional table — a dashboard opened read-only against a pre-v6 DB
    # (never crawled since the migration landed) simply shows none, same
    # convention as the alert_reviews fallback above.
    try:
        evidence_rows = conn.execute(
            "SELECT id, source_id, manufacturer, evidence_kind, provenance, canonical_url, "
            "external_id, model, family, title, description, observed_at, published_at, "
            "confidence FROM evidence_items ORDER BY observed_at DESC LIMIT 200"
        ).fetchall()
    except sqlite3.OperationalError:
        evidence_rows = []
    # Latest observation per item, one query rather than one per row.
    # Missing on a pre-v7 DB, which just means "no event history yet".
    last_events: dict[int, sqlite3.Row] = {}
    if evidence_rows:
        try:
            last_events = {
                r["evidence_item_id"]: r for r in conn.execute(
                    "SELECT evidence_item_id, event_type, detected_at FROM evidence_events "
                    "WHERE id IN (SELECT MAX(id) FROM evidence_events GROUP BY evidence_item_id)"
                ).fetchall()
            }
        except sqlite3.OperationalError:
            last_events = {}
    evidence_items = []
    for r in evidence_rows:
        link = conn.execute(
            "SELECT product_key, method FROM evidence_links WHERE evidence_item_id=? LIMIT 1",
            (r["id"],),
        ).fetchone()
        last = last_events.get(r["id"])
        evidence_items.append({
            "last_event": (last["event_type"] if last else None),
            "last_event_at": (last["detected_at"] if last else None),
            "id": r["id"],
            "source_id": r["source_id"],
            "manufacturer": r["manufacturer"],
            "evidence_kind": r["evidence_kind"],
            "provenance": r["provenance"],
            "canonical_url": r["canonical_url"],
            "external_id": r["external_id"],
            "model": r["model"],
            "family": r["family"],
            "title": r["title"],
            "description": r["description"],
            "observed_at": r["observed_at"],
            "published_at": r["published_at"],
            "confidence": r["confidence"],
            "linked_product_key": link["product_key"] if link else None,
            "link_method": link["method"] if link else None,
        })

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "summary": summary,
        "events": events,
        "components": components,
        "manufacturers": manufacturers,
        "change_types": change_types,
        "runs": runs,
        "stories": stories,
        "collector_health": collector_health,
        "feedback_summary": feedback_summary,
        "evidence_items": evidence_items,
    }


def collect_baseline_events(conn: sqlite3.Connection, limit: int = 2000) -> list[dict]:
    """Diagnostics-only list of events excluded from the default alert
    view because they were produced by a source's first-ever crawl
    (GET /api/baseline-events). Deliberately a separate, smaller shape
    from `collect()`'s event dicts -- no product brief join, no review
    status -- since this exists for an operator confirming what baseline
    did, not for the journalist-facing card list.
    """
    rows = conn.execute(
        "SELECT e.id, e.product_key, e.change_type, e.severity, e.detected_at "
        "FROM change_events e "
        f"WHERE {_PRODUCT_EVENTS_WHERE} AND NOT ({EXCLUDE_BASELINE_EVENTS_SQL}) "
        "ORDER BY e.detected_at DESC, e.id DESC LIMIT ?", (limit,),
    ).fetchall()
    return [
        {
            "id": r["id"], "product_key": r["product_key"],
            "type": r["change_type"], "severity": r["severity"],
            "detected_at": r["detected_at"],
        }
        for r in rows
    ]


def collect_evidence_detail(conn: sqlite3.Connection, evidence_id: int) -> dict | None:
    """Full payload for GET /evidence/{id}.

    Every row the Evidence tab renders resolves here, so nothing in that
    table is a dead card. Deliberately *not* shaped like an alert detail:
    no severity, no review, no HIT/NOISE — an evidence item is a record
    that an official source says something exists, not a claim that a
    tracked product changed."""
    try:
        row = conn.execute(
            "SELECT * FROM evidence_items WHERE id = ?", (evidence_id,)
        ).fetchone()
    except sqlite3.OperationalError:
        return None  # pre-v6 DB: no evidence subsystem at all
    if row is None:
        return None

    prev_row = conn.execute(
        "SELECT id FROM evidence_items WHERE id < ? ORDER BY id DESC LIMIT 1", (evidence_id,)
    ).fetchone()
    next_row = conn.execute(
        "SELECT id FROM evidence_items WHERE id > ? ORDER BY id ASC LIMIT 1", (evidence_id,)
    ).fetchone()

    links = []
    brief_cache: dict = {}
    for lr in conn.execute(
        "SELECT product_key, method, confidence, created_at FROM evidence_links "
        "WHERE evidence_item_id=? ORDER BY id", (evidence_id,),
    ).fetchall():
        b = _latest_product_brief(conn, lr["product_key"], brief_cache) if lr["product_key"] else {}
        links.append({
            "product_key": lr["product_key"],
            "method": lr["method"],
            "confidence": lr["confidence"],
            "created_at": lr["created_at"],
            "model": b.get("model"),
            "manufacturer": b.get("manufacturer"),
            "url": b.get("url"),
        })

    history = []
    try:
        for h in conn.execute(
            "SELECT event_type, detected_at, meta_json FROM evidence_events "
            "WHERE evidence_item_id=? ORDER BY id ASC", (evidence_id,),
        ).fetchall():
            history.append({
                "event_type": h["event_type"],
                "detected_at": h["detected_at"],
                "meta": _loads(h["meta_json"], {}),
            })
    except sqlite3.OperationalError:
        pass  # pre-v7 DB

    keys = row.keys()
    return {
        "id": row["id"],
        "source_id": row["source_id"],
        "manufacturer": row["manufacturer"],
        "evidence_kind": row["evidence_kind"],
        "provenance": row["provenance"],
        "canonical_url": row["canonical_url"],
        "external_id": row["external_id"],
        "model": row["model"],
        "sku": row["sku"],
        "mpn": row["mpn"],
        "family": row["family"],
        "title": row["title"],
        "description": row["description"],
        "version": row["version"],
        "filename": row["filename"],
        "region": row["region"],
        "published_at": row["published_at"],
        "observed_at": row["observed_at"],
        "confidence": row["confidence"],
        "content_hash": (row["content_hash"] if "content_hash" in keys else None),
        "raw_data": _loads(row["raw_data_json"] if "raw_data_json" in keys else None, {}),
        "links": links,
        "history": history,
        "prev_id": (prev_row["id"] if prev_row else None),
        "next_id": (next_row["id"] if next_row else None),
    }


def collect_alert_detail(conn: sqlite3.Connection, alert_id: int) -> dict | None:
    """Full payload for GET /alerts/{id} and GET /api/alerts/{id}/review."""
    row = conn.execute(
        "SELECT e.id, e.product_key, e.change_type, e.field, e.old_value_json, "
        "e.new_value_json, e.severity, e.meta_json, e.detected_at "
        "FROM change_events e WHERE e.id = ?",
        (alert_id,),
    ).fetchone()
    if row is None:
        return None

    prev_row = conn.execute(
        "SELECT id FROM change_events WHERE id < ? ORDER BY id DESC LIMIT 1", (alert_id,)
    ).fetchone()
    next_row = conn.execute(
        "SELECT id FROM change_events WHERE id > ? ORDER BY id ASC LIMIT 1", (alert_id,)
    ).fetchone()

    brief_cache: dict = {}
    b = _latest_product_brief(conn, row["product_key"], brief_cache)
    meta = _loads(row["meta_json"], {})

    # Source / collector from product_key prefix and sources table when possible.
    source_key = row["product_key"].split(":", 1)[0] if row["product_key"] else None
    source_row = None
    if source_key:
        source_row = conn.execute(
            "SELECT source_key, engine, base_url FROM sources WHERE source_key=?",
            (source_key,),
        ).fetchone()

    # Related previous events: same product_key, older than this one.
    related = []
    rel_rows = conn.execute(
        "SELECT id, change_type, field, severity, detected_at, old_value_json, new_value_json "
        "FROM change_events WHERE product_key=? AND id < ? "
        "ORDER BY id DESC LIMIT 10",
        (row["product_key"], alert_id),
    ).fetchall()
    for rr in rel_rows:
        related.append({
            "id": rr["id"],
            "type": rr["change_type"],
            "field": rr["field"],
            "severity": rr["severity"],
            "detected_at": rr["detected_at"],
            "old": _loads(rr["old_value_json"]),
            "new": _loads(rr["new_value_json"]),
        })

    # Current review + history via store-shaped dicts (read-only SQL here).
    review = None
    history: list[dict] = []
    try:
        rev = conn.execute(
            "SELECT * FROM alert_reviews WHERE alert_id=?", (alert_id,)
        ).fetchone()
        if rev:
            from ..core.feedback import reasons_from_json
            review = {
                "id": rev["id"],
                "alert_id": rev["alert_id"],
                "outcome": rev["outcome"],
                "reason_codes": reasons_from_json(rev["reason_codes_json"]),
                "reviewer_note": rev["reviewer_note"],
                "reviewed_at": rev["reviewed_at"],
                "reviewer": rev["reviewer"],
                "created_at": rev["created_at"],
                "updated_at": rev["updated_at"],
            }
        hist_rows = conn.execute(
            "SELECT * FROM alert_review_history WHERE alert_id=? "
            "ORDER BY changed_at ASC, id ASC",
            (alert_id,),
        ).fetchall()
        from ..core.feedback import reasons_from_json as _rfj
        for h in hist_rows:
            history.append({
                "id": h["id"],
                "alert_id": h["alert_id"],
                "previous_outcome": h["previous_outcome"],
                "new_outcome": h["new_outcome"],
                "previous_reason_codes": _rfj(h["previous_reason_codes_json"]),
                "new_reason_codes": _rfj(h["new_reason_codes_json"]),
                "changed_at": h["changed_at"],
                "changed_by": h["changed_by"],
                "change_note": h["change_note"],
            })
    except sqlite3.OperationalError:
        pass  # pre-v4 DB

    return {
        "id": row["id"],
        "product_key": row["product_key"],
        "type": row["change_type"],
        "field": row["field"],
        "old": _loads(row["old_value_json"]),
        "new": _loads(row["new_value_json"]),
        "severity": row["severity"],
        "meta": meta,
        "detected_at": row["detected_at"],
        "manufacturer": b.get("manufacturer"),
        "model": b.get("model"),
        "cpu": b.get("cpu"),
        "gpu": b.get("gpu"),
        "memory": b.get("memory"),
        "storage": b.get("storage"),
        "price": b.get("price"),
        "region": b.get("region"),
        "image": b.get("image"),
        "url": b.get("url"),
        "confidence": b.get("confidence"),
        "sku": b.get("sku") if "sku" in b else None,
        "collector": source_key,
        "engine": (source_row["engine"] if source_row else None),
        "source_base_url": (source_row["base_url"] if source_row else None),
        "related_events": related,
        "review": review,
        "history": history,
        "review_status": (review["outcome"] if review else "UNREVIEWED"),
        "prev_id": (prev_row["id"] if prev_row else None),
        "next_id": (next_row["id"] if next_row else None),
    }

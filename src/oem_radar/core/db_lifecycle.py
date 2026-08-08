"""Reusable primitives for the database-archive-and-reset procedure in
docs/DATABASE_LIFECYCLE.md. Deliberately small: this codifies the two
checks that are easy to get subtly wrong by hand (an integrity audit
that reports every fact instead of just the pass/fail bit, and a
manifest-vs-file cross-check) rather than a full one-shot automation
script. The 2026-08-08 Epoch 1 -> Epoch 2 cutover ran these by hand
once, with full rigor; this exists so the next one doesn't have to
re-derive the same PRAGMA calls from scratch.

Not exposed in the dashboard or the CLI on purpose — this touches
files, not the running application, and the archive/reset sequence is a
reasoned human decision each time, not something to automate behind a
button.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ..providers.sqlite import connect_readonly

# The application's own operational tables (core/schema.sql), not
# counting schema_migrations itself — that table is expected to be
# non-empty (one row per applied migration) even on a fresh database.
OPERATIONAL_TABLES: tuple[str, ...] = (
    "alert_review_history", "alert_reviews", "aliases", "change_events",
    "components", "crawler_runs", "evidence_events", "evidence_items",
    "evidence_links", "listings", "manufacturers", "notifications",
    "prices", "products", "rule_suggestions", "run_errors", "snapshots",
    "sources", "stories",
)


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def integrity_report(db_path: str | Path) -> dict:
    """A read-only audit of a SQLite database: integrity, foreign keys,
    schema version, and a row count per known table. Never opens the
    file read-write, so it is safe to run against a live database mid-
    crawl (WAL mode) or against an archived one.

    Missing tables are reported as `None`, not raised on — a pre-v7
    database audited with this function should say what it's missing,
    not crash.
    """
    conn = connect_readonly(str(db_path))
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        fk_violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        schema_version = conn.execute(
            "SELECT COALESCE(MAX(version), 0) v FROM schema_migrations"
        ).fetchone()["v"]
        row_counts = {}
        for table in OPERATIONAL_TABLES:
            try:
                row_counts[table] = conn.execute(
                    f"SELECT COUNT(*) c FROM {table}"
                ).fetchone()["c"]
            except Exception:  # noqa: BLE001 — table absent on an old schema
                row_counts[table] = None
        return {
            "integrity_check": integrity,
            "foreign_key_violations": len(fk_violations),
            "schema_version": schema_version,
            "row_counts": row_counts,
            "sha256": sha256_file(db_path),
        }
    finally:
        conn.close()


def verify_archive(archive_db_path: str | Path, manifest_path: str | Path) -> list[str]:
    """Cross-check an archived database against its own manifest.

    Returns a list of problems; an empty list means the archive matches
    what its manifest claims. Never raises on a mismatch — a cutover
    script should decide what to do about a failed verification, this
    function just reports facts.
    """
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    problems: list[str] = []

    report = integrity_report(archive_db_path)

    if report["integrity_check"] != "ok":
        problems.append(f"integrity_check={report['integrity_check']!r}, expected 'ok'")
    if report["foreign_key_violations"]:
        problems.append(f"{report['foreign_key_violations']} foreign_key_check violation(s)")
    if report["sha256"] != manifest.get("sha256"):
        problems.append(
            f"sha256 mismatch: file={report['sha256']} manifest={manifest.get('sha256')}"
        )
    if report["schema_version"] != manifest.get("schema_version"):
        problems.append(
            f"schema_version mismatch: file={report['schema_version']} "
            f"manifest={manifest.get('schema_version')}"
        )
    expected_counts = manifest.get("row_counts", {})
    for table, expected in expected_counts.items():
        got = report["row_counts"].get(table)
        if got != expected:
            problems.append(f"{table}: expected {expected} rows, found {got}")

    return problems


def assert_all_operational_tables_empty(db_path: str | Path) -> list[str]:
    """For verifying a freshly-reset database. Returns the list of
    (table, count) pairs that are unexpectedly non-empty; empty list
    means the reset is clean. `schema_migrations` is intentionally not
    checked here — it is expected to be populated on any valid schema."""
    report = integrity_report(db_path)
    return [f"{t}: {c} row(s)" for t, c in report["row_counts"].items() if c]

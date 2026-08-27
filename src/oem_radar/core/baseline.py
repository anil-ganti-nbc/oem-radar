"""Baseline archive / reset machinery (campaign deliverable H).

Pipeline:

    old authoritative radar.db
      -> export_baseline()  : immutable, hashed identity archive on disk
      -> import_baseline()  : fresh operational DB seeded with the known
                              identity universe (products, listings,
                              latest snapshot per listing, aliases)

CRITICAL INVARIANT (tested): everything imported from the archive starts
life as *known*.  A post-cutover crawl of an imported URL with unchanged
content hits the pipeline's hash-dedup path (store.latest().content_hash()
== incoming.content_hash()) and produces ZERO events -- no FIRST_SEEN /
NEW_SKU flood. Only genuinely new hardware after cutover becomes news.

The archive is read-only by construction: manifest carries sha256 for every
part; verify_archive() refuses to operate from a corrupted/mutated archive.
The local dev epoch of 2026-08-25 is NOT canonical; the exporter is meant
to run once against the recovered Hetzner DB.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from base64 import b64decode, b64encode
from datetime import datetime, timezone
from pathlib import Path

MANIFEST = "manifest.json"
IDENTITY_PARTS = (
    "manufacturers.jsonl",
    "sources.jsonl",
    "products.jsonl",
    "listings.jsonl",
    "aliases.jsonl",
    "latest_snapshots.jsonl",
)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _rows(db: sqlite3.Connection, sql: str) -> list[dict]:
    db.row_factory = sqlite3.Row
    return [_encode_row(dict(r)) for r in db.execute(sql)]


def _encode_row(row: dict) -> dict:
    """BLOB columns (normalized_zjson) -> base64 strings for JSONL."""
    out = {}
    for k, v in row.items():
        if isinstance(v, bytes):
            out[k] = {"__b64__": b64encode(v).decode("ascii")}
        else:
            out[k] = v
    return out


def _decode_row(row: dict) -> dict:
    out = {}
    for k, v in row.items():
        if isinstance(v, dict) and set(v) == {"__b64__"}:
            out[k] = b64decode(v["__b64__"])
        else:
            out[k] = v
    return out


def export_baseline(db_path: str | Path, out_dir: str | Path) -> dict:
    """Export the identity universe; never mutates the source DB."""
    src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    out = Path(out_dir)
    if out.exists():
        raise FileExistsError(f"archive dir already exists: {out}")
    out.mkdir(parents=True)
    try:
        migrations = [r[0] for r in src.execute(
            "SELECT version FROM schema_migrations ORDER BY version")]

        parts_sql = {
            "manufacturers.jsonl": "SELECT * FROM manufacturers ORDER BY id",
            "sources.jsonl": "SELECT * FROM sources ORDER BY id",
            "products.jsonl": "SELECT * FROM products ORDER BY id",
            "listings.jsonl": "SELECT * FROM listings ORDER BY id",
            "aliases.jsonl": "SELECT * FROM aliases ORDER BY id",
            # Latest snapshot per listing only: full history stays in the
            # archived DB itself; a fresh operational DB needs exactly one
            # prior snapshot per listing to dedupe correctly.
            "latest_snapshots.jsonl": """
                SELECT s.* FROM snapshots s
                JOIN (SELECT listing_id, MAX(id) AS mid FROM snapshots GROUP BY listing_id) m
                  ON m.mid = s.id
                ORDER BY s.id""",
        }
        counts: dict[str, int] = {}
        for name, sql in parts_sql.items():
            rows = _rows(src, sql)
            counts[name] = len(rows)
            with open(out / name, "w", encoding="utf-8") as fh:
                for row in rows:
                    fh.write(json.dumps(row, sort_keys=True) + "\n")

        manifest = {
            "archived_at_utc": datetime.now(timezone.utc).isoformat(),
            "source_db_path": str(db_path),
            "source_sha256": _sha256_file(Path(db_path)),
            "schema_migrations": migrations,
            "counts": counts,
            "parts_sha256": {n: _sha256_file(out / n) for n in IDENTITY_PARTS},
        }
        (out / MANIFEST).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return manifest
    finally:
        src.close()


def verify_archive(archive_dir: str | Path) -> bool:
    """Recompute every part hash against the manifest (immutability gate)."""
    arc = Path(archive_dir)
    manifest = json.loads((arc / MANIFEST).read_text(encoding="utf-8"))
    for name, expected in manifest["parts_sha256"].items():
        part = arc / name
        if not part.exists() or _sha256_file(part) != expected:
            return False
    return True


_SCHEMA_SQL = (Path(__file__).resolve().parent.parent / "providers" / "sqlite" / "schema.sql")


def _init_fresh_db(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA_SQL.read_text(encoding="utf-8"))


def import_baseline(archive_dir: str | Path, target_db_path: str | Path) -> dict:
    """Create/extend `target_db_path` with the archived identity universe.

    Idempotent: rows are merged via INSERT OR IGNORE keyed on existing unique
    constraints, so re-running against an already-seeded DB is a no-op whose
    counts match the manifest. Never deletes anything in the target.
    """
    if not verify_archive(archive_dir):
        raise ValueError("archive failed immutability verification")
    arc = Path(archive_dir)
    target = Path(target_db_path)
    fresh = not target.exists()
    conn = sqlite3.connect(target)
    try:
        _init_fresh_db(conn)
        stats: dict[str, int] = {}

        def load(name: str) -> list[dict]:
            return [_decode_row(json.loads(line)) for line in
                    (arc / name).read_text(encoding="utf-8").splitlines()]

        def insert(table: str, name: str, cols: tuple[str, ...]) -> None:
            rows = load(name)
            placeholders = ",".join("?" for _ in cols)
            stmt = (f"INSERT OR IGNORE INTO {table} ({','.join(cols)}) "
                    f"VALUES ({placeholders})")
            cur = conn.executemany(stmt, [[r.get(c) for c in cols] for r in rows])
            stats[name] = len(rows)
            conn.commit()

        insert("manufacturers", "manufacturers.jsonl",
               ("id", "name", "country", "aliases_json", "created_at"))
        insert("sources", "sources.jsonl",
               ("id", "source_key", "manufacturer_id", "engine", "base_url",
                "config_json", "enabled", "created_at"))
        insert("products", "products.jsonl",
               ("id", "manufacturer_id", "canonical_model", "series",
                "category", "status", "first_seen_at"))
        insert("listings", "listings.jsonl",
               ("id", "source_id", "product_id", "product_key", "url",
                "vendor_handle", "vendor_sku", "region", "resolution_method",
                "resolution_confidence", "needs_review", "first_seen_at",
                "last_seen_at"))
        insert("aliases", "aliases.jsonl",
               ("id", "product_id", "alias", "kind", "created_at"))

        snaps = load("latest_snapshots.jsonl")
        cur = conn.executemany(
            "INSERT OR IGNORE INTO snapshots (id, listing_id, content_hash,"
            " normalized_json, normalized_zjson, confidence,"
            " validation_issues_json, raw_ref, captured_at)"
            " VALUES (:id,:listing_id,:content_hash,:normalized_json,"
            ":normalized_zjson,:confidence,:validation_issues_json,:raw_ref,:captured_at)",
            snaps)
        conn.commit()
        stats["latest_snapshots.jsonl"] = cur.rowcount

        # Stamp migration versions so the store treats schema as current.
        migrations = json.loads(
            (arc / MANIFEST).read_text(encoding="utf-8"))["schema_migrations"]
        conn.executemany(
            "INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)",
            [(v,) for v in migrations])
        conn.commit()

        return {"fresh_database": fresh, **stats}
    finally:
        conn.close()


def count_unseeded_listings(operational_db: str | Path,
                            source_key_prefix: str | None = None) -> int:
    """Listings lacking any snapshot: these WOULD flood as FIRST_SEEN.

    Cutover preflight requires this to be 0 after import.
    """
    conn = sqlite3.connect(f"file:{operational_db}?mode=ro", uri=True)
    try:
        conds: list[str] = []
        params: list = []
        if source_key_prefix:
            conds.append("l.product_key LIKE ?")
            params.append(f"{source_key_prefix}%")
        conds.append("NOT EXISTS (SELECT 1 FROM snapshots s WHERE s.listing_id = l.id)")
        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        row = conn.execute(
            f"SELECT COUNT(*) FROM listings l {where}", tuple(params))
        return int(row.fetchone()[0])
    finally:
        conn.close()


def backup_archive_immutable(archive_dir: str | Path, backup_dir: str | Path) -> None:
    """Copy the archive; flip files to read-only afterwards."""
    dst = Path(backup_dir)
    if dst.exists():
        raise FileExistsError(str(dst))
    shutil.copytree(archive_dir, dst)
    for p in dst.rglob("*"):
        if p.is_file():
            p.chmod(0o444)

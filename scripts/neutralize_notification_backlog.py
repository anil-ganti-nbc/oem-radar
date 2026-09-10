"""Neutralize pending Discord notifications for muted change types.

One-time operator step for the 2026-09-09 notification-policy mute
(availability_changed, images_changed), kept as a re-runnable tool: when
`notify.discord.suppress_change_types` grows, any PENDING rows of the newly
muted types that were enqueued under the old policy must be converted to
`suppressed` BEFORE the next drain, or they would flush to Discord.

What it does, per provider='discord' rows whose linked change_event's
change_type is muted:
  status='pending'  -> status='suppressed', last_error='change_type_suppressed'

What it never touches:
  - `sent` rows (history of real deliveries),
  - `failed` rows (drain() only ever selects 'pending', so a failed row is
    never retried and cannot violate the mute),
  - any other status (`review`, `demoted`, already-`suppressed`),
  - change_events rows (the events themselves stay fully recorded).

Idempotent: a second run finds zero pending muted rows and changes nothing.
The reason is persisted in the existing `last_error` column — no schema
migration. Run between crawls (the crawl lock is not taken here).
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_TYPES = "availability_changed,images_changed"


def muted_types(args: argparse.Namespace) -> list[str]:
    if args.types:
        return [t.strip() for t in args.types.split(",") if t.strip()]
    import yaml
    cfg = yaml.safe_load((Path(args.config)).read_text(encoding="utf-8")) or {}
    discord = (cfg.get("notify") or {}).get("discord") or {}
    return list(discord.get("suppress_change_types") or [])


def counts(db: sqlite3.Connection, types: list[str]) -> list[sqlite3.Row]:
    qs = ",".join("?" * len(types))
    return db.execute(
        f"SELECT e.change_type AS t, n.status AS s, COUNT(*) AS c "
        f"FROM notifications n JOIN change_events e ON e.id = n.change_event_id "
        f"WHERE n.provider='discord' AND e.change_type IN ({qs}) "
        f"GROUP BY e.change_type, n.status ORDER BY e.change_type, n.status",
        types,
    ).fetchall()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default=str(REPO / "data" / "radar.db"))
    ap.add_argument("--config", default=str(REPO / "config" / "radar.yaml"),
                    help="radar.yaml to read suppress_change_types from")
    ap.add_argument("--types", default="",
                    help="comma-separated override for the muted change types")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    types = muted_types(args)
    if not types:
        print("no muted change types configured; nothing to do")
        return 0

    db = sqlite3.connect(args.db)
    db.row_factory = sqlite3.Row
    print(f"muted change types : {types}")
    print(f"database           : {args.db}")
    print("before, rows by (change_type, status):")
    for r in counts(db, types):
        print(f"  {r['t']:<24} {r['s']:<10} {r['c']}")

    qs = ",".join("?" * len(types))
    pending = db.execute(
        f"SELECT COUNT(*) AS c FROM notifications n "
        f"JOIN change_events e ON e.id = n.change_event_id "
        f"WHERE n.provider='discord' AND n.status='pending' "
        f"AND e.change_type IN ({qs})", types,
    ).fetchone()["c"]
    print(f"\npending muted rows to neutralize: {pending}")
    if args.dry_run:
        print("dry run: nothing changed")
        return 0

    cur = db.execute(
        f"UPDATE notifications SET status='suppressed', last_error='change_type_suppressed' "
        f"WHERE status='pending' AND provider='discord' "
        f"AND change_event_id IN (SELECT id FROM change_events WHERE change_type IN ({qs}))",
        types,
    )
    db.commit()
    print(f"neutralized: {cur.rowcount} row(s) -> suppressed (last_error='change_type_suppressed')")

    print("\nafter, rows by (change_type, status):")
    for r in counts(db, types):
        print(f"  {r['t']:<24} {r['s']:<10} {r['c']}")
    remaining = db.execute(
        f"SELECT COUNT(*) AS c FROM notifications n "
        f"JOIN change_events e ON e.id = n.change_event_id "
        f"WHERE n.provider='discord' AND n.status='pending' "
        f"AND e.change_type IN ({qs})", types,
    ).fetchone()["c"]
    print(f"\npending muted rows remaining: {remaining}")
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Separate, on-disk QC/decision archive database for the alert review
queue (`change_events` + the dashboard's Alerts tab).

Modeled on Korean Tech Wire's `storage/qc_archive.py` (itself modeled on
Chinese Tech Wire's LeadOutcome pattern): a physically separate SQLite
file rather than another table in the live collector database. Rationale,
identical to KTW's:

  - The live database (radar.db) is fleet-governed: destructive changes to
    it are prohibited, and any schema migration requires a fresh verified
    backup first. A QC decision ledger in its own file
    (oem_radar_qc.db, created fresh by this module, sibling to radar.db)
    never needs to touch or migrate the live DB's schema at all.
  - A QC decision is a durable editorial/audit record. Archiving a full
    snapshot of the alert (product_key, change_type, old/new value,
    severity, metadata, detected_at) plus its provenance (source_key
    derived from product_key, the alert's own id as its canonical event
    identity) at decision time means the archive stays self-contained --
    readable even if the underlying change_event row is ever pruned.
  - UNIQUE(alert_id) is the race guard: two concurrent QC submissions for
    the same alert can both attempt an INSERT, but only one commits. The
    caller catches AlreadyQCed and treats the second attempt as a no-op,
    so there is never a duplicate archive row or a lost decision.

Fleet-wide QC contract note (Useful / Not useful / False positive / Out of
stock): OEM Radar's alert review queue already had a validated four-value
outcome taxonomy (`core.feedback.ReviewOutcome`) feeding a
rule-suggestion/noise-reduction engine, years before this fleet-wide
contract existed. Reusing it here -- rather than inventing a second,
parallel Useful/Not-useful/False-positive/Out-of-stock vocabulary on the
same alerts -- IS "OEM Radar's own domain-appropriate naming for the same
four decision types":

    HIT         -- Useful:         confirmed, editorially valuable signal
    INTERESTING -- Useful:         worth watching, lower confidence
    NOISE       -- Not useful:     routine/expected change, no editorial value
    BUG         -- False positive: alert should not have fired at all
                   (parser error, entity-match error, bad baseline, ...)

There is no dedicated top-level "Out of stock" outcome because an
availability flip is not a separate verdict axis here -- it is one of many
`change_type`s this queue reviews (`AVAILABILITY_CHANGED`), and "this
alert is just a routine/temporary stock blip, not real signal" is already
a first-class REASON CODE (`ReasonCode.TEMPORARY_STOCK_CHANGE`) a reviewer
can attach to whichever of the four outcomes above actually applies.

"Active queue" filtering (removing a QC'd alert from the dashboard's
default Alerts view) is done by the caller consulting
`archived_alert_ids()` -- the live DB's `change_events` table and
`alert_reviews` are never mutated by archiving. `alert_reviews` keeps
recording the reviewer's *current* outcome (revisable, feeding the
rule-suggestion engine, unaffected by this module); this archive records
only the *first* terminal decision that took the alert out of the active
queue, which is also exactly what makes a restart safe (SQLite-on-disk, no
in-memory state).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# OEM Radar's own domain-appropriate terminal QC vocabulary -- see module
# docstring above for the mapping onto the fleet's Useful / Not useful /
# False positive / Out of stock contract.
QC_DECISIONS = ("HIT", "INTERESTING", "NOISE", "BUG")

ARCHIVE_FILENAME = "oem_radar_qc.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS qc_decisions (
    id INTEGER PRIMARY KEY,
    alert_id INTEGER NOT NULL UNIQUE,
    product_key TEXT NOT NULL,
    source_key TEXT,
    change_type TEXT NOT NULL,
    field TEXT,
    old_value_json TEXT,
    new_value_json TEXT,
    severity INTEGER,
    meta_json TEXT,
    detected_at TEXT,
    decision TEXT NOT NULL,
    reason_codes_json TEXT NOT NULL DEFAULT '[]',
    note TEXT,
    decided_at TEXT NOT NULL,
    decided_by TEXT
);
CREATE INDEX IF NOT EXISTS qc_decisions_decided_at_idx ON qc_decisions(decided_at DESC);
CREATE INDEX IF NOT EXISTS qc_decisions_source_idx ON qc_decisions(source_key);
"""


def _iso(value: datetime | None = None) -> str:
    return (value or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()


def source_key_of(product_key: str) -> str | None:
    """product_key is '<source_key>:<handle>' (see schema.sql `listings`
    comment) -- cheap provenance without an extra join."""
    if not product_key or ":" not in product_key:
        return None
    return product_key.split(":", 1)[0]


class AlreadyQCed(Exception):
    """Raised when an alert already has an archived QC decision (a race,
    or a resubmission after the alert already left the active queue)."""


class QCArchive:
    """A separate, append-only ledger of alert-review QC decisions."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        con.executescript(_SCHEMA)
        return con

    def archived_alert_ids(self) -> set[int]:
        with self.connect() as con:
            return {row[0] for row in con.execute("SELECT alert_id FROM qc_decisions")}

    def decision_for(self, alert_id: int) -> sqlite3.Row | None:
        with self.connect() as con:
            return con.execute(
                "SELECT * FROM qc_decisions WHERE alert_id=?", (alert_id,)
            ).fetchone()

    def archive(
        self,
        event: sqlite3.Row | dict,
        decision: str,
        *,
        reason_codes: list[str] | None = None,
        note: str | None = None,
        decided_by: str | None = None,
    ) -> None:
        """Transactionally archive one alert's full snapshot + provenance
        and record the QC decision. Raises AlreadyQCed if this alert_id
        already has a row -- never a silent duplicate, never a crash."""
        if decision not in QC_DECISIONS:
            raise ValueError(f"unknown QC decision: {decision!r}")
        event = dict(event)
        import json as _json
        try:
            with self.connect() as con:
                con.execute(
                    "INSERT INTO qc_decisions(alert_id, product_key, source_key, "
                    "change_type, field, old_value_json, new_value_json, severity, "
                    "meta_json, detected_at, decision, reason_codes_json, note, "
                    "decided_at, decided_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        event["id"], event["product_key"],
                        source_key_of(event.get("product_key")),
                        event["change_type"], event.get("field"),
                        event.get("old_value_json"), event.get("new_value_json"),
                        event.get("severity"), event.get("meta_json"),
                        event.get("detected_at"), decision,
                        _json.dumps(list(reason_codes or []), separators=(",", ":")),
                        note, _iso(), decided_by,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise AlreadyQCed(
                f"alert {event.get('id')} already has an archived QC decision"
            ) from exc

    def recent(self, limit: int = 50) -> list[sqlite3.Row]:
        with self.connect() as con:
            return con.execute(
                "SELECT * FROM qc_decisions ORDER BY decided_at DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()

    def status(self) -> dict:
        with self.connect() as con:
            total = con.execute("SELECT COUNT(*) FROM qc_decisions").fetchone()[0]
            by_decision = {
                row["decision"]: row["n"] for row in con.execute(
                    "SELECT decision, COUNT(*) AS n FROM qc_decisions GROUP BY decision"
                )
            }
        return {"total": total, **by_decision}

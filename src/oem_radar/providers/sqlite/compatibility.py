"""Persistent-state compatibility inspection for the OEM Radar store.

M15 / STD-DEPLOY-COM-002, second validation of the current-schema /
bootstrap SQLite family (the first was Feature Phone M14; only the
contract is shared — this module is OEM Radar's own implementation).

The invariant: normal work must not begin against persistent state until
the running software has established that the state is compatible. The
pre-M15 defect was that `SqliteStore.__init__` ran `migrate()`
unconditionally, and `migrate()` executed the full current `schema.sql`
*before* even classifying the database, then stamped the version marker,
then swallowed "duplicate column" migration errors — so ordinary
construction could mutate state before compatibility was established,
launder a marker-less existing database into "current", silently accept a
newer v8+ database (zero migrations remained to run, so nothing failed),
and bless contradictory state by suppressing the very error that exposed
it. Version skew was therefore unguarded in every direction.

The schema authority is the durable `schema_migrations` marker, corroborated
structurally: a marker claiming the expected version must coexist with every
table the current schema defines (TABLE_EXISTS != COMPATIBLE; a missing one
means PARTIAL). Inspection is strictly read-only — quick_check,
sqlite_master, and table_info reads; it never stamps, migrates, or repairs.

Skew contract: FORWARD_ONLY_EXPLICIT. State moves forward only through this
software's own canonical migrations; a newer database (v8+ for software
expecting v7) fails closed because additive migrations do not prove backward
compatibility. No downgrade path exists, is implied, or is invented.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from enum import Enum

# The expected persistent-state contract of THIS software version. Single
# source of truth; `providers.sqlite` re-exports it as SCHEMA_VERSION so the
# schema, the migrations, and the compatibility gate cannot drift apart.
EXPECTED_SCHEMA_VERSION = 7

# Every table the current schema (schema.sql + applied migrations at this
# version) must have left behind: the 19 operational tables catalogued in
# core/db_lifecycle.py plus the marker itself. A marker claiming the
# expected version with any of these missing is PARTIAL.
EXPECTED_TABLES = frozenset({
    "schema_migrations",
    "alert_review_history", "alert_reviews", "aliases", "change_events",
    "components", "crawler_runs", "evidence_events", "evidence_items",
    "evidence_links", "listings", "manufacturers", "notifications",
    "prices", "products", "rule_suggestions", "run_errors", "snapshots",
    "sources", "stories",
})


class SchemaCompatibility(str, Enum):
    """Adjudication verdicts. FRESH != UNKNOWN; DB_OPEN_SUCCESS !=
    COMPATIBLE; TABLE_EXISTS != COMPATIBLE; MIGRATION_CAN_RUN != COMPATIBLE."""

    FRESH = "FRESH"
    MIGRATION_REQUIRED = "MIGRATION_REQUIRED"
    COMPATIBLE = "COMPATIBLE"
    INCOMPATIBLE_NEWER = "INCOMPATIBLE_NEWER"
    UNKNOWN = "UNKNOWN"
    CORRUPT = "CORRUPT"
    PARTIAL = "PARTIAL"


# Verdicts that can never be admitted to normal work, and that mark health
# as degraded when observed read-only. (FRESH bootstraps canonically;
# MIGRATION_REQUIRED migrates canonically — neither is "bad" state.)
UNADMITTABLE_STATES = frozenset({
    SchemaCompatibility.INCOMPATIBLE_NEWER,
    SchemaCompatibility.UNKNOWN,
    SchemaCompatibility.PARTIAL,
    SchemaCompatibility.CORRUPT,
})


@dataclass(frozen=True)
class CompatibilityReport:
    """Read-only verdict on one persistent store, with the evidence that
    produced it. `as_evidence()` is the machine-readable refusal record."""

    state: SchemaCompatibility
    expected_version: int
    observed_version: int | None
    reason: str
    evidence: dict = field(default_factory=dict)

    def as_evidence(self) -> dict:
        return {
            "compatibility_state": self.state.value,
            "expected_schema_version": self.expected_version,
            "observed_schema_version": self.observed_version,
            "reason": self.reason,
            **self.evidence,
        }

    def __str__(self) -> str:
        return (
            f"{self.state.value}: {self.reason} "
            f"(expected schema v{self.expected_version}, "
            f"observed {'none' if self.observed_version is None else f'v{self.observed_version}'})"
        )


class IncompatibleDatabaseError(RuntimeError):
    """Raised when a store is refused because its persistent state is not
    (or not yet) compatible with this software. `.report` carries the full
    read-only evidence; the database was not mutated by the refusal."""

    def __init__(self, report: CompatibilityReport) -> None:
        super().__init__(
            "persistent-state compatibility refused: "
            f"{report} — normal work was not admitted; the database was "
            f"left untouched for diagnosis"
        )
        self.report = report


def _verdict(
    state: SchemaCompatibility,
    expected_version: int,
    observed_version: int | None,
    reason: str,
    **evidence,
) -> CompatibilityReport:
    return CompatibilityReport(
        state=state, expected_version=expected_version,
        observed_version=observed_version, reason=reason, evidence=evidence,
    )


def inspect_schema(
    con: sqlite3.Connection, *, expected_version: int = EXPECTED_SCHEMA_VERSION
) -> CompatibilityReport:
    """Adjudicate one open SQLite connection's persistent state against the
    expected contract. Strictly read-only: never stamps, migrates, or repairs."""
    try:
        quick = con.execute("PRAGMA quick_check").fetchone()[0]
        if quick != "ok":
            return _verdict(
                SchemaCompatibility.CORRUPT, expected_version, None,
                f"quick_check reported {quick!r}", quick_check=str(quick),
            )
        tables = {
            row[0] for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'"
            )
        }
    except sqlite3.DatabaseError as exc:
        return _verdict(
            SchemaCompatibility.CORRUPT, expected_version, None,
            f"not a usable SQLite database: {exc}", sqlite_error=str(exc),
        )

    if not tables:
        return _verdict(
            SchemaCompatibility.FRESH, expected_version, None,
            "no persistent state yet (zero user tables); canonical bootstrap "
            "may create it",
            user_tables=[],
        )

    if "schema_migrations" not in tables:
        return _verdict(
            SchemaCompatibility.UNKNOWN, expected_version, None,
            f"existing database has {len(tables)} table(s) but no "
            f"schema_migrations authority; it is not fresh and must not be "
            f"bootstrapped or stamped",
            user_tables=sorted(tables),
        )

    # Marker shape: the authority must have a usable integer `version`
    # column whose rows all parse as versions.
    columns = {row[1] for row in con.execute("PRAGMA table_info(schema_migrations)")}
    if "version" not in columns:
        return _verdict(
            SchemaCompatibility.UNKNOWN, expected_version, None,
            "schema_migrations table exists but lacks the expected "
            "'version' column; the version authority is unreadable",
            user_tables=sorted(tables),
        )
    raw = [row[0] for row in con.execute("SELECT version FROM schema_migrations")]
    versions: list[int] = []
    for value in raw:
        if isinstance(value, int):
            versions.append(value)
        elif isinstance(value, str):
            try:
                versions.append(int(value))
            except ValueError:
                return _verdict(
                    SchemaCompatibility.UNKNOWN, expected_version, None,
                    f"schema_migrations contains non-integer version data "
                    f"({raw!r}); the version authority is corrupt",
                    user_tables=sorted(tables),
                )
        else:
            return _verdict(
                SchemaCompatibility.UNKNOWN, expected_version, None,
                f"schema_migrations contains non-integer version data "
                f"({raw!r}); the version authority is corrupt",
                user_tables=sorted(tables),
            )
    if not versions:
        return _verdict(
            SchemaCompatibility.UNKNOWN, expected_version, 0,
            "schema_migrations exists but has never recorded any version; "
            "state is neither fresh nor versioned",
            user_tables=sorted(tables),
        )

    observed = max(versions)
    if observed > expected_version:
        return _verdict(
            SchemaCompatibility.INCOMPATIBLE_NEWER, expected_version, observed,
            f"persistent state is newer (v{observed}) than this software "
            f"understands (v{expected_version}); the skew contract is "
            f"FORWARD_ONLY_EXPLICIT and older software must not open it",
            user_tables=sorted(tables),
        )
    if observed < expected_version:
        return _verdict(
            SchemaCompatibility.MIGRATION_REQUIRED, expected_version, observed,
            f"older valid state (v{observed}) must migrate through the "
            f"canonical mechanism to v{expected_version} before normal work",
            user_tables=sorted(tables),
        )

    missing = sorted(EXPECTED_TABLES - tables)
    if missing:
        return _verdict(
            SchemaCompatibility.PARTIAL, expected_version, observed,
            f"marker records v{observed} but {len(missing)} expected table(s) "
            f"are missing ({', '.join(missing)}); migration is incomplete or "
            f"the state is contradictory",
            missing_tables=missing,
            user_tables=sorted(tables),
        )

    return _verdict(
        SchemaCompatibility.COMPATIBLE, expected_version, observed,
        f"state matches the expected v{expected_version} contract "
        f"(all {len(EXPECTED_TABLES)} expected tables present)",
        user_tables=sorted(tables),
    )

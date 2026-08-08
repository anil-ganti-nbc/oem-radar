"""Stage 0.5-compatible runtime bridge for OEM Radar: version / identity / health.

Thin adapter only. Does not implement schedulers, retries, event export, or
Fleet control, and does not claim a release channel this build hasn't earned.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CLANK_ID = "oem-radar"
PACKAGE_VERSION = "0.0.1"


def _release_channel() -> str:
    # Never hard-code "production" here: OEM Radar is Tier C in the current
    # migration policy (portability/investigation only, not approved for
    # production), and even Tier A images must earn promotion explicitly.
    return os.environ.get("OEM_RADAR_RELEASE_CHANNEL", "experimental")


try:
    from clank_runtime.contracts.enums import (
        IngestionState,
        OperationalState,
        ReleaseChannel,
    )
    from clank_runtime.contracts.health import HealthPayload
    from clank_runtime.contracts.identity import RuntimeIdentity
    from clank_runtime.version import (
        HEALTH_CONTRACT_VERSION,
        RUNTIME_CONTRACT_VERSION,
        __version__ as RUNTIME_VERSION,
    )

    _HAS_RUNTIME = True
except ImportError:  # pragma: no cover - clank_runtime is an optional, separate package
    _HAS_RUNTIME = False
    RUNTIME_VERSION = "unavailable"
    RUNTIME_CONTRACT_VERSION = "0.1.0-stage0"
    HEALTH_CONTRACT_VERSION = "0.1.0-stage0"
    OperationalState = None  # type: ignore[assignment]
    IngestionState = None  # type: ignore[assignment]
    ReleaseChannel = None  # type: ignore[assignment]
    HealthPayload = None  # type: ignore[assignment]
    RuntimeIdentity = None  # type: ignore[assignment]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def get_version_info() -> dict[str, str]:
    return {
        "clank_id": CLANK_ID,
        "clank_version": PACKAGE_VERSION,
        "runtime_version": RUNTIME_VERSION,
        "runtime_contract_version": RUNTIME_CONTRACT_VERSION,
        "health_contract_version": HEALTH_CONTRACT_VERSION,
        "release_channel": _release_channel(),
        "runtime_bridge": "stage1.3",
    }


def get_identity() -> Any:
    channel = _release_channel()
    if _HAS_RUNTIME:
        try:
            rc = ReleaseChannel(channel)
        except ValueError:
            rc = ReleaseChannel.EXPERIMENTAL
        return RuntimeIdentity(
            runtime_version=RUNTIME_VERSION,
            clank_id=CLANK_ID,
            clank_version=PACKAGE_VERSION,
            release_channel=rc,
        )
    return {
        "contract_version": RUNTIME_CONTRACT_VERSION,
        "runtime_version": RUNTIME_VERSION,
        "clank_id": CLANK_ID,
        "clank_version": PACKAGE_VERSION,
        "release_channel": channel,
    }


def _probe_sqlite(db_path: Path) -> tuple[bool | None, str | None, list[str]]:
    """Return (writable, last_success_iso, reasons)."""
    reasons: list[str] = []
    if not db_path.exists():
        reasons.append(f"database file missing: {db_path}")
        return None, None, reasons
    try:
        con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
        try:
            row = con.execute(
                "SELECT finished_at FROM crawler_runs "
                "WHERE finished_at IS NOT NULL ORDER BY id DESC LIMIT 1"
            ).fetchone()
            last = row[0] if row else None
        except sqlite3.Error as exc:
            reasons.append(f"crawler_runs query failed: {exc}")
            last = None
        finally:
            con.close()
    except sqlite3.Error as exc:
        reasons.append(f"sqlite open failed: {exc}")
        return False, None, reasons

    parent = db_path.parent
    writable = os.access(parent, os.W_OK)
    if not writable:
        reasons.append(f"data directory not writable: {parent}")
    return writable, last, reasons


def get_health(db_path: Path) -> Any:
    """Build health from process + local SQLite state only.

    Does not run collectors. Does not claim Fleet or ingestion health.
    """
    writable, last_success, reasons = _probe_sqlite(db_path)
    evidence_dir = db_path.parent / "raw"
    evidence_writable = evidence_dir.exists() and os.access(evidence_dir, os.W_OK)

    if last_success is None and not reasons:
        reasons.append("no successful runs recorded yet")

    state = "healthy"
    if writable is False or not db_path.exists():
        state = "degraded"
    if writable is False and not db_path.exists():
        state = "failed"

    version_info = get_version_info()
    observed = _utc_now()

    if _HAS_RUNTIME:
        op_state = {
            "healthy": OperationalState.HEALTHY,
            "degraded": OperationalState.DEGRADED,
            "failed": OperationalState.FAILED,
        }.get(state, OperationalState.UNKNOWN)
        last_dt = None
        if last_success:
            try:
                last_dt = datetime.fromisoformat(str(last_success).replace("Z", "+00:00"))
            except ValueError:
                last_dt = None
        return HealthPayload(
            operational_state=op_state,
            process_liveness=True,
            application_readiness=db_path.exists(),
            last_successful_run=last_dt,
            database_writable=writable,
            evidence_path_writable=evidence_writable,
            ingestion_state=IngestionState.UNKNOWN,
            version_info=version_info,
            status_reasons=reasons,
            observed_at=observed,
        )

    return {
        "contract_version": HEALTH_CONTRACT_VERSION,
        "operational_state": state,
        "process_liveness": True,
        "application_readiness": db_path.exists(),
        "last_successful_run": last_success,
        "database_writable": writable,
        "evidence_path_writable": evidence_writable,
        "ingestion_state": "unknown",
        "version_info": version_info,
        "status_reasons": reasons,
        "observed_at": observed.isoformat(),
    }


def as_jsonable(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    return obj

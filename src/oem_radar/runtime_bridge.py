"""Stage 1 runtime bridge for OEM Radar.

Exposes identity, metadata, health, and version using the Stage 0.5
clank-runtime contracts when the package is available; otherwise emits
compatible plain dicts / JSON-serializable structures.

Does not implement schedulers, retries, event export, or Fleet control.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .core.config import RadarConfig, load_radar_config

CLANK_ID = "oem-radar"
PACKAGE_VERSION = "0.0.1"
RELEASE_CHANNEL = "production"  # pilot is mature production workload

# Prefer installed clank-runtime contracts; fall back to plain structures.
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
except ImportError:  # pragma: no cover - optional dependency for Stage 1 pilot
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


def _db_path_from_config(config_dir: Path) -> Path:
    from .paths import resolve_data_path
    radar = load_radar_config(config_dir / "radar.yaml")
    return resolve_data_path(radar.db_path)


def get_identity(config_dir: Path | None = None) -> Any:
    """Return RuntimeIdentity or a compatible dict."""
    if _HAS_RUNTIME:
        return RuntimeIdentity(
            runtime_version=RUNTIME_VERSION,
            clank_id=CLANK_ID,
            clank_version=PACKAGE_VERSION,
            release_channel=ReleaseChannel.PRODUCTION,
        )
    return {
        "contract_version": RUNTIME_CONTRACT_VERSION,
        "runtime_version": RUNTIME_VERSION,
        "clank_id": CLANK_ID,
        "clank_version": PACKAGE_VERSION,
        "release_channel": RELEASE_CHANNEL,
    }


def get_version_info() -> dict[str, str]:
    return {
        "clank_id": CLANK_ID,
        "clank_version": PACKAGE_VERSION,
        "runtime_version": RUNTIME_VERSION,
        "runtime_contract_version": RUNTIME_CONTRACT_VERSION,
        "health_contract_version": HEALTH_CONTRACT_VERSION,
        "runtime_bridge": "stage1",
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

    # writability of parent dir (not the process holding a write lock)
    parent = db_path.parent
    writable = os.access(parent, os.W_OK)
    if not writable:
        reasons.append(f"data directory not writable: {parent}")
    return writable, last, reasons


def get_health(config_dir: Path) -> Any:
    """Build a HealthPayload (or dict) from process + local SQLite state.

    Does not run collectors. Does not claim Fleet or ingestion health.
    """
    db_path = _db_path_from_config(config_dir)
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
    """Convert pydantic models to plain data for CLI printing."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    return obj

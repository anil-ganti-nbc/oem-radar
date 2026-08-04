"""Authoritative path resolution for OEM Radar (Stage 1.1).

Default behavior is backward-compatible: relative paths in radar.yaml are
resolved against the process current working directory (project root or
container WORKDIR /app).

Optional environment overrides:
  OEM_RADAR_DATA_DIR  — if set, replaces the parent of relative data/* paths
                        (db, raw, http_cache, logs under data/).

No Synology-specific paths. No schema changes.
"""

from __future__ import annotations

import os
from pathlib import Path


def data_root() -> Path | None:
    """Return OEM_RADAR_DATA_DIR if set and non-empty, else None."""
    raw = os.environ.get("OEM_RADAR_DATA_DIR", "").strip()
    return Path(raw) if raw else None


def resolve_data_path(configured: str, *, cwd: Path | None = None) -> Path:
    """Resolve a configured data path (e.g. radar.yaml db_path / raw_dir / log file).

    Rules:
    1. Absolute configured paths are returned unchanged.
    2. If OEM_RADAR_DATA_DIR is set and configured is under ``data/`` (or is
       exactly ``data``), remap the path under that directory.
    3. Otherwise resolve relative to cwd (default: Path.cwd()).
    """
    path = Path(configured)
    if path.is_absolute():
        return path

    root = data_root()
    parts = path.parts
    if root is not None and parts and parts[0] == "data":
        return root.joinpath(*parts[1:]) if len(parts) > 1 else root

    base = cwd if cwd is not None else Path.cwd()
    return (base / path).resolve()


def default_db_path() -> Path:
    return resolve_data_path("data/radar.db")


def default_raw_dir() -> Path:
    return resolve_data_path("data/raw")

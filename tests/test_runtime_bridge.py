"""Stage 1 runtime bridge tests — no crawl, no network."""

from __future__ import annotations

from pathlib import Path

from oem_radar.runtime_bridge import (
    CLANK_ID,
    as_jsonable,
    get_health,
    get_identity,
    get_version_info,
)


def test_version_info() -> None:
    info = get_version_info()
    assert info["clank_id"] == CLANK_ID
    assert "clank_version" in info


def test_identity() -> None:
    identity = as_jsonable(get_identity(Path("config")))
    assert identity["clank_id"] == "oem-radar"
    assert identity["release_channel"] == "production"


def test_health_reads_local_db() -> None:
    health = as_jsonable(get_health(Path("config")))
    assert health["process_liveness"] is True
    assert health["version_info"]["clank_id"] == "oem-radar"
    assert "operational_state" in health

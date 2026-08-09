"""Tests for the Git-revision provenance fields in runtime_bridge.

Covers OEM_RADAR_SOURCE_REVISION handling only -- this is a provenance-only
change, not a broader test of identity/health/version behavior.
"""

from __future__ import annotations

import importlib

import pytest

from oem_radar import runtime_bridge


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OEM_RADAR_SOURCE_REVISION", raising=False)


def test_source_revision_defaults_to_unknown_without_env_var() -> None:
    assert runtime_bridge._source_revision() == "unknown"
    assert runtime_bridge._source_revision_short() == "unknown"


def test_source_revision_reflects_full_sha_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    full_sha = "0ceb001f37355ef0fe904387769ed6f77db9c13f"
    monkeypatch.setenv("OEM_RADAR_SOURCE_REVISION", full_sha)
    assert runtime_bridge._source_revision() == full_sha


def test_source_revision_short_truncates_to_12_chars(monkeypatch: pytest.MonkeyPatch) -> None:
    full_sha = "0ceb001f37355ef0fe904387769ed6f77db9c13f"
    monkeypatch.setenv("OEM_RADAR_SOURCE_REVISION", full_sha)
    assert runtime_bridge._source_revision_short() == "0ceb001f3735"


def test_get_version_info_includes_source_revision(monkeypatch: pytest.MonkeyPatch) -> None:
    full_sha = "0ceb001f37355ef0fe904387769ed6f77db9c13f"
    monkeypatch.setenv("OEM_RADAR_SOURCE_REVISION", full_sha)
    info = runtime_bridge.get_version_info()
    assert info["source_revision"] == full_sha
    assert info["source_revision_short"] == "0ceb001f3735"


def test_get_version_info_reports_unknown_without_env_var() -> None:
    info = runtime_bridge.get_version_info()
    assert info["source_revision"] == "unknown"
    assert info["source_revision_short"] == "unknown"


def test_get_identity_includes_source_revision_when_runtime_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    full_sha = "0ceb001f37355ef0fe904387769ed6f77db9c13f"
    monkeypatch.setenv("OEM_RADAR_SOURCE_REVISION", full_sha)
    if runtime_bridge._HAS_RUNTIME:
        pytest.skip("clank_runtime installed: identity uses the RuntimeIdentity "
                    "pydantic model, which forbids extra fields (see DECISIONS.md)")
    identity = runtime_bridge.get_identity()
    assert identity["source_revision"] == full_sha
    assert identity["source_revision_short"] == "0ceb001f3735"

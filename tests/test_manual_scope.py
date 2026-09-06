"""Manual collection scope: roster authority and selection validation.

Pinned contract (decision 2026-09-06):

- ONE canonical roster: config/oems/*.yaml's own `manual_class` metadata
  decides routine vs long_running; the dashboard derives from it, and no
  JS list decides which collectors are expensive.
- An explicit selection is validated against the registry BEFORE anything
  is enqueued: unknown ids are refused (4xx, no background no-op), a
  disabled collector is refused (manual eligibility requires enabled),
  and a registry with no routine collectors refuses the default action
  instead of silently crawling nothing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from oem_radar.core import crawl_service
from oem_radar.core.crawl_service import (
    ManualScopeError,
    manual_roster,
    resolve_manual_sources as resolve,
)

REPO = Path(__file__).resolve().parents[1]


def _scratch_config(tmp_path: Path, sources: list[dict]) -> Path:
    config_dir = tmp_path / "config"
    (config_dir / "oems").mkdir(parents=True)
    for src in sources:
        (config_dir / "oems" / f"{src['id']}.yaml").write_text(
            "manufacturer:\n"
            f"  name: {src['id'].title()}\n  aliases: []\n  country: XX\n"
            "sources:\n"
            f"  - id: {src['id']}\n"
            f"    engine: {src.get('engine', 'shopify')}\n"
            f"    base_url: https://example.com/{src['id']}\n"
            f"    enabled: {src.get('enabled', True)}\n"
            f"    manual_class: {src.get('manual_class', 'routine')}\n",
            encoding="utf-8",
        )
    return config_dir


def test_manual_class_is_a_typed_field_with_a_safe_default():
    from oem_radar.core.config import SourceConfig

    assert SourceConfig(
        id="a", engine="shopify", base_url="https://example.com",
    ).manual_class == "routine"

    with pytest.raises(Exception):
        SourceConfig(
            id="a", engine="shopify", base_url="https://example.com",
            manual_class="expensive",
        )


def test_roster_groups_sources_by_the_registrys_own_classification(tmp_path):
    """Registry-is-authority guard: a newly classified long_running source
    moves to the deep group WITHOUT any frontend change."""
    config_dir = _scratch_config(tmp_path, [
        {"id": "routine-a"}, {"id": "routine-b"},
        {"id": "deep-x", "manual_class": "long_running"},
        {"id": "deep-y", "manual_class": "long_running"},
    ])
    roster = manual_roster(config_dir)
    assert [e["source_id"] for e in roster["routine"]] == ["routine-a", "routine-b"]
    assert [e["source_id"] for e in roster["long_running"]] == ["deep-x", "deep-y"]
    # exactly the fields the GUI needs — nothing else
    assert set(roster["routine"][0]) == {
        "source_id", "manufacturer", "engine", "enabled", "min_interval",
        "manual_class",
    }


def test_shipped_roster_medion_family_is_long_running():
    """The shipped config's classification, pinned: the four evidence-backed
    sitemap walkers are outside the routine manual action; every other
    enabled collector is routine."""
    roster = manual_roster(REPO / "config")
    deep = {e["source_id"] for e in roster["long_running"]}
    routine = {e["source_id"] for e in roster["routine"] if e["enabled"]}
    assert deep == {
        "medion-gaming-sitemap", "lg-us-gram-sitemap",
        "simplynuc-sitemap", "khadas-sitemap",
    }
    assert routine == {
        "acemagic-shopify", "aoostar-shopify", "beelink-shopify",
        "bosgame-shopify", "chuwi-shopify", "geekom-wc", "gmktec-shopify",
        "kamrui-shopify", "minisforum-shopify", "morefine-shopify",
        "nipogi-shopify", "novacustom-wc", "pine64-wc", "samsung-galaxybook",
        "starlabs-shopify", "vaio-shopify",
    }


def test_routine_default_excludes_long_running_and_disabled(tmp_path):
    config_dir = _scratch_config(tmp_path, [
        {"id": "routine-a"}, {"id": "routine-b"},
        {"id": "deep-x", "manual_class": "long_running"},
        {"id": "sleeping-b", "enabled": False},
    ])
    scope, kind = resolve(config_dir, None)
    assert scope == frozenset({"routine-a", "routine-b"})
    assert kind == "routine"


def test_unknown_source_is_refused_synchronously(tmp_path):
    config_dir = _scratch_config(tmp_path, [{"id": "routine-a"}])
    with pytest.raises(ManualScopeError) as excinfo:
        resolve(config_dir, ["no-such-collector"])
    assert excinfo.value.code == "unknown_source"
    assert excinfo.value.detail["unknown_sources"] == ["no-such-collector"]


def test_disabled_source_is_refused(tmp_path):
    config_dir = _scratch_config(tmp_path, [
        {"id": "routine-a"}, {"id": "sleeping", "enabled": False},
    ])
    with pytest.raises(ManualScopeError) as excinfo:
        resolve(config_dir, ["sleeping"])
    assert excinfo.value.code == "source_disabled"
    assert excinfo.value.detail["disabled_sources"] == ["sleeping"]


def test_empty_routine_roster_is_refused_not_silently_empty(tmp_path):
    """S22: a registry with ONLY long_running collectors must not let the
    ordinary action silently run everything (or nothing)."""
    config_dir = _scratch_config(tmp_path, [
        {"id": "deep-x", "manual_class": "long_running"},
    ])
    with pytest.raises(ManualScopeError) as excinfo:
        resolve(config_dir, None)
    assert excinfo.value.code == "no_routine_collectors"


def test_explicit_selection_resolves_to_the_requested_set(tmp_path):
    config_dir = _scratch_config(tmp_path, [
        {"id": "routine-a"},
        {"id": "deep-x", "manual_class": "long_running"},
        {"id": "deep-y", "manual_class": "long_running"},
    ])
    scope, kind = resolve(config_dir, ["deep-x", "deep-y"])
    assert scope == frozenset({"deep-x", "deep-y"})
    assert kind == "selected"

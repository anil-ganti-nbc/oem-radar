"""YAML configuration: radar.yaml (global policy) + config/oems/*.yaml
(one descriptor per OEM). No hardcoded policy anywhere else."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator

_INTERVAL_RE = re.compile(r"^(\d+)\s*(s|m|h|d)$")
_UNIT_S = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_interval(value: str | int) -> int:
    """'6h' → 21600. Bare ints are seconds."""
    if isinstance(value, int):
        return value
    m = _INTERVAL_RE.match(value.strip())
    if not m:
        raise ValueError(f"bad interval {value!r} (expected e.g. '90s', '30m', '6h', '1d')")
    return int(m.group(1)) * _UNIT_S[m.group(2)]


class SourceConfig(BaseModel):
    model_config = {"extra": "allow"}  # engine-specific keys validated by engine.config_schema

    id: str
    engine: str
    base_url: str
    min_interval: str | int = "6h"
    discovery: list[str] = Field(default_factory=list)
    enabled: bool = True

    @field_validator("min_interval")
    @classmethod
    def _check_interval(cls, v: str | int) -> str | int:
        parse_interval(v)
        return v

    @property
    def min_interval_s(self) -> int:
        return parse_interval(self.min_interval)


class ManufacturerConfig(BaseModel):
    name: str
    aliases: list[str] = Field(default_factory=list)
    country: str | None = None


class OemConfig(BaseModel):
    manufacturer: ManufacturerConfig
    sources: list[SourceConfig] = Field(default_factory=list)


class SeverityRule(BaseModel):
    match: dict[str, Any] = Field(default_factory=dict)
    severity: int = Field(ge=1, le=5)


class StoryRule(BaseModel):
    """A cross-event correlation pattern (config, like severity rules).
    Fires a story when enough DISTINCT manufacturers share a grouped key
    within a time window."""

    id: str
    title: str                               # template, e.g. "{n} OEMs listed {key}"
    match: dict[str, Any] = Field(default_factory=dict)
    group_by: str = "new_value"
    window: str | int = "7d"
    min_distinct_manufacturers: int = 2
    base_score: int = Field(default=60, ge=0, le=100)
    per_extra_oem: int = 10
    enabled: bool = True

    @field_validator("window")
    @classmethod
    def _check_window(cls, v):
        parse_interval(v)
        return v

    @property
    def window_s(self) -> int:
        return parse_interval(self.window)


class NotifyChannelConfig(BaseModel):
    model_config = {"extra": "allow"}
    min_severity: int = Field(default=3, ge=1, le=5)
    digest_below: int | None = None


class RadarConfig(BaseModel):
    store: str = "sqlite"
    notifier: str = "discord"
    summarizer: str | None = None
    db_path: str = "data/radar.db"
    raw_dir: str = "data/raw"
    removal_grace: int = 2
    baseline_quiet: bool = False  # suppress notifications on a source's first-ever crawl
    severity_rules: list[SeverityRule] = Field(default_factory=list)
    story_rules: list[StoryRule] = Field(default_factory=list)
    notify: dict[str, NotifyChannelConfig] = Field(default_factory=dict)
    rate_limit: dict[str, Any] = Field(default_factory=dict)
    ai: dict[str, Any] = Field(default_factory=dict)
    logging: dict[str, Any] = Field(default_factory=dict)


class ConfigError(Exception):
    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__("; ".join(problems))


def _load_yaml(path: Path) -> Any:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_radar_config(path: Path) -> RadarConfig:
    try:
        return RadarConfig.model_validate(_load_yaml(path) or {})
    except ValidationError as e:
        raise ConfigError([f"{path.name}: {err['loc']}: {err['msg']}" for err in e.errors()])


def load_oem_configs(oems_dir: Path) -> dict[str, OemConfig]:
    """Load all descriptors; collect *all* problems before failing."""
    oems: dict[str, OemConfig] = {}
    problems: list[str] = []
    seen_source_ids: dict[str, str] = {}
    for path in sorted(oems_dir.glob("*.yaml")):
        try:
            cfg = OemConfig.model_validate(_load_yaml(path) or {})
        except ValidationError as e:
            problems.extend(f"{path.name}: {err['loc']}: {err['msg']}" for err in e.errors())
            continue
        for src in cfg.sources:
            if src.id in seen_source_ids:
                problems.append(
                    f"{path.name}: duplicate source id {src.id!r} (also in {seen_source_ids[src.id]})"
                )
            seen_source_ids[src.id] = path.name
        oems[cfg.manufacturer.name] = cfg
    if problems:
        raise ConfigError(problems)
    return oems

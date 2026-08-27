"""Restock Watch (campaign deliverable D).

Availability becomes a separate subsystem with its own editorial gates:
a restock must *earn* notification authority. First implementation is
deterministic and fully explainable -- no scores, no LLM.

Eligibility contract:

    CURRENT     -> ELIGIBLE (may toll)
    PREVIOUS    -> CONDITIONAL (gates below must all pass)
    OLD/LEGACY  -> SUPPRESSED (unless explicit strategic override)
    UNKNOWN     -> REVIEW (never automatic Discord)
"""

from __future__ import annotations

import re
from datetime import date, datetime

from pydantic import BaseModel, Field

try:  # pyyaml is a runtime dependency of the project already
    import yaml
except ModuleNotFoundError:  # pragma: no cover - defensive
    yaml = None


class GenerationStatus(str):
    CURRENT = "CURRENT"
    PREVIOUS = "PREVIOUS"
    OLD = "OLD"
    LEGACY = "LEGACY"
    UNKNOWN = "UNKNOWN"


class HardwareGeneration(BaseModel):
    component_type: str                 # cpu | gpu | npu
    vendor: str
    family: str                         # e.g. ryzen-mobile, core-ultra
    model: str                          # e.g. 8845HS / Ultra 9 185H
    announcement_date: str | None = None
    launch_date: str | None = None
    generation: str | None = None       # e.g. zen4 / meteor-lake
    generation_rank: int | None = None
    status: str = GenerationStatus.UNKNOWN
    successor: str | None = None


class RestockCandidate(BaseModel):
    product_key: str
    manufacturer: str
    model: str
    cpu_raw: str | None = None
    gpu_raw: str | None = None
    category: str | None = None
    region: str | None = None
    first_seen_at: datetime             # product age anchor
    unavailable_since: datetime | None = None   # prior SOLD_OUT start
    unavailable_until: datetime | None = None   # now AVAILABLE again
    source_confidence: float = 1.0
    strategic_override: bool = False    # operator-curated whitelist only
    important_market: bool = True       # US/UK/DE default true; curated list later


class EligibilityVerdict(BaseModel):
    decision: str                       # ELIGIBLE | CONDITIONAL_ELIGIBLE | SUPPRESSED | REVIEW
    gate_trace: list[str] = Field(default_factory=list)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _numeric_signature(text: str) -> set[str]:
    """Part numbers hidden inside noisy vendor strings: '7735HS' -> '7735'."""
    return {m.group(1) for m in re.finditer(r"\b\w*?(\d{3,4})\w*\b", text)}


def generation_status(component: str | None,
                      generations: dict[str, HardwareGeneration]) -> str:
    """Look up the newest applicable status for one component raw string.

    Match order: exact slug -> contained slug -> 4-digit part-number
    signature. Returns UNKNOWN on any miss.
    """
    if not component or not generations:
        return GenerationStatus.UNKNOWN
    key = _slug(component)
    for gk, gen in generations.items():
        if _slug(gk) == key:
            return gen.status
    for gk, gen in generations.items():
        if _slug(gk) in key or key in _slug(gk):
            return gen.status
    sig = _numeric_signature(component)
    best_len, found_status = -1, GenerationStatus.UNKNOWN
    for gk, gen in generations.items():
        for num in _numeric_signature(gk):
            if num in sig and len(num) > best_len:
                best_len, found_status = len(num), gen.status
    return found_status


def load_generations(path) -> dict[str, HardwareGeneration]:
    """Seed file: config/hardware_generations.yaml."""
    if yaml is None:  # pragma: no cover
        raise RuntimeError("pyyaml unavailable")
    data = yaml.safe_load(open(path, encoding="utf-8")) or {}
    out: dict[str, HardwareGeneration] = {}
    for entry in data.get("generations", []):
        gen = HardwareGeneration(**entry)
        out[gen.model] = gen
        # alias raw strings like "AMD Ryzen 7 8845HS" onto their model row
        if gen.vendor and gen.model:
            out[f"{gen.vendor} {gen.family} {gen.model}"] = gen
    return out


_MIN_DAYS_UNAVAILABLE_PREVIOUS = 7
_MAX_PRODUCT_AGE_CONDITIONAL_DAYS = 365


def restock_eligibility(
    candidate: RestockCandidate,
    cpu_generations: dict[str, HardwareGeneration],
    now: datetime | None = None,
) -> EligibilityVerdict:
    """Deterministic gate trace. Never raises; unknown inputs => REVIEW."""
    trace: list[str] = []
    now = now or candidate.unavailable_until or datetime.now()

    if candidate.strategic_override:
        trace.append("strategic override (operator whitelist): pass")
        return EligibilityVerdict(decision="ELIGIBLE", gate_trace=trace)

    status = generation_status(candidate.cpu_raw, cpu_generations)
    trace.append(f"cpu generation status: {status}")

    if status == GenerationStatus.CURRENT:
        trace.append("current-generation hardware may toll")
        verdict = "ELIGIBLE"
    elif status == GenerationStatus.PREVIOUS:
        age_days = (now - candidate.first_seen_at).days
        unavail_days = (
            (candidate.unavailable_until - candidate.unavailable_since).days
            if candidate.unavailable_since and candidate.unavailable_until else 0)
        trace.append(f"product age: {age_days}d, prior unavailability: {unavail_days}d")
        ok_age = 0 <= age_days <= _MAX_PRODUCT_AGE_CONDITIONAL_DAYS
        ok_unavail = unavail_days >= _MIN_DAYS_UNAVAILABLE_PREVIOUS
        ok_market = candidate.important_market
        ok_conf = candidate.source_confidence >= 0.8
        trace.append(f"gates[age<=365]={ok_age}, [unavailable>=7d]={ok_unavail}, "
                     f"[market]={ok_market}, [confidence>=0.8]={ok_conf}")
        verdict = ("CONDITIONAL_ELIGIBLE" if all((ok_age, ok_unavail, ok_market, ok_conf))
                   else "REVIEW")
    elif status in (GenerationStatus.OLD, GenerationStatus.LEGACY):
        trace.append("old/legacy silicon: availability is not news")
        verdict = "SUPPRESSED"
    else:  # UNKNOWN
        trace.append("unknown generation: review before any delivery")
        verdict = "REVIEW"

    return EligibilityVerdict(decision=verdict, gate_trace=trace)

"""Restock Watch tests (campaign deliverable D)."""

from datetime import datetime, timezone

from oem_radar.core.restock import (
    GenerationStatus,
    RestockCandidate,
    generation_status,
    load_generations,
    restock_eligibility,
)
from pathlib import Path

SEED = Path(__file__).resolve().parent.parent / "config" / "hardware_generations.yaml"
NOW = datetime(2026, 8, 27, tzinfo=timezone.utc)


def _cand(**over) -> RestockCandidate:
    base = dict(
        product_key="minisforum:um890", manufacturer="Minisforum",
        model="UM890 Pro", cpu_raw="AMD Ryzen 7 8845HS",
        first_seen_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        unavailable_since=NOW, unavailable_until=NOW,
        source_confidence=1.0,
    )
    base.update(over)
    return RestockCandidate(**base)


GENS = load_generations(SEED)


def test_seed_loads_and_statuses_exist():
    assert GENS
    assert any(g.status == GenerationStatus.CURRENT for g in GENS.values())


def test_generation_lookup_exact_and_contained():
    assert generation_status("Ryzen 7 8845HS", GENS) == "CURRENT"
    assert generation_status("AMD Ryzen(TM) 7 7735HS w/ Radeon", GENS) == "OLD"
    assert generation_status("Some alien chip XT-99", GENS) == GenerationStatus.UNKNOWN


def test_current_generation_restock_may_toll():
    v = restock_eligibility(_cand(cpu_raw="Ryzen AI 9 HX 370"), GENS, now=NOW)
    assert v.decision == "ELIGIBLE"


def test_previous_generation_conditional_gates():
    # all gates pass => CONDITIONAL_ELIGIBLE
    v = restock_eligibility(_cand(
        cpu_raw="Intel i7-13620H",
        first_seen_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        unavailable_since=NOW.replace(day=10), unavailable_until=NOW), GENS, now=NOW)
    assert v.decision == "CONDITIONAL_ELIGIBLE"
    # too-short unavailability drops to review
    v2 = restock_eligibility(_cand(
        cpu_raw="Intel i7-13620H",
        first_seen_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        unavailable_since=NOW.replace(day=25), unavailable_until=NOW), GENS, now=NOW)
    assert v2.decision == "REVIEW"
    # ancient product (age > 365d) drops to review as well
    v3 = restock_eligibility(_cand(
        cpu_raw="Intel i7-13620H",
        first_seen_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        unavailable_since=NOW.replace(day=10), unavailable_until=NOW), GENS, now=NOW)
    assert v3.decision == "REVIEW"


def test_three_year_old_cpu_restock_is_silent():
    """The campaign's canonical example must not toll."""
    v = restock_eligibility(_cand(
        product_key="beelink:gti11", manufacturer="Beelink",
        model="GTi 11", cpu_raw="Ryzen 5 5600U"), GENS, now=NOW)
    assert v.decision == "SUPPRESSED"
    assert any("old/legacy" in t.lower() for t in v.gate_trace)


def test_unknown_cpu_never_notifies_automatically():
    v = restock_eligibility(_cand(cpu_raw="Zhaoxin KX-7000"), GENS, now=NOW)
    assert v.decision == "REVIEW"


def test_strategic_override_is_explicit_operator_power():
    v = restock_eligibility(_cand(cpu_raw="N5095", strategic_override=True), GENS, now=NOW)
    assert v.decision == "ELIGIBLE"


def test_gate_trace_is_human_explainable():
    v = restock_eligibility(_cand(), GENS, now=NOW)
    assert v.gate_trace and all(isinstance(t, str) for t in v.gate_trace)

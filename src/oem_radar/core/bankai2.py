"""BANKAI II benchmark harness (campaign deliverable J).

Notebookcheck is the CANONICAL_EDITORIAL_TARGET: never a discovery source.
The harness samples real NBC hardware stories into a frozen corpus (JSONL),
then measures, per case:

    NBC_RECALL     eligible sources contained the product before publication
    NBC_LEAD       seconds between Radar evidence possession and NBC publish
    NBC_PRECISION  fraction of Radar alerts that were plausible NBC stories
    NBC_NOISE      alerts with no credible editorial value

Failure taxonomy is exactly the campaign contract. The corpus schema and
metric calculators exist now; the benchmark RUN waits for OEM Radar 2.0
(notification firewall + identity + clustering) to be live on local replays.
"""

from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field


CANONICAL_EDITORIAL_TARGET = "Notebookcheck"


class FailureTaxonomy(str, Enum):
    NONE = "none"
    SOURCE_GAP = "source_gap"
    REGION_GAP = "region_gap"
    COLLECTOR_FAILURE = "collector_failure"
    SCHEDULE_LATENCY = "schedule_latency"
    PARSER_GAP = "parser_gap"
    IDENTITY_FAILURE = "identity_failure"
    BASELINE_FALSE_MATCH = "baseline_false_match"
    EDITORIAL_SUPPRESSION = "editorial_suppression"
    CLUSTERING_ERROR = "clustering_error"
    DELIVERY_FAILURE = "delivery_failure"


class BenchmarkCase(BaseModel):
    """One frozen Notebookcheck-relevant hardware story.

    corpus format: JSONL, one case per line; `sampled_at_utc`/`corpus_id`
    bind cases to a frozen BANKAI II run so rows are never silently revised.
    """

    case_id: str                       # stable id, e.g. bankai2-2026-08-0001
    nbc_title: str
    nbc_url: str | None = None
    nbc_published_at: datetime         # publication timestamp (UTC)
    manufacturer: str
    model: str
    sku: str | None = None
    region_hint: str | None = None
    categories: list[str] = Field(default_factory=list)
    eligible_sources: list[str] = Field(default_factory=list)  # source_keys that could have seen it


class ReplayOutcome(BaseModel):
    """Result of replaying one BenchmarkCase against a Radar implementation."""

    case_id: str
    source_had_product_before_pub: bool = False
    crawled_in_time: bool = False
    parsed_correctly: bool = False
    identity_recognised_new: bool = False
    editorial_candidate_generated: bool = False
    clustering_preserved_lead: bool = False
    would_have_notified: bool = False
    radar_evidence_at: datetime | None = None   # first possession of evidence
    alert_generated_at: datetime | None = None
    failure: FailureTaxonomy = FailureTaxonomy.NONE


def load_corpus(path: str | Path) -> list[BenchmarkCase]:
    return [BenchmarkCase(**json.loads(line)) for line in
            Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def save_corpus(cases: list[BenchmarkCase], path: str | Path) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for c in cases:
            fh.write(json.dumps(json.loads(c.model_dump_json()), sort_keys=True) + "\n")


def _first_failure(o: ReplayOutcome) -> FailureTaxonomy:
    """First broken link in the funnel determines the dominant failure class."""
    if o.source_had_product_before_pub:
        if not o.crawled_in_time:
            return FailureTaxonomy.COLLECTOR_FAILURE
        if not o.parsed_correctly:
            return FailureTaxonomy.PARSER_GAP
        if o.identity_recognised_new is False:
            return FailureTaxonomy.BASELINE_FALSE_MATCH
        if not o.editorial_candidate_generated:
            return FailureTaxonomy.EDITORIAL_SUPPRESSION
        if not o.clustering_preserved_lead:
            return FailureTaxonomy.CLUSTERING_ERROR
        if not o.would_have_notified:
            return FailureTaxonomy.DELIVERY_FAILURE
        return FailureTaxonomy.NONE
    return FailureTaxonomy.SOURCE_GAP  # region refinement happens at analysis time


def score_case(case: BenchmarkCase, outcome: ReplayOutcome) -> dict:
    lead_s = None
    if outcome.radar_evidence_at is not None:
        lead_s = (case.nbc_published_at - outcome.radar_evidence_at).total_seconds()
    alerted_lead_s = None
    if outcome.alert_generated_at is not None:
        alerted_lead_s = (case.nbc_published_at - outcome.alert_generated_at).total_seconds()
    derived = _first_failure(outcome)
    effective_failure = outcome.failure if outcome.failure != FailureTaxonomy.NONE else derived
    recalled = (
        outcome.source_had_product_before_pub
        and outcome.crawled_in_time
        and outcome.parsed_correctly
        and outcome.identity_recognised_new
        and outcome.editorial_candidate_generated
        and outcome.clustering_preserved_lead
        and outcome.would_have_notified
    )
    return {
        "case_id": case.case_id,
        "recalled": recalled,
        "evidence_lead_s": lead_s,
        "alert_lead_s": alerted_lead_s,
        "failure": effective_failure.value,
    }


def summarize(scores: list[dict]) -> dict:
    total = len(scores) or 1
    recalls = sum(1 for s in scores if s["recalled"])
    leads = [s["alert_lead_s"] for s in scores
             if s["alert_lead_s"] is not None and s["alert_lead_s"] > 0]
    failures: dict[str, int] = {}
    for s in scores:
        f = s["failure"]
        if f != "none":
            failures[f] = failures.get(f, 0) + 1
    return {
        "cases": len(scores),
        "recall": recalls / total,
        "median_alert_lead_s": sorted(leads)[len(leads) // 2] if leads else None,
        "failure_counts": dict(sorted(failures.items(), key=lambda kv: -kv[1])),
    }


def precision_and_noise(alerts: list[bool]) -> tuple[float, float]:
    """alerts: True where a Radar alert was a plausible NBC story."""
    if not alerts:
        return 0.0, 0.0
    good = sum(1 for a in alerts if a)
    return good / len(alerts), 1 - (good / len(alerts))

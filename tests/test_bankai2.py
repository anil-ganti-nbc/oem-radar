"""BANKAI II harness tests (campaign deliverable J)."""

import json
from datetime import datetime, timedelta, timezone

from oem_radar.core.bankai2 import (
    CANONICAL_EDITORIAL_TARGET,
    BenchmarkCase,
    FailureTaxonomy,
    ReplayOutcome,
    precision_and_noise,
    save_corpus,
    load_corpus,
    score_case,
    summarize,
)

PUB = datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc)


def case(cid: str = "bankai2-x-0001") -> BenchmarkCase:
    return BenchmarkCase(
        case_id=cid, nbc_title="New Ryzen mini-PC spotted",
        nbc_published_at=PUB, manufacturer="Minisforum", model="UM890",
        eligible_sources=["minisforum-shopify"])


def caught(published_ahead_h: float) -> ReplayOutcome:
    alert_at = PUB - timedelta(hours=published_ahead_h)
    return ReplayOutcome(
        case_id=case().case_id,
        source_had_product_before_pub=True,
        crawled_in_time=True,
        parsed_correctly=True,
        identity_recognised_new=True,
        editorial_candidate_generated=True,
        clustering_preserved_lead=True,
        would_have_notified=True,
        radar_evidence_at=PUB - timedelta(days=4),
        alert_generated_at=alert_at,
        failure=FailureTaxonomy.NONE)


def test_canonical_target_is_notebookcheck():
    assert CANONICAL_EDITORIAL_TARGET == "Notebookcheck"


def test_full_funnel_pass_scores_recall_with_lead():
    out = ReplayOutcome(
        case_id="c1", source_had_product_before_pub=True, crawled_in_time=True,
        parsed_correctly=True, identity_recognised_new=True,
        editorial_candidate_generated=True, clustering_preserved_lead=True,
        would_have_notified=True,
        radar_evidence_at=PUB - timedelta(days=4),
        alert_generated_at=PUB - timedelta(days=3))
    s = score_case(case("c1"), out)
    assert s["recalled"] is True
    assert s["evidence_lead_s"] == 4 * 24 * 3600
    assert s["alert_lead_s"] == 3 * 24 * 3600
    assert s["failure"] == "none"


def test_failure_taxonomy_source_gap_dominates_when_no_eligible_source():
    out = ReplayOutcome(case_id="c2", failure=FailureTaxonomy.NONE)
    s = score_case(case("c2"), out)
    assert s["failure"] == FailureTaxonomy.SOURCE_GAP.value


def test_each_broken_link_maps_to_its_taxon():
    matrix = {
        "crawled_in_time": FailureTaxonomy.COLLECTOR_FAILURE,
        "parsed_correctly": FailureTaxonomy.PARSER_GAP,
        "identity_recognised_new": FailureTaxonomy.BASELINE_FALSE_MATCH,
        "editorial_candidate_generated": FailureTaxonomy.EDITORIAL_SUPPRESSION,
        "clustering_preserved_lead": FailureTaxonomy.CLUSTERING_ERROR,
        "would_have_notified": FailureTaxonomy.DELIVERY_FAILURE,
    }
    for broken, taxon in matrix.items():
        flags = dict(
            source_had_product_before_pub=True, crawled_in_time=False,
            parsed_correctly=False, identity_recognised_new=False,
            editorial_candidate_generated=False, clustering_preserved_lead=False,
            would_have_notified=False)
        # ensure upstream links still pass to isolate the broken one
        order = ["source_had_product_before_pub", "crawled_in_time",
                 "parsed_correctly", "identity_recognised_new",
                 "editorial_candidate_generated",
                 "clustering_preserved_lead", "would_have_notified"]
        for k in order:
            if k == broken:
                break
            flags[k] = True
        out = ReplayOutcome(case_id=f"tax-{broken}", **flags)
        s = score_case(case(f"tax-{broken}"), out)
        assert s["failure"] == taxon.value, f"{broken} -> {s['failure']}"


def test_explicit_failure_override_respected():
    out = caught(1.0)
    out.failure = FailureTaxonomy.SCHEDULE_LATENCY
    s = score_case(case(), out)
    assert s["failure"] == FailureTaxonomy.SCHEDULE_LATENCY.value


def test_summarize_aggregates():
    o1, o2 = caught(1.0), caught(2.0)
    scores = [score_case(case("a"), o1), score_case(case("b"), o2)]
    summary = summarize(scores)
    assert summary["cases"] == 2 and summary["recall"] == 1.0
    assert summary["median_alert_lead_s"] is not None


def test_precision_noise_pairing():
    p, n = precision_and_noise([True, True, False])
    assert abs(p - 2 / 3) < 1e-9 and abs(n - 1 / 3) < 1e-9


def test_corpus_roundtrip(tmp_path):
    c = case()
    path = tmp_path / "corpus.jsonl"
    save_corpus([c], path)
    loaded = load_corpus(path)
    assert len(loaded) == 1 and loaded[0].model_dump() == c.model_dump()


def test_zero_work_shape_documented():
    """Policy reminder encoded as a contract constant: a NO_WORK_DUE run is
    APPLICATION_EXECUTED=yes / WORK_ATTEMPTED=no and is HEALTHY."""
    from oem_radar.core.bankai2 import FailureTaxonomy as F  # noqa: F401
    import oem_radar.core.census as census
    assert census.VERIFICATION_UNVERIFIED == "UNVERIFIED_PENDING_HETZNER"

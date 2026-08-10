from datetime import datetime, timedelta, timezone

from oem_radar.core.models import NormalizedProduct
from oem_radar.core.onboarding import baseline_review_candidate


NOW = datetime(2026, 8, 10, tzinfo=timezone.utc)


def _product(published_at):
    return NormalizedProduct(
        manufacturer="Chuwi", model="Example Laptop", source_url="https://example.test/p",
        raw_data={} if published_at is None else {"published_at": published_at},
    )


def test_recent_source_timestamp_can_create_review_only_baseline_candidate():
    c = baseline_review_candidate("chuwi", "chuwi:example", _product("2026-08-05T00:00:00+00:00"), observed_at=NOW)
    assert c is not None
    assert c["candidate_type"] == "baseline_recent_product_evidence"
    assert c["novelty_reason"] == "source_published_at_within_baseline_window"


def test_old_or_missing_or_invalid_or_future_timestamps_remain_quiet():
    for value in (None, "not-a-date", "2026-07-01T00:00:00+00:00", "2026-08-11T00:00:00+00:00", "2026-08-09T00:00:00"):
        assert baseline_review_candidate("s", "s:p", _product(value), observed_at=NOW) is None


def test_baseline_candidate_key_is_stable_for_same_source_product_and_publication_time():
    p = _product("2026-08-05T00:00:00+00:00")
    assert baseline_review_candidate("s", "s:p", p, observed_at=NOW)["dedup_key"] == baseline_review_candidate("s", "s:p", p, observed_at=NOW + timedelta(hours=1))["dedup_key"]

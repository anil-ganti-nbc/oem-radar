"""Stage 11: Evidence Fusion v0.1 persistence, conservative identity
correlation, and the discover->extract->persist->link->event pipeline.
Uses SqliteStore directly (real schema, real migration path) — no
network, no fixtures needed here since this tests the mechanism, not any
one source's parsing (that's tests/test_lenovo_psref_evidence_source.py).
"""

from __future__ import annotations

import pytest

from oem_radar.core.evidence_pipeline import candidates_for_evidence, run_evidence_source
from oem_radar.core.models import (
    ChangeType,
    EvidenceDocument,
    EvidenceCandidateType,
    EvidenceItem,
    EvidenceKind,
    EvidenceProvenance,
    EvidenceRef,
    NormalizedProduct,
)
from oem_radar.providers.sqlite import SCHEMA_VERSION, SqliteStore


@pytest.fixture()
def store(tmp_path):
    s = SqliteStore(str(tmp_path / "s.db"), str(tmp_path / "raw"))
    yield s
    s.close()


def _item(**overrides) -> EvidenceItem:
    defaults = dict(
        manufacturer="Lenovo",
        source_id="lenovo-psref",
        evidence_kind=EvidenceKind.PRODUCT_DATABASE,
        provenance=EvidenceProvenance.OFFICIAL_PRODUCT_DATABASE,
        canonical_url="https://psref.lenovo.com/Product/ThinkPad/ThinkPad_X1_Carbon_Gen_12",
        external_id="9001",
        model="ThinkPad X1 Carbon Gen 12",
    )
    defaults.update(overrides)
    return EvidenceItem(**defaults)


# ============================================================================
# schema
# ============================================================================

def test_schema_version_is_7(store):
    assert SCHEMA_VERSION == 7
    tables = {r["name"] for r in store.db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert "evidence_items" in tables
    assert "evidence_links" in tables
    assert "evidence_events" in tables


# ============================================================================
# record_evidence_item: new / updated / unchanged
# ============================================================================

def test_record_evidence_item_first_time_is_new(store):
    item_id, status = store.record_evidence_item(_item())
    assert status == "new"
    assert item_id > 0


def test_record_evidence_item_same_content_is_unchanged(store):
    store.record_evidence_item(_item())
    _, status = store.record_evidence_item(_item())
    assert status == "unchanged"


def test_record_evidence_item_changed_content_is_updated(store):
    store.record_evidence_item(_item(model="ThinkPad X1 Carbon Gen 12"))
    _, status = store.record_evidence_item(_item(model="ThinkPad X1 Carbon Gen 12 (updated name)"))
    assert status == "updated"


def test_record_evidence_item_dedupes_on_source_and_external_id(store):
    id1, _ = store.record_evidence_item(_item(external_id="9001"))
    id2, _ = store.record_evidence_item(_item(external_id="9001", model="renamed"))
    assert id1 == id2  # same row, updated in place — not a duplicate insert


def test_record_evidence_item_distinct_external_ids_are_distinct_rows(store):
    id1, _ = store.record_evidence_item(_item(external_id="9001"))
    id2, _ = store.record_evidence_item(_item(external_id="9002"))
    assert id1 != id2


# ============================================================================
# resolve_evidence_link: conservative correlation, never fuzzy
# ============================================================================

def test_resolve_evidence_link_no_existing_products_stays_unlinked(store):
    key, method = store.resolve_evidence_link(_item())
    assert key is None
    assert method == "none"


def test_resolve_evidence_link_exact_sku_match(store):
    store.append("lenovo-storefront:x1-carbon", NormalizedProduct(
        manufacturer="Lenovo", model="ThinkPad X1 Carbon Gen 12",
        vendor_sku="21KC0010US", source_url="https://example.com/x1",
    ))
    key, method = store.resolve_evidence_link(_item(sku="21KC0010US"))
    assert key == "lenovo-storefront:x1-carbon"
    assert method == "exact_sku"


def test_resolve_evidence_link_exact_mpn_match(store):
    store.append("lenovo-storefront:x1-carbon", NormalizedProduct(
        manufacturer="Lenovo", model="ThinkPad X1 Carbon Gen 12",
        vendor_sku="MPN-123", source_url="https://example.com/x1",
    ))
    key, method = store.resolve_evidence_link(_item(mpn="MPN-123"))
    assert key == "lenovo-storefront:x1-carbon"
    assert method == "exact_mpn"


def test_resolve_evidence_link_exact_model_match(store):
    store.append("lenovo-storefront:x1-carbon", NormalizedProduct(
        manufacturer="Lenovo", model="ThinkPad X1 Carbon Gen 12",
        source_url="https://example.com/x1",
    ))
    key, method = store.resolve_evidence_link(_item(model="ThinkPad X1 Carbon Gen 12"))
    assert key == "lenovo-storefront:x1-carbon"
    assert method == "exact_model_id"


def test_resolve_evidence_link_alias_match(store):
    store.append("lenovo-storefront:x1-carbon", NormalizedProduct(
        manufacturer="Lenovo", model="ThinkPad X1 Carbon Gen 12",
        source_url="https://example.com/x1", aliases=["X1C Gen 12"],
    ))
    key, method = store.resolve_evidence_link(_item(model="X1C Gen 12"))
    assert key == "lenovo-storefront:x1-carbon"
    assert method == "alias"


def test_resolve_evidence_link_never_cross_manufacturer(store):
    """A same-named product from a DIFFERENT manufacturer must never link —
    this is the exact discipline behind the Stage 8 Samsung SKU-guard."""
    store.append("other-oem:widget", NormalizedProduct(
        manufacturer="NotLenovo", model="ThinkPad X1 Carbon Gen 12",
        vendor_sku="21KC0010US", source_url="https://example.com/x",
    ))
    key, method = store.resolve_evidence_link(_item(sku="21KC0010US"))
    assert key is None
    assert method == "none"


def test_resolve_evidence_link_no_fuzzy_partial_model_match(store):
    store.append("lenovo-storefront:x1-carbon", NormalizedProduct(
        manufacturer="Lenovo", model="ThinkPad X1 Carbon Gen 12",
        source_url="https://example.com/x1",
    ))
    # A materially different model — must stay unlinked, not "close enough."
    key, method = store.resolve_evidence_link(_item(model="ThinkPad X1 Yoga Gen 9"))
    assert key is None
    assert method == "none"


# ============================================================================
# evidence_timeline
# ============================================================================

def test_evidence_timeline_scoped_by_manufacturer(store):
    store.record_evidence_item(_item(external_id="1", manufacturer="Lenovo"))
    store.record_evidence_item(_item(external_id="2", manufacturer="HP", source_id="hp-catalog"))
    rows = store.evidence_timeline(manufacturer="Lenovo")
    assert len(rows) == 1
    assert rows[0]["manufacturer"] == "Lenovo"


def test_evidence_timeline_unscoped_returns_all(store):
    store.record_evidence_item(_item(external_id="1", manufacturer="Lenovo"))
    store.record_evidence_item(_item(external_id="2", manufacturer="HP", source_id="hp-catalog"))
    assert len(store.evidence_timeline()) == 2


# ============================================================================
# run_evidence_source pipeline
# ============================================================================

class _FakeEvidenceSource:
    """Two real-shaped items, one already-withdrawn — mirrors PSREF's own
    extract() output shape without depending on that module."""

    config_schema = dict

    def discover(self, fetcher):
        return [
            EvidenceRef(external_id="1", url="https://x/1", inline_payload={"n": "A"}),
            EvidenceRef(external_id="2", url="https://x/2", inline_payload={"n": "B"}),
        ]

    def fetch(self, ref, fetcher):
        return EvidenceDocument(url=ref.url, status=200, body=ref.inline_payload["n"])

    def extract(self, doc):
        return [_item(external_id=doc.url.rsplit("/", 1)[-1], model=doc.body,
                      raw_data={"Withdraw": False, "IsNewProduct": True})]


def test_pipeline_first_run_emits_added_events(store):
    stats = run_evidence_source("lenovo-psref", _FakeEvidenceSource(), fetcher=None, store=store)
    assert stats.discovered == 2
    assert stats.new_items == 2
    assert stats.events == 2
    events = store.db.execute("SELECT event_type FROM evidence_events").fetchall()
    assert [e["event_type"] for e in events] == ["added", "added"]


def test_pipeline_repeat_run_unchanged_emits_no_events(store):
    run_evidence_source("lenovo-psref", _FakeEvidenceSource(), fetcher=None, store=store)
    stats2 = run_evidence_source("lenovo-psref", _FakeEvidenceSource(), fetcher=None, store=store)
    assert stats2.unchanged_items == 2
    assert stats2.events == 0


def test_pipeline_changed_content_emits_updated_event(store):
    class _ChangedSecondRun(_FakeEvidenceSource):
        def extract(self, doc):
            return [_item(external_id=doc.url.rsplit("/", 1)[-1], model=doc.body + "-CHANGED")]

    run_evidence_source("lenovo-psref", _FakeEvidenceSource(), fetcher=None, store=store)
    stats2 = run_evidence_source("lenovo-psref", _ChangedSecondRun(), fetcher=None, store=store)
    assert stats2.updated_items == 2
    events = store.db.execute(
        "SELECT event_type FROM evidence_events WHERE event_type='updated'"
    ).fetchall()
    assert len(events) == 2


def test_evidence_never_writes_to_change_events(store):
    """Stage 11.1's core invariant. Stage 11 emitted a change_event per
    evidence item, which at production scale made 44% of the alert stream
    things that were not product changes and could not be opened."""
    run_evidence_source("lenovo-psref", _FakeEvidenceSource(), fetcher=None, store=store)
    assert store.db.execute("SELECT COUNT(*) FROM change_events").fetchone()[0] == 0
    assert store.db.execute("SELECT COUNT(*) FROM evidence_events").fetchone()[0] == 2
    # ...and nothing was queued for delivery as an alert, either.
    assert store.db.execute("SELECT COUNT(*) FROM notifications").fetchone()[0] == 0


def test_current_unlinked_product_database_is_a_review_only_new_model_candidate(store):
    item = _item(raw_data={"Withdraw": False, "IsNewProduct": True})
    candidates = candidates_for_evidence(item, None)
    assert [c.candidate_type for c in candidates] == [EvidenceCandidateType.NEW_MODEL_EVIDENCE]
    assert candidates[0].external_id == "9001"


def test_withdrawn_psref_record_never_becomes_a_candidate():
    assert candidates_for_evidence(_item(raw_data={"Withdraw": True, "IsNewProduct": True}), None) == []


def test_current_but_not_new_psref_record_is_stale_catalogue_not_a_candidate():
    assert candidates_for_evidence(_item(raw_data={"Withdraw": False, "IsNewProduct": False}), None) == []


def test_known_product_in_new_region_is_regional_availability_evidence():
    candidates = candidates_for_evidence(
        _item(region="US", raw_data={"Withdraw": False, "IsNewProduct": True}), "lenovo-storefront:x1"
    )
    assert [c.candidate_type for c in candidates] == [EvidenceCandidateType.REGIONAL_PRODUCT_EVIDENCE]
    assert candidates[0].linked_product_key == "lenovo-storefront:x1"


def test_unlinked_regional_page_is_not_mislabelled_availability():
    candidates = candidates_for_evidence(_item(region="US", raw_data={"Withdraw": False, "IsNewProduct": True}), None)
    assert candidates[0].candidate_type == EvidenceCandidateType.NEW_MODEL_EVIDENCE


def test_candidate_dedup_key_is_stable_and_distinguishes_region():
    a = candidates_for_evidence(_item(raw_data={"Withdraw": False, "IsNewProduct": True}), None)[0]
    b = candidates_for_evidence(_item(raw_data={"Withdraw": False, "IsNewProduct": True}), None)[0]
    regional = candidates_for_evidence(
        _item(region="US", raw_data={"Withdraw": False, "IsNewProduct": True}), "lenovo:x1"
    )[0]
    assert a.dedup_key() == b.dedup_key()
    assert a.dedup_key() != regional.dedup_key()


def test_candidate_is_persisted_only_in_evidence_event_metadata(store):
    stats = run_evidence_source("lenovo-psref", _FakeEvidenceSource(), fetcher=None, store=store)
    assert len(stats.candidates) == 2
    meta = store.db.execute("SELECT meta_json FROM evidence_events ORDER BY id LIMIT 1").fetchone()[0]
    assert "new_model_evidence" in meta
    assert store.db.execute("SELECT COUNT(*) FROM change_events").fetchone()[0] == 0


def test_evidence_events_carry_no_severity_or_review_surface(store):
    """An evidence event is a log line, not a rateable alert: it has no
    severity column to sort by and no alert_id to review against."""
    run_evidence_source("lenovo-psref", _FakeEvidenceSource(), fetcher=None, store=store)
    cols = {r[1] for r in store.db.execute("PRAGMA table_info(evidence_events)")}
    assert "severity" not in cols
    assert cols == {"id", "evidence_item_id", "event_type", "detected_at", "meta_json"}


def test_record_evidence_event_rejects_unknown_type(store):
    item_id, _ = store.record_evidence_item(_item())
    with pytest.raises(ValueError):
        store.record_evidence_event(item_id, "deleted")


def test_pipeline_broken_discover_does_not_raise(store):
    class _Broken:
        config_schema = dict

        def discover(self, fetcher):
            raise ConnectionError("network down")

    stats = run_evidence_source("broken-source", _Broken(), fetcher=None, store=store)
    assert stats.discovered == 0
    assert stats.errors


def test_pipeline_one_bad_ref_does_not_lose_others(store):
    class _PartiallyBroken(_FakeEvidenceSource):
        def fetch(self, ref, fetcher):
            if ref.external_id == "1":
                raise ValueError("boom")
            return super().fetch(ref, fetcher)

    stats = run_evidence_source("lenovo-psref", _PartiallyBroken(), fetcher=None, store=store)
    assert stats.new_items == 1
    assert len(stats.errors) == 1

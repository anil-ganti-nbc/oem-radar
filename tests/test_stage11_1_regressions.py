"""Stage 11.1 regression suite.

Three regressions shipped together in Stage 11 and all three had the same
root cause: the UI was describing a data model that no longer matched the
data. These tests pin the corrected boundaries so the next stage cannot
quietly re-collapse them.

  1. The OEM filter must list every *configured* OEM, never a set derived
     from whatever rows happened to be queried.
  2. Evidence must not appear in the product-alert stream, at any layer.
  3. Everything the UI renders must resolve to a real detail page.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from oem_radar.core.config import ManufacturerConfig, OemConfig, RadarConfig, SourceConfig
from oem_radar.core.evidence_pipeline import run_evidence_source
from oem_radar.core.models import (
    ChangeEvent,
    ChangeType,
    EvidenceDocument,
    EvidenceItem,
    EvidenceKind,
    EvidenceProvenance,
    EvidenceRef,
    Severity,
)
from oem_radar.core.runner import sync_oem_registry
from oem_radar.dashboard import _EVIDENCE_PATH_RE
from oem_radar.dashboard.data import (
    collect,
    collect_alert_detail,
    collect_evidence_detail,
    collect_oem_registry,
)
from oem_radar.dashboard.render import render, render_evidence_page
from oem_radar.providers.sqlite import SqliteStore, connect_readonly


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

def _oem(name: str, source_id: str, enabled: bool = True) -> OemConfig:
    return OemConfig(
        manufacturer=ManufacturerConfig(name=name, country="CN"),
        sources=[SourceConfig(id=source_id, engine="shopify",
                              base_url=f"https://{source_id}.example",
                              discovery=["products_json"], enabled=enabled)],
    )


# Deliberately mixed: one that will be crawled, one disabled, one simply
# never touched. All three must reach the dropdown.
CONFIGURED = {
    "Crawled": _oem("Crawled", "crawled-shopify"),
    "Disabled": _oem("Disabled", "disabled-shopify", enabled=False),
    "NeverRun": _oem("NeverRun", "neverrun-shopify"),
}


@pytest.fixture()
def store(tmp_path):
    s = SqliteStore(str(tmp_path / "r.db"), str(tmp_path / "raw"))
    yield s
    s.close()


def _evidence_item(external_id="123", model="ThinkPad X1 Carbon Gen 12", **kw):
    return EvidenceItem(
        manufacturer=kw.pop("manufacturer", "Lenovo"),
        source_id="lenovo-psref",
        evidence_kind=EvidenceKind.PRODUCT_DATABASE,
        provenance=EvidenceProvenance.OFFICIAL_PRODUCT_DATABASE,
        canonical_url=f"https://psref.lenovo.com/Product/{external_id}",
        external_id=external_id,
        model=model,
        title=kw.pop("title", model),
        raw_data=kw.pop("raw_data", {"ProductID": external_id, "Withdraw": "N"}),
        **kw,
    )


class _PsrefLike:
    """Minimal evidence source: two real items, bulk-inline like PSREF."""

    config_schema = dict

    def discover(self, fetcher):
        return [EvidenceRef(external_id=i, url=f"https://psref.example/{i}",
                            inline_payload={"model": f"ThinkPad Model {i}"})
                for i in ("2364", "2365")]

    def fetch(self, ref, fetcher):
        return EvidenceDocument(url=ref.url, status=200,
                                body=ref.inline_payload["model"])

    def extract(self, doc):
        ext = doc.url.rsplit("/", 1)[-1]
        return [_evidence_item(external_id=ext, model=doc.body)]


def _product_alert(store, product_key="crawled-shopify:p1"):
    """A real product change_event so 'products unaffected' is testable."""
    store.ensure_manufacturer("Crawled", "CN", [])
    return store.record_event(ChangeEvent(
        product_key=product_key, change_type=ChangeType.NEW_PRODUCT,
        severity=Severity.BREAKING, field="model", new_value="Mini PC X1",
    ))


# ---------------------------------------------------------------------------
# Regression #1 — the manufacturer dropdown
# ---------------------------------------------------------------------------

def test_registry_contains_every_configured_oem_before_any_crawl(store):
    """The dropdown must be complete on a DB that has never crawled.

    Root cause of the original bug: `manufacturers` was populated as a side
    effect of crawling, so config-only OEMs did not exist to be listed."""
    synced = sync_oem_registry(store, CONFIGURED)
    assert synced == 3
    names = {m["name"] for m in collect_oem_registry(store.db)}
    assert names == {"Crawled", "Disabled", "NeverRun"}


def test_registry_includes_oems_whose_only_source_is_disabled(store):
    sync_oem_registry(store, CONFIGURED)
    names = {m["name"] for m in collect_oem_registry(store.db)}
    assert "Disabled" in names, "a disabled source must not hide its OEM"


def test_registry_survives_being_synced_twice(store):
    sync_oem_registry(store, CONFIGURED)
    sync_oem_registry(store, CONFIGURED)
    names = [m["name"] for m in collect_oem_registry(store.db)]
    assert len(names) == len(set(names)) == 3


def test_registry_is_committed_not_rolled_back_on_close(tmp_path):
    """The sync writes and closes; a *separate* reader must still see it.

    This is the exact failure mode caught during Stage 11.1: the upserts
    were uncommitted, so `store.close()` discarded them and the dropdown
    stayed short with no error anywhere."""
    db_path = str(tmp_path / "r.db")
    s = SqliteStore(db_path, str(tmp_path / "raw"))
    sync_oem_registry(s, CONFIGURED)
    s.close()

    conn = connect_readonly(db_path)
    try:
        names = {m["name"] for m in collect_oem_registry(conn)}
    finally:
        conn.close()
    assert names == {"Crawled", "Disabled", "NeverRun"}


def test_dropdown_is_independent_of_the_event_window(store):
    """limit=0 starves every event-derived list. The OEM list must not care."""
    sync_oem_registry(store, CONFIGURED)
    _product_alert(store)
    data = collect(store.db, limit=0)
    assert data["events"] == []
    assert {m["name"] for m in data["manufacturers"]} == {
        "Crawled", "Disabled", "NeverRun"}


def test_dropdown_is_independent_of_evidence(store):
    """Evidence carries a manufacturer string. It must never inject OEMs
    into (or remove them from) the registry-backed filter."""
    sync_oem_registry(store, CONFIGURED)
    store.record_evidence_item(_evidence_item(manufacturer="Lenovo"))
    data = collect(store.db)
    names = {m["name"] for m in data["manufacturers"]}
    assert "Lenovo" not in names, "an evidence row is not an OEM registration"
    assert names == {"Crawled", "Disabled", "NeverRun"}


def test_render_builds_both_oem_selects_from_one_helper(store):
    """One authoritative code path, not three almost-identical ones."""
    sync_oem_registry(store, CONFIGURED)
    html = render(collect(store.db))
    assert html.count("function oemRegistry()") == 1
    # Both manufacturer controls consume the same computed option list.
    assert "const oemOptions=" in html
    assert "document.getElementById('f-man').innerHTML=oemOptions;" in html
    assert "evMan.innerHTML=oemOptions;" in html
    # And nothing rebuilds an OEM list off the event window any more.
    assert "DATA.events.map(e=>e.manufacturer)" not in html


def test_change_type_filter_is_not_derived_from_the_visible_window(store):
    """Same class of bug as the OEM list: a LIMIT-bounded source silently
    drops filter options for older change types."""
    sync_oem_registry(store, CONFIGURED)
    _product_alert(store)
    store.record_event(ChangeEvent(
        product_key="crawled-shopify:p2", change_type=ChangeType.PRICE_CHANGED,
        severity=Severity.NOTABLE, field="price", old_value=1, new_value=2))
    data = collect(store.db, limit=0)
    assert data["events"] == []
    assert set(data["change_types"]) == {"new_product", "price_changed"}


# ---------------------------------------------------------------------------
# Regression #2 — evidence out of the alert stream
# ---------------------------------------------------------------------------

def test_evidence_run_creates_no_change_events(store):
    run_evidence_source("lenovo-psref", _PsrefLike(), fetcher=None, store=store)
    assert store.db.execute("SELECT COUNT(*) FROM change_events").fetchone()[0] == 0
    assert store.db.execute("SELECT COUNT(*) FROM evidence_events").fetchone()[0] == 2


def test_evidence_excluded_from_default_all_changes_view(store):
    sync_oem_registry(store, CONFIGURED)
    alert_id = _product_alert(store)
    run_evidence_source("lenovo-psref", _PsrefLike(), fetcher=None, store=store)

    data = collect(store.db)
    assert [e["id"] for e in data["events"]] == [alert_id]
    assert all(e["type"] not in ("support_artifact_added", "support_artifact_updated")
               for e in data["events"])
    assert not any(str(e["product_key"]).startswith("evidence:") for e in data["events"])


def test_evidence_excluded_even_on_an_unmigrated_database(tmp_path):
    """Belt and braces: a v6 DB still carrying Stage 11's rows must read
    clean, because the exclusion is a query predicate, not only a migration."""
    db_path = str(tmp_path / "legacy.db")
    s = SqliteStore(db_path, str(tmp_path / "raw"))
    good = _product_alert(s)
    # Hand-write exactly what Stage 11's pipeline used to produce.
    s.db.execute(
        "INSERT INTO change_events(product_key, change_type, severity, meta_json, detected_at) "
        "VALUES ('evidence:lenovo-psref:2364','support_artifact_added',3,'{}','2026-08-07T00:00:00+00:00')")
    s.db.commit()
    s.close()

    conn = connect_readonly(db_path)
    try:
        data = collect(conn)
    finally:
        conn.close()
    assert [e["id"] for e in data["events"]] == [good]
    assert data["summary"]["events"] == 1
    assert data["summary"]["unreviewed_events"] == 1


def test_summary_counters_count_products_not_evidence(store):
    sync_oem_registry(store, CONFIGURED)
    _product_alert(store)
    run_evidence_source("lenovo-psref", _PsrefLike(), fetcher=None, store=store)
    summary = collect(store.db)["summary"]
    assert summary["events"] == 1, "product alert count must exclude evidence"
    assert summary["unreviewed_events"] == 1
    assert summary["evidence_items"] == 2, "evidence is counted, separately"


def test_migration_moves_stage11_evidence_rows_without_losing_them(tmp_path):
    """The v7 migration is a MOVE. Product alerts survive untouched and
    every evidence row reappears in the evidence event log."""
    db_path = str(tmp_path / "mig.db")
    s = SqliteStore(db_path, str(tmp_path / "raw"))
    kept = _product_alert(s)
    item_id, _ = s.record_evidence_item(_evidence_item(external_id="2364"))
    s.db.execute(
        "INSERT INTO change_events(product_key, change_type, severity, meta_json, detected_at) "
        "VALUES ('evidence:lenovo-psref:2364','support_artifact_added',3,"
        "'{\"manufacturer\":\"Lenovo\"}','2026-08-07T00:00:00+00:00')")
    # Simulate a v6 DB so migrate() actually runs the v7 step.
    s.db.execute("DELETE FROM evidence_events")
    s.db.execute("DELETE FROM schema_migrations WHERE version=7")
    s.db.commit()
    s.close()

    s2 = SqliteStore(db_path, str(tmp_path / "raw"))  # migrate() runs here
    try:
        remaining = s2.db.execute("SELECT id FROM change_events").fetchall()
        assert [r["id"] for r in remaining] == [kept], "product alert must survive"
        moved = s2.db.execute(
            "SELECT evidence_item_id, event_type, detected_at, meta_json "
            "FROM evidence_events").fetchall()
        assert len(moved) == 1
        assert moved[0]["evidence_item_id"] == item_id
        assert moved[0]["event_type"] == "added"
        assert moved[0]["detected_at"] == "2026-08-07T00:00:00+00:00"
        assert json.loads(moved[0]["meta_json"])["manufacturer"] == "Lenovo"
    finally:
        s2.close()


# ---------------------------------------------------------------------------
# Regression #3 — no dead cards; evidence is a first-class entity
# ---------------------------------------------------------------------------

def test_every_rendered_evidence_row_resolves_to_a_detail_page(store):
    run_evidence_source("lenovo-psref", _PsrefLike(), fetcher=None, store=store)
    data = collect(store.db)
    assert data["evidence_items"], "expected evidence to render"
    for item in data["evidence_items"]:
        detail = collect_evidence_detail(store.db, item["id"])
        assert detail is not None, f"evidence {item['id']} has no detail page"
        assert detail["canonical_url"]
        page = render_evidence_page(detail)
        assert page.startswith("<!DOCTYPE html>")


def test_evidence_detail_exposes_the_facts_the_brief_asked_for(store):
    run_evidence_source("lenovo-psref", _PsrefLike(), fetcher=None, store=store)
    eid = collect(store.db)["evidence_items"][0]["id"]
    d = collect_evidence_detail(store.db, eid)

    assert d["provenance"] == "official_product_database"   # provenance
    assert d["source_id"] == "lenovo-psref"                 # source
    assert d["evidence_kind"] == "product_database"         # evidence type
    assert d["observed_at"]                                 # timestamps
    assert isinstance(d["links"], list)                     # linked products
    assert d["external_id"] and d["content_hash"]           # raw identifiers
    assert d["raw_data"]["ProductID"] == d["external_id"]   # supporting metadata

    page = render_evidence_page(d)
    for expected in ("Provenance", "Evidence kind", "External ID",
                     "Linked products", "Observation history",
                     "Raw source payload"):
        assert expected in page


def test_evidence_detail_page_offers_no_review_form(store):
    """Evidence is not rated HIT/NOISE, so it must not present the control
    that says it is — a review page with no valid outcome is a dead end."""
    run_evidence_source("lenovo-psref", _PsrefLike(), fetcher=None, store=store)
    eid = collect(store.db)["evidence_items"][0]["id"]
    page = render_evidence_page(collect_evidence_detail(store.db, eid))
    assert "name=\"outcome\"" not in page
    assert "/api/alerts/" not in page
    assert "Why there is no review form here" in page


def test_evidence_rows_link_to_evidence_routes_not_alert_routes(store):
    run_evidence_source("lenovo-psref", _PsrefLike(), fetcher=None, store=store)
    html = render(collect(store.db))
    assert "/evidence/${e.id}" in html
    # The evidence renderer must not mint /alerts/ links for evidence ids.
    evidence_js = html[html.index("function renderEvidence()"):]
    evidence_js = evidence_js[:evidence_js.index("\n}")]
    assert "/alerts/" not in evidence_js


def test_evidence_route_pattern_matches_detail_urls():
    assert _EVIDENCE_PATH_RE.match("/evidence/42")
    assert _EVIDENCE_PATH_RE.match("/evidence/42/")
    assert not _EVIDENCE_PATH_RE.match("/evidence/abc")
    assert not _EVIDENCE_PATH_RE.match("/alerts/42")


def test_unknown_evidence_id_is_a_clean_miss_not_a_crash(store):
    assert collect_evidence_detail(store.db, 999999) is None


def test_navigation_links_both_directions_between_products_and_evidence(store):
    sync_oem_registry(store, CONFIGURED)
    _product_alert(store)
    run_evidence_source("lenovo-psref", _PsrefLike(), fetcher=None, store=store)
    html = render(collect(store.db))
    assert 'href="/?tab=evidence"' in html          # overview -> evidence
    assert 'data-tab="evidence"' in html

    eid = collect(store.db)["evidence_items"][0]["id"]
    page = render_evidence_page(collect_evidence_detail(store.db, eid))
    assert 'href="/?tab=evidence"' in page          # evidence detail -> list
    assert 'href="/?tab=events"' in page            # evidence detail -> alerts


# ---------------------------------------------------------------------------
# The product side must be untouched by all of the above
# ---------------------------------------------------------------------------

def test_product_alerts_still_render_and_review_normally(store):
    sync_oem_registry(store, CONFIGURED)
    alert_id = _product_alert(store)
    run_evidence_source("lenovo-psref", _PsrefLike(), fetcher=None, store=store)

    detail = collect_alert_detail(store.db, alert_id)
    assert detail is not None and detail["type"] == "new_product"
    assert detail["review_status"] == "UNREVIEWED"

    rev = store.upsert_review(alert_id, outcome="HIT", reviewer="tester")
    assert rev["outcome"] == "HIT"
    assert collect(store.db)["events"][0]["review_status"] == "HIT"


def test_review_workflow_rejects_evidence_ids(store):
    """Evidence ids share no namespace with alert ids; reviewing one must
    fail loudly rather than silently create an orphan review row."""
    from oem_radar.core.feedback import FeedbackError

    item_id, _ = store.record_evidence_item(_evidence_item())
    with pytest.raises(FeedbackError):
        store.upsert_review(item_id, outcome="HIT")
    assert store.db.execute("SELECT COUNT(*) FROM alert_reviews").fetchone()[0] == 0


def test_evidence_filtering_controls_exist_and_are_scoped_to_evidence(store):
    run_evidence_source("lenovo-psref", _PsrefLike(), fetcher=None, store=store)
    html = render(collect(store.db))
    for control in ('id="ev-q"', 'id="f-ev-man"', 'id="f-ev-kind"'):
        assert control in html
    # The evidence filters must not be wired to the product events renderer.
    assert "['ev-q','f-ev-man','f-ev-kind'].forEach" in html
    assert "el.addEventListener('input',renderEvidence)" in html

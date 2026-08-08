"""Dashboard integration pass: navigation, discoverability, and homepage
metrics that expose the feedback/health functionality already built in
Stages 1-4.1 through the main GUI. See docs/CURRENT_STATUS.md."""

from __future__ import annotations

from pathlib import Path

import pytest

from oem_radar.core.models import ChangeEvent, ChangeType, Severity
from oem_radar.dashboard.data import collect, collect_alert_detail
from oem_radar.dashboard.render import render, render_feedback_page, render_review_page
from oem_radar.core.feedback_analytics import build_metrics_payload
from oem_radar.providers.sqlite import SqliteStore, connect_readonly


@pytest.fixture()
def store(tmp_path):
    s = SqliteStore(str(tmp_path / "r.db"), str(tmp_path / "raw"))
    yield s
    s.close()


def _eid(store, key="src:k12", change_type=ChangeType.IMAGES_CHANGED, field="images"):
    return store.record_event(
        ChangeEvent(product_key=key, change_type=change_type, field=field,
                    severity=Severity.NOTABLE)
    )


# ---- navigation present across pages ---------------------------------------

def test_homepage_links_to_feedback(store, tmp_path):
    store.close()
    conn = connect_readonly(str(tmp_path / "r.db"))
    data = collect(conn)
    conn.close()
    html = render(data)
    assert 'href="/feedback"' in html


def test_homepage_exposes_review_status_and_alert_links(store, tmp_path):
    eid = _eid(store)
    store.upsert_review(eid, outcome="HIT", reason_codes=["VALID_CONFIRMATION_SIGNAL"])
    store.close()
    conn = connect_readonly(str(tmp_path / "r.db"))
    data = collect(conn)
    conn.close()
    ev = next(e for e in data["events"] if e["id"] == eid)
    assert ev["review_status"] == "HIT"
    html = render(data)
    # client-side card renderer links every event id to its alert page and
    # renders the review badge from review_status
    assert "/alerts/${e.id}" in html
    assert "rev-${esc(rev)}" in html


def test_homepage_has_unreviewed_review_action(store, tmp_path):
    _eid(store)
    store.close()
    conn = connect_readonly(str(tmp_path / "r.db"))
    data = collect(conn)
    conn.close()
    html = render(data)
    assert "review=UNREVIEWED" in html
    assert "tab=events" in html


def test_homepage_nav_present(store, tmp_path):
    store.close()
    conn = connect_readonly(str(tmp_path / "r.db"))
    data = collect(conn)
    conn.close()
    html = render(data)
    assert 'class="crumbs"' in html
    assert 'href="/"' in html and 'href="/feedback"' in html


def test_feedback_page_links_back_to_dashboard(store, tmp_path):
    store.close()
    conn = connect_readonly(str(tmp_path / "r.db"))
    metrics = build_metrics_payload(conn)
    conn.close()
    html = render_feedback_page(metrics, [], csrf_token="tok")
    assert 'href="/"' in html
    assert 'class="crumbs"' in html


def test_alert_page_links_back_to_alerts_and_overview(store, tmp_path):
    eid = _eid(store)
    store.close()
    conn = connect_readonly(str(tmp_path / "r.db"))
    detail = collect_alert_detail(conn, eid)
    conn.close()
    html = render_review_page(detail, csrf_token="tok")
    assert 'href="/"' in html
    assert 'tab=events' in html
    assert 'href="/feedback"' in html


def test_alert_page_prev_next_links(store, tmp_path):
    e1 = _eid(store, key="src:a", change_type=ChangeType.NEW_PRODUCT, field=None)
    e2 = _eid(store, key="src:b", change_type=ChangeType.NEW_PRODUCT, field=None)
    store.close()
    conn = connect_readonly(str(tmp_path / "r.db"))
    detail = collect_alert_detail(conn, e1)
    conn.close()
    html = render_review_page(detail, csrf_token="tok")
    assert f"/alerts/{e2}" in html  # next link present, no prev (e1 is first)


# ---- homepage metrics reuse existing analytics, not reimplemented ---------

def test_homepage_metrics_reuse_feedback_analytics(store, tmp_path):
    eid = _eid(store)
    store.upsert_review(eid, outcome="NOISE", reason_codes=["CDN_URL_CHURN"])
    store.close()
    conn = connect_readonly(str(tmp_path / "r.db"))
    data = collect(conn)
    expected = build_metrics_payload(conn)
    conn.close()
    assert data["feedback_summary"] == expected["summary"]
    assert data["feedback_summary"]["noise_count"] == 1


def test_collector_health_surfaced_from_run_stats(store, tmp_path):
    man_id = store.ensure_manufacturer("Acme", None, [])
    store.ensure_source("acme-shopify", man_id, "shopify", "https://acme.example", {})
    run_id = store.run_started("acme-shopify")
    store.run_finished(run_id, "ok", {"health": "degraded", "health_reason": "CATALOG_WARN_THRESHOLD"}, [])
    store.close()
    conn = connect_readonly(str(tmp_path / "r.db"))
    data = collect(conn)
    conn.close()
    row = next(c for c in data["collector_health"] if c["source"] == "acme-shopify")
    assert row["health"] == "degraded"
    assert data["summary"]["degraded_collectors"] == 1
    html = render(data)
    # health rows are rendered client-side from the embedded DATA payload;
    # verify the data + renderer plumbing are both present in the page
    assert "acme-shopify" in html
    assert '"degraded"' in html
    assert "health-row" in html  # client-side renderer for collector_health


# ---- seen state vs review state stay independent ---------------------------

def test_seen_state_independent_of_review_state(store, tmp_path):
    """Marking a component 'seen' (hardware feed) must not touch alert review
    status, and vice versa — the two are unrelated axes of state."""
    eid = _eid(store)
    store.upsert_review(eid, outcome="HIT", reason_codes=["VALID_CONFIRMATION_SIGNAL"])
    store.seed_components([("cpu", "Some Unseen Chip 9999")])
    # a plain seed with source defaulting to 'known' does not touch reviews;
    # simulate a discovered component instead to exercise mark_component_seen
    store.db.execute(
        "INSERT INTO components(kind, canonical_name, first_raw, source) "
        "VALUES ('cpu','discovered-chip','Discovered Chip','discovered')"
    )
    store.db.commit()
    changed = store.mark_component_seen(["discovered-chip"])
    assert changed == 1
    conn = connect_readonly(str(tmp_path / "r.db"))
    detail = collect_alert_detail(conn, eid)
    conn.close()
    assert detail["review_status"] == "HIT"  # untouched by the seen action
    store.close()


# ---- escaping ---------------------------------------------------------------

def test_feedback_page_escapes_suggestion_content(store, tmp_path):
    store.close()
    conn = connect_readonly(str(tmp_path / "r.db"))
    metrics = build_metrics_payload(conn)
    conn.close()
    malicious = [{
        "id": 1, "status": "PROPOSED", "collector": "<img src=x onerror=alert(1)>",
        "alert_type": "component_changed",
        "explanation": "<script>alert(2)</script>",
        "supporting_alert_count": 5, "estimated_noise_reduction": 0.5,
        "estimated_signal_loss": 0.0,
    }]
    html = render_feedback_page(metrics, malicious, csrf_token="tok")
    assert "<script>alert(2)</script>" not in html
    assert "<img src=x onerror=alert(1)>" not in html


# ---- no raw API endpoints exposed as primary nav ---------------------------

def test_no_raw_api_endpoints_in_navigation(store, tmp_path):
    store.close()
    conn = connect_readonly(str(tmp_path / "r.db"))
    data = collect(conn)
    metrics = build_metrics_payload(conn)
    conn.close()
    home_html = render(data)
    feedback_html = render_feedback_page(metrics, [], csrf_token="tok")
    import re
    for html in (home_html, feedback_html):
        crumbs = re.search(r'<nav class="crumbs">.*?</nav>', html, re.S)
        assert crumbs is not None
        assert "/api/" not in crumbs.group(0)


# ---- no frontend framework dependency introduced ---------------------------

def test_no_frontend_framework_dependency():
    pyproject = (Path(__file__).parent.parent / "pyproject.toml").read_text(encoding="utf-8")
    for banned in ("react", "vue", "svelte", "bootstrap", "tailwind"):
        assert banned not in pyproject.lower()
    assert not (Path(__file__).parent.parent / "package.json").exists()

"""Epoch 2 production activation, item 1: baseline events must not
masquerade as fresh alerts.

Root cause: `core/pipeline.py::run_source` already marks every event
produced by a source's first-ever crawl with `event.meta["baseline"] =
True` (explicit, deterministic — never inferred from a timestamp or from
`notifications.status`). That marker was faithfully persisted into
`change_events.meta_json` all along, but nothing downstream ever read
it: the dashboard's default "All changes" view, its summary counters,
and `core.feedback_analytics`'s signal/noise metrics all counted
baseline events as ordinary alerts. On the real Epoch 2 database this
put 1,875 baseline records in front of the first genuine alert.

Fix (Approach B — baseline events stay real ChangeEvent rows for
diagnostics, per the pipeline's own pre-existing "record for history"
comment; they are excluded from the default view and from analytics via
one shared SQL predicate, `core.models.EXCLUDE_BASELINE_EVENTS_SQL`,
reused by `dashboard.data` and `core.feedback_analytics` — the same
single-predicate discipline Stage 11.1 used for the evidence/product
split). All tests here use temp databases; the real Epoch 2 database is
never touched or re-baselined to prove this.
"""

from __future__ import annotations

import copy

import pytest

from oem_radar.core.config import (
    ManufacturerConfig,
    OemConfig,
    RadarConfig,
    SourceConfig,
)
from oem_radar.core.feedback_analytics import compute_summary
from oem_radar.core.knownhw import SEED_COMPONENTS
from oem_radar.core.runner import run_all
from oem_radar.dashboard.data import collect, collect_baseline_events
from oem_radar.engines import shopify  # noqa: F401 (registers engine)
from oem_radar.providers.discord import DiscordNotifier
from oem_radar.providers.sqlite import SqliteStore, connect_readonly
from test_runner import BASE, FIXTURE, RouteFetcher


@pytest.fixture()
def baselined_then_changed(tmp_path):
    """Reproduces the real Epoch 2 shape at small scale: one source's
    baseline crawl (3 products, all flagged baseline), then a second
    crawl with one genuine price change and, separately, a second
    source whose baseline happens later (so both a NEW_PRODUCT baseline
    event and a real post-baseline NEW_PRODUCT-shaped update exist)."""
    radar = RadarConfig(db_path=str(tmp_path / "r.db"), raw_dir=str(tmp_path / "raw"),
                        baseline_quiet=True)
    oems = {"GMKtec": OemConfig(
        manufacturer=ManufacturerConfig(name="GMKtec", country="CN"),
        sources=[SourceConfig(id="gmktec-shopify", engine="shopify", base_url=BASE,
                              discovery=["products_json"])],
    )}
    store = SqliteStore(radar.db_path, radar.raw_dir)
    store.seed_components(SEED_COMPONENTS)
    sent = []
    notifier = DiscordNotifier(store, "https://hook.example", 3,
                               sender=lambda u, p: (sent.append(p), None) and (True, None))

    # Baseline crawl: 3 products, all events flagged baseline, nothing sent.
    stats = run_all(radar, oems, store, notifier, RouteFetcher(FIXTURE), force=True)
    assert stats[0].snapshots_written == 3 and sent == []

    # A genuine post-baseline change: real signal, must remain visible.
    catalog = copy.deepcopy(FIXTURE)
    next(p for p in catalog["products"] if "k12" in p["handle"])["variants"][0]["price"] = "779.99"
    run_all(radar, oems, store, notifier, RouteFetcher(catalog), force=True)

    store.close()
    yield tmp_path / "r.db"


def test_baseline_events_are_marked_in_meta_json(baselined_then_changed):
    conn = connect_readonly(str(baselined_then_changed))
    rows = conn.execute("SELECT meta_json FROM change_events").fetchall()
    assert len(rows) == 4  # 3 baseline + 1 real price change
    baseline_flags = [r["meta_json"] for r in rows]
    assert sum(1 for m in baseline_flags if '"baseline": true' in m) == 3
    conn.close()


def test_fresh_baseline_cannot_flood_all_changes(baselined_then_changed):
    """The core bug: 3 baseline NEW_PRODUCT events must not appear in the
    default event list. Only the 1 genuine price change should."""
    conn = connect_readonly(str(baselined_then_changed))
    data = collect(conn)
    conn.close()
    assert len(data["events"]) == 1
    assert data["events"][0]["type"] == "price_changed"
    assert data["summary"]["events"] == 1


def test_baseline_events_are_counted_separately_not_silently_dropped(baselined_then_changed):
    """Excluded from the default view, but never hidden entirely --
    the count is a real, visible summary field."""
    conn = connect_readonly(str(baselined_then_changed))
    data = collect(conn)
    conn.close()
    assert data["summary"]["baseline_events"] == 3


def test_baseline_events_inspectable_via_diagnostic_query(baselined_then_changed):
    conn = connect_readonly(str(baselined_then_changed))
    rows = collect_baseline_events(conn)
    conn.close()
    assert len(rows) == 3
    assert all(r["type"] == "new_product" for r in rows)


def test_genuine_new_product_after_baseline_remains_visible(tmp_path):
    """A second source that baselines later must still show its genuine
    NEW_PRODUCT the moment a *third* crawl adds one for real -- baseline
    exclusion must not blanket-hide every new_product event forever."""
    radar = RadarConfig(db_path=str(tmp_path / "r.db"), raw_dir=str(tmp_path / "raw"),
                        baseline_quiet=True)
    oems = {"GMKtec": OemConfig(
        manufacturer=ManufacturerConfig(name="GMKtec", country="CN"),
        sources=[SourceConfig(id="gmktec-shopify", engine="shopify", base_url=BASE,
                              discovery=["products_json"])],
    )}
    store = SqliteStore(radar.db_path, radar.raw_dir)
    store.seed_components(SEED_COMPONENTS)
    notifier = DiscordNotifier(store, "https://hook.example", 3, sender=lambda u, p: (True, None))

    baseline_catalog = copy.deepcopy(FIXTURE)
    baseline_catalog["products"] = baseline_catalog["products"][:2]  # baseline with 2 products
    run_all(radar, oems, store, notifier, RouteFetcher(baseline_catalog), force=True)

    # Third product appears later -- a genuine new_product, not baseline.
    run_all(radar, oems, store, notifier, RouteFetcher(FIXTURE), force=True)

    conn = connect_readonly(str(tmp_path / "r.db"))
    data = collect(conn)
    conn.close()
    new_product_events = [e for e in data["events"] if e["type"] == "new_product"]
    assert len(new_product_events) == 1
    store.close()


def test_genuine_updated_product_remains_visible(baselined_then_changed):
    conn = connect_readonly(str(baselined_then_changed))
    data = collect(conn)
    conn.close()
    prices = [e for e in data["events"] if e["type"] == "price_changed"]
    assert len(prices) == 1


def test_baseline_does_not_enter_unreviewed_count(baselined_then_changed):
    conn = connect_readonly(str(baselined_then_changed))
    data = collect(conn)
    conn.close()
    # Only the 1 real event is unreviewed; the 3 baseline events must not
    # inflate this the way the real Epoch 2 dashboard showed 1,875.
    assert data["summary"]["unreviewed_events"] == 1


def test_baseline_does_not_affect_signal_noise_analytics(baselined_then_changed):
    conn = connect_readonly(str(baselined_then_changed))
    summary = compute_summary(conn)
    conn.close()
    assert summary["total_alerts"] == 1
    assert summary["unreviewed_alerts"] == 1


def test_baseline_never_sends_discord_notifications(tmp_path):
    radar = RadarConfig(db_path=str(tmp_path / "r.db"), raw_dir=str(tmp_path / "raw"),
                        baseline_quiet=True)
    oems = {"GMKtec": OemConfig(
        manufacturer=ManufacturerConfig(name="GMKtec", country="CN"),
        sources=[SourceConfig(id="gmktec-shopify", engine="shopify", base_url=BASE,
                              discovery=["products_json"])],
    )}
    store = SqliteStore(radar.db_path, radar.raw_dir)
    store.seed_components(SEED_COMPONENTS)
    sent = []
    notifier = DiscordNotifier(store, "https://hook.example", 3,
                               sender=lambda u, p: (sent.append(p), None) and (True, None))
    run_all(radar, oems, store, notifier, RouteFetcher(FIXTURE), force=True)
    store.close()
    assert sent == []


def test_baseline_events_excluded_from_change_type_filter_options(baselined_then_changed):
    """The type-filter dropdown must reflect what's actually filterable
    in the default view, not include a type that only ever appeared as
    baseline noise."""
    conn = connect_readonly(str(baselined_then_changed))
    data = collect(conn)
    conn.close()
    assert data["change_types"] == ["price_changed"]


def test_baseline_event_still_individually_reachable_for_diagnostics(baselined_then_changed):
    """A deliberate design choice, not an oversight: unlike evidence
    (structurally a different object), a baseline event is a normal
    ChangeEvent -- /alerts/{id} still resolves it directly if an operator
    navigates to it by id. Only the default list/counts exclude it."""
    from oem_radar.dashboard.data import collect_alert_detail

    conn = connect_readonly(str(baselined_then_changed))
    baseline_ids = [r["id"] for r in collect_baseline_events(conn)]
    assert baseline_ids
    detail = collect_alert_detail(conn, baseline_ids[0])
    conn.close()
    assert detail is not None and detail["id"] == baseline_ids[0]

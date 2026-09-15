"""Notification-policy mute (2026-09-09): availability_changed and
images_changed must never reach Discord.

Operator decision, enforced in config (radar.yaml
notify.discord.suppress_change_types) rather than by lowering severity —
severity stays useful classification data elsewhere. Proven in layers:

  1. severity rules unchanged (both types still score 3);
  2. enqueue suppression BEFORE a row becomes pending (event still
     recorded, still visible in dashboard/All Changes data);
  3. drain-time guard as the last choke point: a stale pending row of a
     muted type can never post, however it got there;
  4. the operational backlog neutralizer (scripts/neutralize_notification_backlog.py)
     converts existing pending rows without deleting history.

There is no digest implementation in this repository (digest_below is a
config field with no consumer), so enqueue+drain suppression covers every
path that could ever deliver; the tests below assert no muted payload is
ever rendered into a pending or sent row.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from oem_radar.core.config import ConfigError, RadarConfig, load_radar_config
from oem_radar.core.crawl_service import build_store_and_notifier
from oem_radar.core.diff import score
from oem_radar.core.models import (
    ChangeEvent,
    ChangeType,
    Severity,
)
from oem_radar.dashboard.data import collect
from oem_radar.providers.discord import DiscordNotifier
from oem_radar.providers.sqlite import SqliteStore
from test_models import make_product

REPO = Path(__file__).parent.parent
SHIPPED = load_radar_config(REPO / "config" / "radar.yaml")
MUTED = ("availability_changed", "images_changed")


def ev(change_type: ChangeType, sev: Severity = Severity.NOTABLE, **kw) -> ChangeEvent:
    return ChangeEvent(product_key="s:p", change_type=change_type,
                       severity=sev, **kw)


@pytest.fixture()
def store(tmp_path):
    s = SqliteStore(str(tmp_path / "r.db"), str(tmp_path / "raw"))
    yield s
    s.close()


def muted_notifier(store, **kw) -> DiscordNotifier:
    return DiscordNotifier(
        store, "https://hook.example", min_severity=3,
        sender=lambda u, p: (True, None),
        suppress_change_types=MUTED, **kw,
    )


# -- 1. severity classification unchanged -------------------------------------

def test_muted_types_keep_severity_3():
    assert score(ev(ChangeType.AVAILABILITY_CHANGED), SHIPPED.severity_rules) == Severity.NOTABLE
    assert score(ev(ChangeType.IMAGES_CHANGED), SHIPPED.severity_rules) == Severity.NOTABLE
    assert SHIPPED.notify["discord"].min_severity == 3


def test_other_severity_behaviour_unchanged():
    rules = SHIPPED.severity_rules
    assert score(ev(ChangeType.NEW_PRODUCT), rules) == Severity.BREAKING
    assert score(ev(ChangeType.COMPONENT_CHANGED, meta={"unseen_component": True}),
                 rules) == Severity.BREAKING
    assert score(ev(ChangeType.SPEC_CHANGED, field="memory", meta={"direction": "up"}),
                 rules) == Severity.SIGNIFICANT
    assert score(ev(ChangeType.PRICE_CHANGED, meta={"magnitude_pct": 20.0}),
                 rules) == Severity.NOTABLE
    assert score(ev(ChangeType.PRICE_CHANGED, meta={"magnitude_pct": 5.0}),
                 rules) == Severity.NOISE


# -- 2. enqueue suppression: recorded, visible, never pending ------------------

@pytest.mark.parametrize("change_type", [ChangeType.AVAILABILITY_CHANGED,
                                         ChangeType.IMAGES_CHANGED])
def test_muted_event_persisted_but_never_pending(store, tmp_path, change_type):
    notifier = muted_notifier(store)
    notifier.enqueue(ev(change_type), make_product())

    assert store.outbox_pending("discord") == []  # never PENDING
    suppressed = store.db.execute(
        "SELECT COUNT(*) c FROM notifications WHERE status='suppressed'"
    ).fetchone()["c"]
    assert suppressed == 1  # the outbox row exists, born suppressed
    persisted = store.db.execute(
        "SELECT change_type FROM change_events"
    ).fetchall()
    assert [r["change_type"] for r in persisted] == [change_type.value]

    # Dashboard / All Changes data still shows it (only baselines are
    # excluded there); delivery_state honestly reads "suppressed".
    conn = sqlite3.connect(str(tmp_path / "r.db"))
    conn.row_factory = sqlite3.Row
    try:
        view = collect(conn)
    finally:
        conn.close()
    entry = next(e for e in view["events"] if e["product_key"] == "s:p")
    assert entry["delivery_state"] == "suppressed"


def test_even_high_severity_muted_event_never_becomes_pending(store):
    """The mute is not subject to min_severity: a severity-5 availability
    change must still never enqueue pending."""
    notifier = muted_notifier(store)
    notifier.enqueue(ev(ChangeType.AVAILABILITY_CHANGED, Severity.BREAKING))
    assert store.outbox_pending("discord") == []


# -- 3. everything else still notifies -----------------------------------------

@pytest.mark.parametrize("event", [
    ev(ChangeType.NEW_PRODUCT, Severity.BREAKING),
    ev(ChangeType.COMPONENT_CHANGED, Severity.BREAKING, meta={"unseen_component": True}),
    ev(ChangeType.SPEC_CHANGED, Severity.SIGNIFICANT, field="memory",
       meta={"direction": "up"}),
    ev(ChangeType.PRICE_CHANGED, Severity.NOTABLE, meta={"magnitude_pct": 20.0}),
], ids=["new_product", "component_unseen", "spec_memory_up", "price_over_15"])
def test_qualifying_non_muted_events_still_pending(store, event):
    muted_notifier(store).enqueue(event, make_product())
    pending = store.outbox_pending("discord")
    assert len(pending) == 1 and pending[0]["change_type"] == event.change_type.value


def test_baseline_suppression_still_wins(store):
    notifier = muted_notifier(store)
    notifier.enqueue(ev(ChangeType.NEW_PRODUCT, Severity.BREAKING, meta={"baseline": True}))
    assert store.outbox_pending("discord") == []
    # A baseline muted event is suppressed by the baseline branch (first
    # match) — same terminal state either way, event still recorded.
    notifier.enqueue(ev(ChangeType.IMAGES_CHANGED, meta={"baseline": True}))
    assert store.db.execute(
        "SELECT COUNT(*) c FROM notifications WHERE status='suppressed'"
    ).fetchone()["c"] == 2


# -- 4. config surface ----------------------------------------------------------

def _write_radar(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "radar.yaml"
    path.write_text(body, encoding="utf-8")
    return path


MINIMAL = (
    "severity_rules: [{match: {}, severity: 2}]\n"
    "notify:\n  discord:\n    min_severity: 3\n"
)


def test_invalid_suppress_change_type_fails_validation(tmp_path):
    path = _write_radar(
        tmp_path, MINIMAL + "    suppress_change_types: [availabilty_changed]\n")  # typo
    with pytest.raises(ConfigError) as ei:
        load_radar_config(path)
    assert "suppress_change_types" in str(ei.value)


def test_valid_suppress_change_types_load(tmp_path):
    path = _write_radar(
        tmp_path, MINIMAL + "    suppress_change_types: [availability_changed, images_changed]\n")
    cfg = load_radar_config(path)
    assert cfg.notify["discord"].suppress_change_types == list(MUTED)


def test_omitting_the_key_preserves_legacy_behaviour(tmp_path):
    path = _write_radar(tmp_path, MINIMAL)
    cfg = load_radar_config(path)
    assert cfg.notify["discord"].suppress_change_types == []
    # Legacy semantics: a severity-3 availability event pends when unlisted.
    store = SqliteStore(str(tmp_path / "r.db"), str(tmp_path / "raw"))
    try:
        DiscordNotifier(store, "https://hook.example", min_severity=3,
                        sender=lambda u, p: (True, None)).enqueue(
            ev(ChangeType.AVAILABILITY_CHANGED))
        assert len(store.outbox_pending("discord")) == 1
    finally:
        store.close()


def test_config_flows_to_the_single_notifier_assembly_point(tmp_path):
    """Every execution surface (scheduled CLI run, manual run, dashboard
    crawl) builds its notifier through build_store_and_notifier — prove the
    configured suppression set arrives there."""
    (tmp_path / "oems").mkdir()
    (tmp_path / "raw").mkdir()
    path = _write_radar(tmp_path, (
        "severity_rules: [{match: {}, severity: 2}]\n"
        f"db_path: {json.dumps(str(tmp_path / 'r.db'))}\n"
        f"raw_dir: {json.dumps(str(tmp_path / 'raw'))}\n"
        "notify:\n  discord:\n    min_severity: 3\n"
        "    suppress_change_types: [availability_changed, images_changed]\n"
    ))
    radar = load_radar_config(path)
    store, notifier, wh_src, present = build_store_and_notifier(radar, tmp_path)
    try:
        assert isinstance(notifier, DiscordNotifier)
        assert notifier.suppress_change_types == frozenset(MUTED)
    finally:
        store.close()


# -- 5. drain guard: stale pending muted rows can never post --------------------

def test_drain_neutralizes_stale_pending_muted_rows_without_sending(store):
    # Simulate the pre-policy backlog: a muted-type row already pending.
    legacy = DiscordNotifier(store, "https://hook.example", min_severity=3,
                             sender=lambda u, p: (True, None))
    legacy.enqueue(ev(ChangeType.AVAILABILITY_CHANGED, Severity.NOTABLE,
                      old_value="in_stock", new_value="sold_out"))
    legacy.enqueue(ev(ChangeType.IMAGES_CHANGED))
    legacy.enqueue(ev(ChangeType.NEW_PRODUCT, Severity.BREAKING))  # must still send

    sent_payloads = []
    policy = DiscordNotifier(
        store, "https://hook.example", min_severity=3,
        sender=lambda u, p: (sent_payloads.append(p), None) and (True, None),
        suppress_change_types=MUTED,
    )
    sent = policy.drain()
    # Only the new_product row posted; both muted rows were neutralized.
    assert sent == 1 and len(sent_payloads) == 1
    assert "NEW PRODUCT" in sent_payloads[0]["embeds"][0]["title"]
    rows = store.db.execute(
        "SELECT n.status, n.last_error, e.change_type AS t FROM notifications n "
        "JOIN change_events e ON e.id = n.change_event_id"
    ).fetchall()
    by_type = {r["t"]: (r["status"], r["last_error"]) for r in rows}
    assert by_type["availability_changed"] == ("suppressed", "change_type_suppressed")
    assert by_type["images_changed"] == ("suppressed", "change_type_suppressed")
    assert by_type["new_product"][0] == "sent"


# -- 6. backlog neutralizer: history preserved, idempotent ----------------------

def test_backlog_neutralizer_converts_only_pending_muted_rows(tmp_path):
    db_path = str(tmp_path / "r.db")
    store = SqliteStore(db_path, str(tmp_path / "raw"))
    try:
        legacy = DiscordNotifier(store, "https://hook.example", min_severity=3,
                                 sender=lambda u, p: (True, None))
        legacy.enqueue(ev(ChangeType.AVAILABILITY_CHANGED))            # pending muted
        legacy.enqueue(ev(ChangeType.IMAGES_CHANGED))                  # pending muted
        legacy.enqueue(ev(ChangeType.NEW_PRODUCT, Severity.BREAKING))  # pending other
        other_id = store.outbox_pending("discord")[2]["id"]
        store.outbox_mark(other_id, "sent")                            # sent history
        legacy.enqueue(ev(ChangeType.PRICE_CHANGED, Severity.NOTABLE,
                          meta={"magnitude_pct": 50.0}))
        failed_id = store.outbox_pending("discord")[-1]["id"]
        for _ in range(5):
            store.outbox_mark(failed_id, "pending", "HTTP 500")
        store.outbox_mark(failed_id, "failed", "HTTP 500")             # failed history
    finally:
        store.close()

    script = REPO / "scripts" / "neutralize_notification_backlog.py"
    result = subprocess.run(
        [sys.executable, str(script), "--db", db_path,
         "--types", "availability_changed,images_changed"],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr

    check = sqlite3.connect(db_path)
    check.row_factory = sqlite3.Row
    rows = {
        r["change_type"]: r
        for r in check.execute(
            "SELECT e.change_type AS change_type, n.status AS status, n.last_error AS err "
            "FROM notifications n JOIN change_events e ON e.id = n.change_event_id")
    }
    # Pending muted rows: converted, reason persisted, event history intact.
    assert rows["availability_changed"]["status"] == "suppressed"
    assert rows["availability_changed"]["err"] == "change_type_suppressed"
    assert rows["images_changed"]["status"] == "suppressed"
    # History untouched: sent stays sent, failed stays failed.
    assert rows["new_product"]["status"] == "sent"
    assert rows["price_changed"]["status"] == "failed"
    # No change_events were deleted.
    assert check.execute("SELECT COUNT(*) FROM change_events").fetchone()[0] == 4
    check.close()

    # Idempotent: a second run changes nothing.
    again = subprocess.run(
        [sys.executable, str(script), "--db", db_path,
         "--types", "availability_changed,images_changed"],
        capture_output=True, text=True, timeout=60,
    )
    assert again.returncode == 0
    assert "pending muted rows to neutralize: 0" in again.stdout


# -- 7. runtime identity diagnostics (2026-09-10 split-brain incident) ---------

def test_drain_logs_structured_runtime_identity(store, caplog, monkeypatch):
    """The muted-alert incident happened because 'the checkout' was assumed
    to be 'the sender'. Every drain must log which runtime is speaking —
    git sha, db path, hostname, surface, config path, webhook presence —
    and must NEVER log the webhook URL itself."""
    import logging as _logging
    monkeypatch.setenv("OEM_RADAR_GIT_SHA", "deadbeeftest")
    notifier = DiscordNotifier(
        store, "https://hook.example/never-log-me", min_severity=3,
        sender=lambda u, p: (True, None),
        suppress_change_types=MUTED, surface="test",
        config_path="C:/somewhere/config/radar.yaml",
    )
    with caplog.at_level(_logging.INFO, logger="oem_radar.discord"):
        notifier.drain()
    line = next(r.message for r in caplog.records if r.message.startswith("discord_runtime"))
    assert "git_sha=deadbeeftest" in line
    assert "hostname=" in line
    assert "surface=test" in line
    assert "config=C:/somewhere/config/radar.yaml" in line
    assert "webhook_configured=True" in line
    # db path is the store's real file, via PRAGMA database_list
    assert "db=" in line and ":memory:" not in line
    assert "never-log-me" not in line  # the URL must never appear


def test_resolve_git_sha_env_override_and_fallback(monkeypatch):
    from oem_radar.providers.discord import resolve_git_sha
    monkeypatch.setenv("OEM_RADAR_GIT_SHA", "  cafef00d  ")
    assert resolve_git_sha() == "cafef00d"
    monkeypatch.delenv("OEM_RADAR_GIT_SHA")
    # In the source checkout the fallback resolves the repo's real HEAD.
    sha = resolve_git_sha()
    assert sha == "unknown" or (len(sha) == 40 and all(c in "0123456789abcdef" for c in sha))


def test_assembly_point_passes_surface_and_config_path(tmp_path):
    (tmp_path / "oems").mkdir()
    (tmp_path / "raw").mkdir()
    path = _write_radar(tmp_path, MINIMAL)
    radar = load_radar_config(path)
    store, notifier, _src, _present = build_store_and_notifier(
        radar, tmp_path, surface="dashboard")
    try:
        assert notifier.surface == "dashboard"
        assert notifier.config_path.endswith("radar.yaml")
    finally:
        store.close()

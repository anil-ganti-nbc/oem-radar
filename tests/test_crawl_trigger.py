"""Stage 11.2: triggering a collector run from the dashboard.

Two things are being pinned here. The obvious one is that the button and
the auto-trigger work. The less obvious one is that they work by calling
the *same* crawl the CLI calls — Stage 11.1's lesson was that a second
caller becomes a second implementation unless a test says otherwise.
"""

from __future__ import annotations

import json
import threading
import time
from http.client import HTTPConnection
from pathlib import Path

import pytest

from oem_radar.core import crawl_service
from oem_radar.core.config import (
    DashboardConfig,
    ManufacturerConfig,
    OemConfig,
    RadarConfig,
    SourceConfig,
    load_radar_config,
)
from oem_radar.core.crawl_service import CrawlController
from oem_radar.core.knownhw import SEED_COMPONENTS
from oem_radar.core.run_lock import LockError
from oem_radar.core.runner import run_all
from oem_radar.engines import shopify  # noqa: F401 (registers engine)
from oem_radar.providers.discord import DiscordNotifier
from oem_radar.providers.sqlite import SqliteStore
from test_runner import BASE, FIXTURE, RouteFetcher


# ---------------------------------------------------------------------------
# run_all progress reporting
# ---------------------------------------------------------------------------

@pytest.fixture()
def env(tmp_path):
    radar = RadarConfig(db_path=str(tmp_path / "radar.db"), raw_dir=str(tmp_path / "raw"))
    oems = {"GMKtec": OemConfig(
        manufacturer=ManufacturerConfig(name="GMKtec", country="CN"),
        sources=[SourceConfig(id="gmktec-shopify", engine="shopify", base_url=BASE,
                              min_interval="6h", discovery=["products_json"])],
    )}
    store = SqliteStore(radar.db_path, radar.raw_dir)
    store.seed_components(SEED_COMPONENTS)
    notifier = DiscordNotifier(store, "https://hook.example", 3,
                               sender=lambda u, p: (True, None))
    yield radar, oems, store, notifier
    store.close()


def test_run_all_emits_progress_in_order(env):
    radar, oems, store, notifier = env
    seen = []
    run_all(radar, oems, store, notifier, RouteFetcher(FIXTURE), force=True,
            on_progress=seen.append)
    kinds = [e["event"] for e in seen]
    assert kinds[0] == "planned" and kinds[-1] == "finished"
    assert kinds.index("source_start") < kinds.index("source_done")
    assert seen[0]["sources_total"] == 1
    done = next(e for e in seen if e["event"] == "source_done")
    assert done["source"] == "gmktec-shopify"
    assert done["status"] == "ok" and done["snapshots"] == 3


def test_progress_reports_skipped_sources_not_just_crawled_ones(env):
    """A crawl where everything is within min_interval must still say so.

    This is the case that made the dashboard look broken: nothing happens,
    and without an event the UI cannot tell 'up to date' from 'hung'."""
    radar, oems, store, notifier = env
    run_all(radar, oems, store, notifier, RouteFetcher(FIXTURE), force=True)
    seen = []
    run_all(radar, oems, store, notifier, RouteFetcher(FIXTURE), on_progress=seen.append)
    assert [e["event"] for e in seen] == ["planned", "source_skipped", "finished"]
    assert seen[1]["status"] == "skipped"


def test_a_broken_progress_observer_cannot_abort_a_crawl(env):
    radar, oems, store, notifier = env

    def boom(_ev):
        raise RuntimeError("observer is broken")

    stats = run_all(radar, oems, store, notifier, RouteFetcher(FIXTURE),
                    force=True, on_progress=boom)
    assert len(stats) == 1 and stats[0].snapshots_written == 3


def test_planned_total_respects_only_source_and_disabled(tmp_path):
    radar = RadarConfig(db_path=str(tmp_path / "r.db"), raw_dir=str(tmp_path / "raw"))
    oems = {"GMKtec": OemConfig(
        manufacturer=ManufacturerConfig(name="GMKtec", country="CN"),
        sources=[
            SourceConfig(id="a", engine="shopify", base_url=BASE, discovery=["products_json"]),
            SourceConfig(id="b", engine="shopify", base_url=BASE, discovery=["products_json"],
                         enabled=False),
        ],
    )}
    store = SqliteStore(radar.db_path, radar.raw_dir)
    try:
        seen = []
        run_all(radar, oems, store, DiscordNotifier(store, None, 3),
                RouteFetcher(FIXTURE), only_source="a", force=True,
                on_progress=seen.append)
        assert seen[0]["sources_total"] == 1  # disabled 'b' is not counted
    finally:
        store.close()


# ---------------------------------------------------------------------------
# CrawlController
# ---------------------------------------------------------------------------

class FakeOutcome:
    def __init__(self, **kw):
        self.d = {"sources": 1, "snapshots": 2, "events": 3, "errors": 0,
                  "duration_s": 0.1} | kw

    def as_dict(self):
        return dict(self.d)


def test_controller_starts_idle(tmp_path):
    c = CrawlController(tmp_path, runner=lambda *a, **k: FakeOutcome())
    st = c.status()
    assert st["status"] == "idle" and st["running"] is False
    assert st["sources_done"] == 0 and st["outcome"] is None


def test_controller_runs_and_reports_outcome(tmp_path):
    calls = {}

    def runner(config_dir, *, force, only_source, on_progress):
        calls.update(config_dir=config_dir, force=force, only_source=only_source)
        on_progress({"event": "planned", "sources_total": 4})
        on_progress({"event": "source_start", "source": "medion"})
        on_progress({"event": "source_done", "source": "medion", "status": "ok",
                     "events": 1, "snapshots": 2, "errors": 0})
        return FakeOutcome()

    c = CrawlController(tmp_path, runner=runner)
    accepted, reason, _ = c.trigger(force=True, only_source="medion")
    assert accepted and reason == "started"
    c.join(5)
    st = c.status()
    assert st["status"] == "ok" and st["running"] is False
    assert st["outcome"]["events"] == 3
    assert st["sources_total"] == 4 and st["sources_done"] == 1
    assert st["sources"][0]["source"] == "medion"
    assert st["current_source"] is None
    assert calls["force"] is True and calls["only_source"] == "medion"
    assert Path(calls["config_dir"]) == Path(tmp_path)


def test_controller_is_single_flight(tmp_path):
    release = threading.Event()

    def runner(config_dir, *, force, only_source, on_progress):
        release.wait(5)
        return FakeOutcome()

    c = CrawlController(tmp_path, runner=runner)
    assert c.trigger()[0] is True
    for _ in range(200):           # wait for the worker to actually be RUNNING
        if c.running:
            break
        time.sleep(0.01)
    accepted, reason, state = c.trigger()
    assert accepted is False and reason == "already_running"
    assert state["running"] is True
    release.set()
    c.join(5)
    assert c.status()["status"] == "ok"


def test_controller_reports_lock_held_as_blocked_not_failed(tmp_path):
    """Another crawl holding the lock is the system working, not an error.

    The scheduled hourly task and the dashboard share one lock; a user who
    opens the dashboard mid-crawl should be told that, not shown a failure.
    """
    def runner(config_dir, *, force, only_source, on_progress):
        raise LockError("another oem-radar run is active (pid=4242)")

    c = CrawlController(tmp_path, runner=runner)
    c.trigger()
    c.join(5)
    st = c.status()
    assert st["status"] == "blocked"
    assert "pid=4242" in st["message"]


def test_controller_survives_a_crawl_that_raises(tmp_path):
    def runner(config_dir, *, force, only_source, on_progress):
        raise ValueError("network exploded")

    c = CrawlController(tmp_path, runner=runner)
    c.trigger()
    c.join(5)
    st = c.status()
    assert st["status"] == "failed"
    assert "ValueError" in st["message"] and "network exploded" in st["message"]
    # and the controller is reusable afterwards
    assert c.trigger()[0] is True


def test_allow_manual_false_blocks_the_button_but_not_the_auto_trigger(tmp_path):
    c = CrawlController(tmp_path, runner=lambda *a, **k: FakeOutcome(),
                        allow_manual=False)
    accepted, reason, st = c.trigger(trigger="manual")
    assert accepted is False and reason == "manual_crawl_disabled"
    assert st["allow_manual"] is False
    accepted, _, _ = c.trigger(trigger="auto")
    assert accepted is True
    c.join(5)


# ---------------------------------------------------------------------------
# one code path, not two
# ---------------------------------------------------------------------------

def test_cli_and_dashboard_share_the_run_assembly():
    """The CLI's helpers must literally be the crawl_service ones.

    Stage 11.1 shipped three regressions traceable to the same shape of
    mistake — a second consumer growing its own near-copy. If someone
    re-inlines `_build_fetcher` into cli.py, this fails.
    """
    from oem_radar import cli

    assert cli._build_fetcher is crawl_service.build_fetcher
    assert cli._resolve_webhook is crawl_service.resolve_webhook


def test_execute_crawl_registers_engines_without_the_cli():
    """The .exe never imports cli.py, so a crawl triggered from the
    browser must register the engines itself or fail on the first source."""
    from oem_radar.core.registry import engines, notifiers, stores

    crawl_service._ensure_registries()
    for name in ("shopify", "dell", "sitemap_jsonld", "woocommerce_store_api",
                 "category_jsonld"):
        assert name in engines.names()
    assert stores.get("sqlite") is not None
    assert notifiers.get("discord") is not None


def test_execute_crawl_is_what_cmd_run_calls():
    import inspect

    from oem_radar import cli

    assert "execute_crawl" in inspect.getsource(cli.cmd_run)
    assert "run_all" not in inspect.getsource(cli.cmd_run)


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------

def test_dashboard_config_defaults_fail_closed():
    # Fleet Law 5 (Phase 2C): dashboards must not become collection/notification
    # actors implicitly. Default is fail-closed; opting in is explicit.
    d = DashboardConfig()
    assert d.auto_crawl_on_start is False
    assert d.allow_manual_crawl is True
    # Forcing on every launch would re-crawl every catalog on every open.
    assert d.auto_crawl_force is False


def test_shipped_radar_yaml_has_a_dashboard_section():
    cfg = load_radar_config(Path("config/radar.yaml"))
    assert cfg.dashboard.auto_crawl_on_start is False
    assert cfg.dashboard.stale_after_hours > 0


def test_no_crawl_flag_overrides_config(tmp_path):
    import argparse

    from oem_radar.cli import build_dashboard_crawl_kwargs

    radar = RadarConfig(dashboard=DashboardConfig(auto_crawl_on_start=True))
    args = argparse.Namespace(no_crawl=True)
    kw = build_dashboard_crawl_kwargs(radar, tmp_path, args)
    assert kw["crawl"] is None and kw["auto_crawl"] is False

    kw2 = build_dashboard_crawl_kwargs(radar, tmp_path, argparse.Namespace(no_crawl=False))
    assert kw2["crawl"] is None and kw2["auto_crawl"] is False


# ---------------------------------------------------------------------------
# serve() wiring
# ---------------------------------------------------------------------------

class RecordingController:
    def __init__(self, allow_manual=True, running=False):
        self.calls = []
        self.allow_manual = allow_manual
        self._running = running

    @property
    def running(self):
        return self._running

    def trigger(self, *, force=False, only_source=None, trigger="manual"):
        self.calls.append({"force": force, "source": only_source, "trigger": trigger})
        if self._running:
            return False, "already_running", self.status()
        return True, "started", self.status()

    def status(self):
        return {"status": "running" if self._running else "idle",
                "running": self._running, "allow_manual": self.allow_manual,
                "sources_done": 0, "sources_total": 0, "sources": [],
                "outcome": None, "message": None, "trigger": None,
                "started_at": None, "finished_at": None, "current_source": None,
                "force": False}


@pytest.fixture()
def fake_httpd(monkeypatch):
    from oem_radar import dashboard as dash

    class FakeHttpd:
        def __init__(self, addr, handler):
            pass

        def serve_forever(self):
            pass

        def server_close(self):
            pass

    monkeypatch.setattr(dash, "ThreadingHTTPServer", FakeHttpd)
    yield


def test_serve_rejects_auto_crawl_on_start(fake_httpd, tmp_path):
    from oem_radar.dashboard import serve

    ctl = RecordingController()
    # Auto-crawl is refused unconditionally and cannot be opted into, even
    # alongside the manual-collection opt-in: opening the GUI must never
    # start a crawl.
    with pytest.raises(ValueError, match="auto-crawl is not permitted"):
        serve(str(tmp_path / "x.db"), open_browser=False, crawl=ctl, auto_crawl=True)
    with pytest.raises(ValueError, match="auto-crawl is not permitted"):
        serve(str(tmp_path / "x.db"), open_browser=False, crawl=ctl,
              auto_crawl=True, allow_manual_collection=True)
    assert ctl.calls == []


def test_serve_rejects_crawl_controller_even_without_force(fake_httpd, tmp_path):
    """Auto-crawl on every launch is only safe because it respects
    min_interval. If it ever forces, opening the dashboard five times
    re-crawls every catalog five times."""
    from oem_radar.dashboard import serve

    ctl = RecordingController()
    # Auto-crawl is refused unconditionally and cannot be opted into, even
    # alongside the manual-collection opt-in: opening the GUI must never
    # start a crawl.
    with pytest.raises(ValueError, match="auto-crawl is not permitted"):
        serve(str(tmp_path / "x.db"), open_browser=False, crawl=ctl, auto_crawl=True)
    with pytest.raises(ValueError, match="auto-crawl is not permitted"):
        serve(str(tmp_path / "x.db"), open_browser=False, crawl=ctl,
              auto_crawl=True, allow_manual_collection=True)
    assert ctl.calls == []


def test_serve_rejects_manual_crawl_controller(fake_httpd, tmp_path):
    from oem_radar.dashboard import serve

    ctl = RecordingController()
    with pytest.raises(ValueError, match="read-only"):
        serve(str(tmp_path / "x.db"), open_browser=False, crawl=ctl, auto_crawl=False)
    assert ctl.calls == []


def test_serve_read_only_needs_no_controller(fake_httpd, tmp_path):
    from oem_radar.dashboard import serve

    serve(str(tmp_path / "x.db"), open_browser=False, crawl=None, auto_crawl=False)


# ---------------------------------------------------------------------------
# HTTP API
# ---------------------------------------------------------------------------

@pytest.fixture()
def server(tmp_path, request):
    import socket
    from http.server import ThreadingHTTPServer

    from oem_radar.dashboard import _CSRF_TOKEN, _Handler

    db = str(tmp_path / "srv.db")
    raw = str(tmp_path / "raw")
    SqliteStore(db, raw).close()

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    ctl = getattr(request, "param", None)
    _Handler.db_path = db
    _Handler.raw_dir = raw
    _Handler.max_body = 16384
    _Handler.csrf_token = _CSRF_TOKEN
    _Handler.crawl = ctl
    _Handler.mutation_authorizer = lambda _headers: True
    _Handler.stale_after_hours = 6.0
    httpd = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield {"port": port, "csrf": _CSRF_TOKEN, "crawl": ctl}
    httpd.shutdown()
    _Handler.crawl = None  # class attribute: never leak into another test
    _Handler.mutation_authorizer = None


def _req(port, method, path, body=None, headers=None):
    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    hdrs = dict(headers or {})
    payload = None
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
        hdrs["Content-Length"] = str(len(payload))
    conn.request(method, path, body=payload, headers=hdrs)
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    try:
        return resp.status, json.loads(data.decode("utf-8"))
    except Exception:
        return resp.status, data.decode("utf-8", errors="replace")


def test_status_reports_disabled_when_read_only(server):
    status, data = _req(server["port"], "GET", "/api/crawl/status")
    assert status == 200
    assert data["enabled"] is False and data["running"] is False


def test_post_crawl_is_503_when_read_only(server):
    status, data = _req(server["port"], "POST", "/api/crawl",
                        body={"csrf_token": server["csrf"]})
    assert status == 503 and data["error"]["code"] == "crawl_disabled"


@pytest.mark.parametrize("server", [RecordingController()], indirect=True)
def test_post_crawl_requires_csrf(server):
    status, data = _req(server["port"], "POST", "/api/crawl", body={"force": False})
    assert status == 403 and data["error"]["code"] == "csrf_invalid"
    assert server["crawl"].calls == []


@pytest.mark.parametrize("server", [RecordingController()], indirect=True)
def test_post_crawl_rejects_a_wrong_csrf_token(server):
    status, _ = _req(server["port"], "POST", "/api/crawl",
                     body={"csrf_token": "not-the-token"})
    assert status == 403
    assert server["crawl"].calls == []


@pytest.mark.parametrize("server", [RecordingController()], indirect=True)
def test_post_crawl_starts_a_run(server):
    status, data = _req(
        server["port"], "POST", "/api/crawl", body={"force": False},
        headers={"X-OEM-Radar-CSRF": server["csrf"]})
    assert status == 202 and data["ok"] is True
    assert data["state"]["enabled"] is True
    assert server["crawl"].calls == [
        {"force": False, "source": None, "trigger": "manual"}]


@pytest.mark.parametrize("server", [RecordingController()], indirect=True)
def test_post_crawl_passes_force_through(server):
    _req(server["port"], "POST", "/api/crawl", body={"force": True},
         headers={"X-OEM-Radar-CSRF": server["csrf"]})
    assert server["crawl"].calls[0]["force"] is True


@pytest.mark.parametrize("server", [RecordingController(running=True)], indirect=True)
def test_post_crawl_is_409_while_one_is_running(server):
    status, data = _req(server["port"], "POST", "/api/crawl", body={},
                        headers={"X-OEM-Radar-CSRF": server["csrf"]})
    assert status == 409 and data["error"]["code"] == "already_running"


@pytest.mark.parametrize("server", [RecordingController(allow_manual=False)],
                         indirect=True)
def test_status_exposes_manual_disabled(server):
    status, data = _req(server["port"], "GET", "/api/crawl/status")
    assert status == 200 and data["enabled"] is True
    assert data["allow_manual"] is False


@pytest.mark.parametrize("server", [RecordingController()], indirect=True)
def test_post_crawl_rejects_unknown_fields_and_bad_types(server):
    status, data = _req(server["port"], "POST", "/api/crawl",
                        body={"force": False, "wat": 1},
                        headers={"X-OEM-Radar-CSRF": server["csrf"]})
    assert status == 400 and data["error"]["code"] == "unknown_fields"

    status, data = _req(server["port"], "POST", "/api/crawl", body={"force": "yes"},
                        headers={"X-OEM-Radar-CSRF": server["csrf"]})
    assert status == 400 and data["error"]["code"] == "invalid_force"
    assert server["crawl"].calls == []


@pytest.mark.parametrize("server", [RecordingController()], indirect=True)
def test_crawl_endpoint_rejects_get_and_put(server):
    assert _req(server["port"], "GET", "/api/crawl")[0] == 404
    assert _req(server["port"], "PUT", "/api/crawl")[0] == 405


# ---------------------------------------------------------------------------
# page
# ---------------------------------------------------------------------------

def _page(tmp_path, csrf="tok-123"):
    from oem_radar.dashboard.data import collect
    from oem_radar.dashboard.render import render
    from oem_radar.providers.sqlite import connect_readonly

    db = str(tmp_path / "p.db")
    SqliteStore(db, str(tmp_path / "raw")).close()
    conn = connect_readonly(db)
    try:
        return render(collect(conn), csrf_token=csrf)
    finally:
        conn.close()


def test_page_has_a_crawl_bar_and_a_manual_trigger(tmp_path):
    html = _page(tmp_path)
    assert 'id="crawlbar"' in html
    assert "startCrawl(false)" in html and "startCrawl(true)" in html
    assert "/api/crawl/status" in html and "'/api/crawl'" in html


def test_page_embeds_the_csrf_token_for_the_trigger(tmp_path):
    html = _page(tmp_path, csrf="tok-123")
    assert '"tok-123"' in html
    assert "__CSRF__" not in html  # placeholder must always be substituted


def test_page_renders_without_a_token_when_none_is_supplied(tmp_path):
    from oem_radar.dashboard.data import collect
    from oem_radar.dashboard.render import render
    from oem_radar.providers.sqlite import connect_readonly

    db = str(tmp_path / "q.db")
    SqliteStore(db, str(tmp_path / "raw")).close()
    conn = connect_readonly(db)
    try:
        html = render(collect(conn))
    finally:
        conn.close()
    assert "__CSRF__" not in html


def test_reload_keeps_the_tab_you_were_reading(tmp_path):
    """'Reload does nothing' was half a data problem and half this: a
    reload dropped you back on Stories, so nothing looked like it moved."""
    html = _page(tmp_path)
    assert "history.replaceState" in html
    assert "searchParams.set('tab', name)" in html


def test_crawl_bar_polls_the_server_rather_than_guessing(tmp_path):
    """Crawl state is the server's, like the OEM registry. The page must
    never infer 'is a crawl running' from what it happens to be showing."""
    html = _page(tmp_path)
    assert "function crawlPoll()" in html
    assert "setInterval(crawlPoll" in html


# ---------------------------------------------------------------------------
# Stage 11.3: the manual-collection opt-in is actually wired end to end.
#
# The button, the endpoint and the controller all existed and were all
# tested before this — and manual collection still did not work, because
# three authority gates upstream of them were hardcoded shut:
# build_dashboard_crawl_kwargs always returned crawl=None, serve() raised on
# any controller, and the launcher passed no controller. Endpoint-level tests
# could not see that. These tests pin the wiring itself.
# ---------------------------------------------------------------------------


def test_build_crawl_kwargs_opts_out_by_default(tmp_path):
    """A: default remains read-only — no controller, no auto-crawl."""
    from argparse import Namespace

    from oem_radar.cli import build_dashboard_crawl_kwargs

    from oem_radar.core.config import load_radar_config

    radar = load_radar_config(Path("config/radar.yaml"))
    kwargs = build_dashboard_crawl_kwargs(radar, Path("config"), Namespace())
    assert kwargs["crawl"] is None
    assert kwargs["auto_crawl"] is False
    assert kwargs["allow_manual_collection"] is False


def test_build_crawl_kwargs_builds_canonical_controller_when_opted_in():
    """B + I: opting in yields the canonical CrawlController, bound to the
    same config directory the scheduler resolves its source registry from."""
    from argparse import Namespace

    from oem_radar.cli import build_dashboard_crawl_kwargs
    from oem_radar.core.config import load_radar_config
    from oem_radar.core.crawl_service import CrawlController, execute_crawl

    radar = load_radar_config(Path("config/radar.yaml"))
    kwargs = build_dashboard_crawl_kwargs(
        radar, Path("config"), Namespace(allow_manual_collection=True, no_crawl=False),
    )
    ctl = kwargs["crawl"]
    assert isinstance(ctl, CrawlController)
    assert ctl.allow_manual is True
    # Same execution service the scheduled `oem-radar run` path uses: no
    # second collector implementation behind the GUI.
    assert ctl._runner is execute_crawl
    assert Path(ctl.config_dir) == Path("config")
    # Auto-crawl is never enabled by opting into manual collection.
    assert kwargs["auto_crawl"] is False
    assert kwargs["allow_manual_collection"] is True


def test_no_crawl_flag_still_overrides_the_manual_opt_in():
    """--no-crawl remains the operator's off switch."""
    from argparse import Namespace

    from oem_radar.cli import build_dashboard_crawl_kwargs
    from oem_radar.core.config import load_radar_config

    radar = load_radar_config(Path("config/radar.yaml"))
    kwargs = build_dashboard_crawl_kwargs(
        radar, Path("config"), Namespace(allow_manual_collection=True, no_crawl=True),
    )
    assert kwargs["crawl"] is None
    assert kwargs["allow_manual_collection"] is False


def test_serve_accepts_a_controller_only_with_the_explicit_opt_in(fake_httpd, tmp_path):
    """B: the gate that blocked every previous fix attempt."""
    from oem_radar.dashboard import _Handler, serve

    ctl = RecordingController()
    # Without the opt-in: still refused (historical contract preserved).
    with pytest.raises(ValueError, match="allow_manual_collection"):
        serve(str(tmp_path / "x.db"), open_browser=False, crawl=ctl)
    # With it: accepted, and the handler actually receives the controller.
    serve(str(tmp_path / "x.db"), open_browser=False, crawl=ctl,
          allow_manual_collection=True)
    assert _Handler.crawl is ctl
    assert _Handler.mutation_authorizer is not None
    assert ctl.calls == []          # A: still nothing collected on load
    _Handler.crawl = None
    _Handler.mutation_authorizer = None
    _Handler.manual_collection_only = False


def test_opting_in_without_a_controller_is_refused(fake_httpd, tmp_path):
    from oem_radar.dashboard import serve

    with pytest.raises(ValueError, match="requires a crawl controller"):
        serve(str(tmp_path / "x.db"), open_browser=False, allow_manual_collection=True)


def test_manual_collection_launch_does_not_authorize_mark_seen(fake_httpd, tmp_path):
    """The opt-in authorizes collection only — not every mutation."""
    from oem_radar.dashboard import _Handler, serve

    ctl = RecordingController()
    serve(str(tmp_path / "x.db"), open_browser=False, crawl=ctl,
          allow_manual_collection=True)
    try:
        assert _Handler.manual_collection_only is True
        assert _Handler.review_writes_only is False
    finally:
        _Handler.crawl = None
        _Handler.mutation_authorizer = None
        _Handler.manual_collection_only = False


def test_desktop_launcher_opts_into_manual_collection():
    """The operator-facing entry point is the one that must work. Reads the
    launcher source rather than executing it (it opens a browser and serves
    forever), pinning that it passes the opt-in and never auto-crawls."""
    src = Path("launch_dashboard.py").read_text(encoding="utf-8")
    assert "allow_manual_collection=True" in src
    assert "auto_crawl=True" not in src


def test_gui_trigger_reaches_execute_crawl_under_the_canonical_lock(tmp_path, monkeypatch):
    """B + C + D + E + H: an explicit POST runs the canonical service, takes
    the canonical run lock, targets the canonical database, and the result
    is durable in the controller's inspectable state."""
    from oem_radar.core import crawl_service

    seen = {}

    def fake_execute_crawl(config_dir, *, force=False, only_source=None,
                           dry_run=False, use_lock=True, on_progress=None):
        # Prove the canonical signature is what the GUI path calls, and that
        # exclusivity is requested rather than bypassed.
        seen["config_dir"] = Path(config_dir)
        seen["use_lock"] = use_lock
        seen["force"] = force
        if on_progress:
            on_progress({"event": "planned", "sources_total": 1})
        return crawl_service.CrawlOutcome(
            sources=1, snapshots=0, events=0, errors=0, duration_s=0.1,
        )

    ctl = crawl_service.CrawlController(
        Path("config"), runner=fake_execute_crawl, allow_manual=True,
    )
    accepted, reason, _ = ctl.trigger(trigger="manual")
    assert accepted, reason
    ctl.join(timeout=30)

    assert seen["config_dir"] == Path("config")   # D: canonical config/DB resolution
    assert seen["use_lock"] is True               # C: canonical exclusivity, not bypassed
    state = ctl.status()
    assert state["trigger"] == "manual"           # F/provenance: manual vs auto
    assert state["running"] is False
    assert state["status"] in ("ok", "failed", "blocked")
    assert state["outcome"] is not None           # E: durable, inspectable result


def test_manual_and_scheduled_share_one_execution_path():
    """H + G: exactly one collector implementation; the scheduled CLI path is
    untouched by the GUI opt-in."""
    import inspect

    from oem_radar.core.crawl_service import CrawlController, execute_crawl
    from oem_radar import cli

    # The controller's default runner IS the canonical service.
    assert inspect.signature(CrawlController.__init__).parameters["runner"].default is execute_crawl
    # cmd_run still calls execute_crawl directly — unchanged by this work.
    assert "execute_crawl" in inspect.getsource(cli.cmd_run)

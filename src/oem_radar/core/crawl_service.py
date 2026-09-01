"""One way to run a crawl, and one way to trigger one in the background.

Before this module there was exactly one caller of `run_all` — `oem-radar
run` — so the assembly around it (resolve the webhook, build the fetcher,
build the store and notifier, take the single-instance lock, seed
components, count what's left pending) lived inline in `cli.py`. The
dashboard's "run collectors now" button is a second caller, and the
lesson of Stage 11.1 is that a second caller must not become a second
almost-identical implementation. So the assembly moved here, `cmd_run`
became a printer around `execute_crawl`, and the dashboard calls the same
function through `CrawlController`.

`CrawlController` adds only what a GUI needs on top: a background thread
so the HTTP request returns immediately, single-flight so two clicks
cannot start two crawls, and an observable state so the page can show
progress instead of a dead "reload" link.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .config import RadarConfig, load_oem_configs, load_radar_config, parse_interval
from .knownhw import SEED_COMPONENTS
from .registry import notifiers, stores
from .run_lock import LockError, RunLock
from .runner import run_all
from ..providers.sqlite import IncompatibleDatabaseError

log = logging.getLogger("oem_radar.crawl_service")

ProgressFn = Callable[[dict], None]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# assembly (moved verbatim from cli.py — this is the only copy)
# --------------------------------------------------------------------------

def resolve_webhook(radar: RadarConfig, config_dir: Path) -> tuple[str | None, int, str]:
    """Find the Discord webhook from, in order: the env var, or a
    `discord_webhook.txt` file in the config dir. The file means crawls run
    from ANY terminal notify correctly — not just via start-radar.cmd.
    Returns (webhook_or_None, min_severity, source_description)."""
    discord_cfg = radar.notify.get("discord")
    min_sev = discord_cfg.min_severity if discord_cfg else 3
    env_name = "OEM_RADAR_DISCORD_WEBHOOK"
    if discord_cfg:
        env_name = getattr(discord_cfg, "webhook_url_env", None) or env_name
    wh = os.environ.get(env_name)
    if wh:
        return wh, min_sev, f"env {env_name}"
    wf = config_dir / "discord_webhook.txt"
    if wf.exists():
        txt = wf.read_text(encoding="utf-8").strip()
        if txt and txt.startswith("http"):
            return txt, min_sev, str(wf.name)
    return None, min_sev, "none"


def build_fetcher(cfg: RadarConfig):
    from .fetch import HttpFetcher
    rl = cfg.rate_limit
    delay = rl.get("per_domain_delay", ["3s", "9s"])
    return HttpFetcher(
        cache_dir=Path(cfg.db_path).parent / "http_cache" if cfg.db_path != ":memory:" else None,
        delay_range=(float(parse_interval(delay[0])), float(parse_interval(delay[1]))),
        backoff_base=float(rl.get("backoff_base", 2)),
        backoff_max=float(parse_interval(rl.get("backoff_max", "300s"))),
        max_retries=int(rl.get("max_retries", 4)),
    )


def build_store_and_notifier(radar: RadarConfig, config_dir: Path, *, dry_run: bool = False):
    """Returns (store, notifier, webhook_source, webhook_present)."""
    if dry_run:
        store = stores.get(radar.store)(":memory:", radar.raw_dir)
        return store, notifiers.get("console")(), "none (dry run)", False
    store = stores.get(radar.store)(radar.db_path, radar.raw_dir)
    webhook, min_sev, wh_src = resolve_webhook(radar, config_dir)
    fb = radar.feedback
    notifier = notifiers.get(radar.notifier)(
        store, webhook, min_sev,
        review_base_url=fb.dashboard_base_url,
        feedback_enabled=fb.enabled,
    )
    return store, notifier, wh_src, webhook is not None


# --------------------------------------------------------------------------
# the one crawl entry point
# --------------------------------------------------------------------------

@dataclass
class CrawlOutcome:
    sources: int = 0
    snapshots: int = 0
    events: int = 0
    errors: int = 0
    pending_notifications: int = 0
    webhook_source: str = "none"
    webhook_present: bool = False
    duration_s: float = 0.0
    stats: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "sources": self.sources, "snapshots": self.snapshots,
            "events": self.events, "errors": self.errors,
            "pending_notifications": self.pending_notifications,
            "webhook_source": self.webhook_source,
            "webhook_present": self.webhook_present,
            "duration_s": round(self.duration_s, 1),
        }


def _ensure_registries() -> None:
    """Import the engine and provider modules for their registration side effect.

    `cli.py` has always done this at module import, which was enough while
    the CLI was the only thing that ran a crawl. The dashboard .exe
    (`launch_dashboard.py`) never imports the CLI, so a crawl triggered
    from the browser would have found an empty engine registry and failed
    on the first source. Registering here makes `execute_crawl` complete
    on its own terms rather than depending on who imported what first.
    """
    from .. import providers  # noqa: F401
    from ..engines import category_jsonld  # noqa: F401
    from ..engines import dell  # noqa: F401
    from ..engines import shopify  # noqa: F401
    from ..engines import sitemap_jsonld  # noqa: F401
    from ..engines import woocommerce_store_api  # noqa: F401
    from ..providers import discord  # noqa: F401
    from ..providers import sqlite  # noqa: F401


def execute_crawl(
    config_dir: str | Path,
    *,
    force: bool = False,
    only_source: str | None = None,
    dry_run: bool = False,
    use_lock: bool = True,
    on_progress: ProgressFn | None = None,
) -> CrawlOutcome:
    """Run one complete crawl. Raises `LockError` if another run holds the lock.

    Config is loaded fresh on every call, so editing `config/oems/*.yaml`
    takes effect on the next crawl without restarting a long-lived
    dashboard process.
    """
    _ensure_registries()
    config_dir = Path(config_dir)
    radar = load_radar_config(config_dir / "radar.yaml")
    oems = load_oem_configs(config_dir / "oems")

    lock = RunLock.acquire(radar.run_lock_path) if (use_lock and not dry_run) else None
    started = time.monotonic()
    store, notifier, wh_src, wh_present = build_store_and_notifier(
        radar, config_dir, dry_run=dry_run)
    try:
        store.seed_components(SEED_COMPONENTS)
        stats = run_all(radar, oems, store, notifier, build_fetcher(radar),
                        force=force, only_source=only_source,
                        on_progress=on_progress)
        outcome = CrawlOutcome(
            sources=len(stats),
            snapshots=sum(s.snapshots_written for s in stats),
            events=sum(s.events for s in stats),
            errors=sum(len(s.errors) for s in stats),
            webhook_source=wh_src,
            webhook_present=wh_present,
            stats=stats,
        )
        if not dry_run:
            outcome.pending_notifications = store.db.execute(
                "SELECT COUNT(*) c FROM notifications WHERE status='pending'"
            ).fetchone()["c"]
        outcome.duration_s = time.monotonic() - started
        return outcome
    finally:
        try:
            store.close()
        except Exception:  # noqa: BLE001 — closing must never mask a crawl error
            log.warning("store close failed after crawl", exc_info=True)
        if lock is not None:
            lock.release()


# --------------------------------------------------------------------------
# background trigger for the dashboard
# --------------------------------------------------------------------------

#: Terminal states. `blocked` is not a failure of this process — it means
#: something else (the scheduled hourly task, a terminal `oem-radar run`)
#: already holds the lock, which is the system working as designed.
IDLE, RUNNING, OK, FAILED, BLOCKED = "idle", "running", "ok", "failed", "blocked"


class CrawlController:
    """Single-flight background crawl trigger.

    One instance per dashboard process. `trigger()` returns immediately;
    `status()` is a cheap snapshot safe to poll from HTTP handler threads.

    Deliberately *not* a queue: if a crawl is running, a second trigger is
    refused rather than deferred. A crawl already in flight will pick up
    everything due anyway, so queueing would only produce a redundant
    second pass over the same catalogs.
    """

    def __init__(
        self,
        config_dir: str | Path,
        *,
        runner: Callable[..., CrawlOutcome] = execute_crawl,
        allow_manual: bool = True,
    ) -> None:
        self.config_dir = Path(config_dir)
        self._runner = runner
        self.allow_manual = allow_manual
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._state: dict[str, Any] = self._fresh_state()

    @staticmethod
    def _fresh_state() -> dict[str, Any]:
        return {
            "status": IDLE,
            "trigger": None,          # "auto" | "manual"
            "started_at": None,
            "finished_at": None,
            "current_source": None,
            "sources_done": 0,
            "sources_total": 0,
            "sources": [],            # [{source, status, events, snapshots, errors}]
            "outcome": None,
            "message": None,
            "force": False,
        }

    # -- public API --------------------------------------------------------

    @property
    def running(self) -> bool:
        with self._lock:
            return self._state["status"] == RUNNING

    def status(self) -> dict:
        with self._lock:
            snap = dict(self._state)
            snap["sources"] = list(self._state["sources"])
        snap["allow_manual"] = self.allow_manual
        snap["running"] = snap["status"] == RUNNING
        return snap

    def trigger(
        self, *, force: bool = False, only_source: str | None = None,
        trigger: str = "manual",
    ) -> tuple[bool, str, dict]:
        """Start a crawl in the background.

        Returns (accepted, reason, status). `accepted` is False when a
        crawl is already in flight, or when manual triggering is disabled
        and this is a manual request.
        """
        if trigger == "manual" and not self.allow_manual:
            return False, "manual_crawl_disabled", self.status()
        with self._lock:
            if self._state["status"] == RUNNING:
                return False, "already_running", self._snapshot_locked()
            self._state = self._fresh_state()
            self._state.update({
                "status": RUNNING, "trigger": trigger,
                "started_at": _now(), "force": force,
                "message": "starting…",
            })
            snap = self._snapshot_locked()
            self._thread = threading.Thread(
                target=self._run, args=(force, only_source),
                name="oem-radar-crawl", daemon=True,
            )
            self._thread.start()
        return True, "started", snap

    def join(self, timeout: float | None = None) -> None:
        """Wait for an in-flight crawl. Used by tests and by shutdown."""
        t = self._thread
        if t is not None:
            t.join(timeout)

    # -- internals ---------------------------------------------------------

    def _snapshot_locked(self) -> dict:
        snap = dict(self._state)
        snap["sources"] = list(self._state["sources"])
        snap["allow_manual"] = self.allow_manual
        snap["running"] = snap["status"] == RUNNING
        return snap

    def _on_progress(self, ev: dict) -> None:
        with self._lock:
            if ev.get("event") == "planned":
                self._state["sources_total"] = ev.get("sources_total", 0)
                self._state["message"] = f"{ev.get('sources_total', 0)} source(s) to check"
            elif ev.get("event") == "source_start":
                self._state["current_source"] = ev.get("source")
                self._state["message"] = f"crawling {ev.get('source')}"
            elif ev.get("event") in ("source_done", "source_skipped"):
                self._state["sources_done"] += 1
                self._state["current_source"] = None
                self._state["sources"].append({
                    "source": ev.get("source"),
                    "status": ev.get("status"),
                    "events": ev.get("events"),
                    "snapshots": ev.get("snapshots"),
                    "errors": ev.get("errors"),
                })
            elif ev.get("event") == "stories":
                self._state["current_source"] = None
                self._state["message"] = "correlating stories"

    def _run(self, force: bool, only_source: str | None) -> None:
        try:
            outcome = self._runner(
                self.config_dir, force=force, only_source=only_source,
                on_progress=self._on_progress,
            )
        except LockError as exc:
            self._finish(BLOCKED, str(exc))
            log.info("dashboard crawl blocked: %s", exc)
            return
        except IncompatibleDatabaseError as exc:
            # Persistent-state gate (STD-DEPLOY-COM-002): the one-shot crawl
            # refuses before touching incompatible state, however
            # short-lived the process. The refusal is recorded as the
            # crawl's outcome so the evidence survives in the dashboard.
            self._finish(
                FAILED,
                f"persistent-state compatibility refused: {exc}",
                outcome=exc.report.as_evidence(),
            )
            log.warning("dashboard crawl refused by the persistent-state "
                        "compatibility gate: %s", exc)
            return
        except Exception as exc:  # noqa: BLE001 — a crawl failure must not kill the server
            self._finish(FAILED, f"{type(exc).__name__}: {exc}")
            log.exception("dashboard-triggered crawl failed")
            return
        d = outcome.as_dict() if hasattr(outcome, "as_dict") else dict(outcome)
        msg = (f"{d['sources']} source(s) crawled · {d['snapshots']} snapshot(s) · "
               f"{d['events']} change(s)")
        if d.get("errors"):
            msg += f" · {d['errors']} error(s)"
        self._finish(OK, msg, outcome=d)

    def _finish(self, status: str, message: str, outcome: dict | None = None) -> None:
        with self._lock:
            self._state.update({
                "status": status, "message": message,
                "finished_at": _now(), "current_source": None,
                "outcome": outcome,
            })

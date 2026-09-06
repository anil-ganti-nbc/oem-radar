"""run_all: iterate configured OEMs/sources, honoring due-ness, recording
telemetry, then drain the outbox. Separated from the CLI so tests can inject
fake fetchers/stores/notifiers."""

from __future__ import annotations

import logging
from typing import Any, Callable, Iterable

from .config import OemConfig, RadarConfig, SourceConfig
from .interfaces import Fetcher, Notifier
from .pipeline import SourceRunStats, run_source
from .registry import engines
from .story import detect as detect_stories


class ManualScopeError(ValueError):
    """A manual run was asked for a scope the canonical registry cannot
    honor (e.g. no routine collectors configured). Carries a machine-
    readable code so an operator surface can show actionable evidence
    instead of a bare failure."""

    def __init__(self, code: str, message: str, *, detail: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or {}

log = logging.getLogger("oem_radar.runner")


def sync_oem_registry(store, oems: dict[str, OemConfig]) -> int:
    """Project every configured OEM into the `manufacturers` table.

    `config/oems/*.yaml` is the authority on which OEMs this project
    tracks; the DB table is only a projection of it. Before Stage 11.1 that
    projection was a *side effect of crawling* — `ensure_manufacturer` ran
    inside `run_all`'s per-source loop — so an OEM added to config but not
    yet crawled (or whose only source is disabled) simply did not exist as
    far as the dashboard was concerned. That is what made the manufacturer
    filter incomplete, and no amount of fixing the dropdown's JS could have
    fixed it: the data was not there to show.

    This is now the single writer of that projection. Call it anywhere
    config and a writable store are both in hand — crawls do, and so does
    the dashboard at startup. Returns the number of OEMs synced.
    """
    for oem in oems.values():
        man = oem.manufacturer
        store.ensure_manufacturer(man.name, man.country, man.aliases)
    return len(oems)


def run_all(
    radar_cfg: RadarConfig,
    oems: dict[str, OemConfig],
    store,
    notifier: Notifier,
    fetcher: Fetcher,
    *,
    force: bool = False,
    only_source: str | None = None,
    only_sources: Iterable[str] | None = None,
    routine_scope: bool = False,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> list[SourceRunStats]:
    rules = radar_cfg.severity_rules or None
    all_stats: list[SourceRunStats] = []

    # Scope and freshness are separate dimensions. `only_source` (singular,
    # the CLI's --source) and `only_sources` (an explicit collector set,
    # e.g. an operator's deep-crawl selection) narrow WHICH collectors run.
    # `routine_scope` (the dashboard's default manual action) resolves the
    # routine set — every enabled collector NOT classified long_running —
    # so a manual click stays bounded even when new deep sources are added
    # to the registry. No dimension of this touches force, enablement,
    # maturity or health.
    scope: frozenset[str] | None
    if only_sources is not None:
        scope = frozenset(only_sources)
    elif only_source is not None:
        scope = frozenset({only_source})
    elif routine_scope:
        scope = frozenset(
            src.id
            for oem in oems.values() for src in oem.sources
            if src.enabled and src.manual_class == "routine"
        )
        if not scope:
            raise ManualScopeError(
                "no_routine_collectors",
                "no routine collectors are configured; the default manual "
                "action would silently run nothing — use the long-running "
                "collector selection explicitly",
            )
    else:
        scope = None

    def emit(**ev: Any) -> None:
        """Report progress to an observer (the dashboard's crawl bar).

        A crawl is long — Medion alone is over an hour — so a caller that
        wants to show progress needs to hear about it as it happens, not
        in the return value. Wrapped: an observer that raises must never
        abort a crawl that is otherwise fine.
        """
        if on_progress is None:
            return
        try:
            on_progress(ev)
        except Exception:  # noqa: BLE001
            log.warning("progress observer raised; continuing crawl", exc_info=True)

    # Every configured OEM becomes visible immediately — including ones this
    # run will skip (disabled, not due, or filtered out by scope).
    sync_oem_registry(store, oems)

    planned = [
        src for oem in oems.values() for src in oem.sources
        if src.enabled and (scope is None or src.id in scope)
    ]
    emit(event="planned", sources_total=len(planned))

    for oem in oems.values():
        man = oem.manufacturer
        man_id = store.ensure_manufacturer(man.name, man.country, man.aliases)
        for src in oem.sources:
            if not src.enabled or (scope is not None and src.id not in scope):
                continue
            if not force and not store.source_due(src.id, src.min_interval_s):
                log.info("skip %s: crawled within min_interval", src.id)
                emit(event="source_skipped", source=src.id, status="skipped")
                continue
            emit(event="source_start", source=src.id)
            store.ensure_source(src.id, man_id, src.engine, src.base_url, src.model_dump())
            baseline = radar_cfg.baseline_quiet and not store.has_completed_run(src.id)
            if baseline:
                log.info("%s: first crawl — baseline mode, notifications suppressed", src.id)
            run_id = store.run_started(src.id)
            try:
                engine = engines.get(src.engine)(src, man.name)
                stats = run_source(
                    src, engine, fetcher, store, notifier, rules,
                    baseline=baseline,
                    health_cfg=radar_cfg.collector_health,
                )
                # Failed catalog health must not become the last-good baseline.
                run_status = "failed" if stats.health == "failed" else "ok"
                store.run_finished(
                    run_id, run_status,
                    vars(stats) | {
                        "errors": len(stats.errors),
                        "health": stats.health,
                        "health_reason": getattr(stats, "health_reason", None),
                    },
                    stats.errors,
                )
                all_stats.append(stats)
                emit(event="source_done", source=src.id, status=run_status,
                     events=stats.events, snapshots=stats.snapshots_written,
                     errors=len(stats.errors))
                log.info(
                    "%s: %d discovered, %d new snapshots, %d unchanged, %d skipped, "
                    "%d events, %d errors",
                    src.id, stats.discovered, stats.snapshots_written,
                    stats.unchanged, stats.skipped, stats.events, len(stats.errors),
                )
                sent_now = notifier.drain()  # per-source: embeds arrive promptly
                if sent_now:
                    log.info("sent %d notification(s)", sent_now)
            except Exception as exc:
                store.run_finished(run_id, "failed", {}, [repr(exc)])
                emit(event="source_done", source=src.id, status="failed", errors=1)
                log.exception("source %s failed entirely: %r", src.id, exc)

    # Story detection (DESIGN_REVIEW §7): correlate this and recent events
    # across OEMs, BEFORE the final drain, so a story can demote its
    # constituent product pings. Deterministic; runs only if rules exist.
    story_rules = getattr(radar_cfg, "story_rules", None) or []
    if story_rules and hasattr(store, "event_rows_for_stories"):
        emit(event="stories")
        max_window = max(r.window_s for r in story_rules)
        rows = store.event_rows_for_stories(max_window)
        for story in detect_stories(rows, story_rules):
            if store.story_exists(story.dedup_key()):
                continue  # already alerted this OEM-set for this key
            store.save_story(story)
            keys = [e.product_key for e in story.evidence]
            demoted = store.demote_events_for_products(keys)
            if hasattr(notifier, "enqueue_story"):
                notifier.enqueue_story(story)
            log.info("STORY: %s (score %d, demoted %d ping(s))",
                     story.title, story.score, demoted)

    sent = notifier.drain()
    if sent:
        log.info("drained outbox: %d notification(s) sent", sent)
    emit(event="finished", sources_crawled=len(all_stats))
    return all_stats

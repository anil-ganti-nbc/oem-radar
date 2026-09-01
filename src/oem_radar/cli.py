"""oem-radar CLI: validate | run | status | probe.

Exit codes: 0 success; 1 operational failure; 2 single-instance lock held
by another run; 3 persistent-state compatibility refusal — the database
state is unknown, corrupt, partial, or newer than this software understands
(STD-DEPLOY-COM-002); normal work was refused before anything mutated and
the refusal JSON carries the read-only compatibility evidence.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .core.config import (
    ConfigError,
    RadarConfig,
    load_oem_configs,
    load_radar_config,
)
from .core.crawl_service import build_fetcher, resolve_webhook
from .core.registry import engines, stores
from .providers.sqlite import IncompatibleDatabaseError

# Imports for side effect: registry registration.
from . import providers  # noqa: F401
from .engines import category_jsonld  # noqa: F401
from .engines import dell  # noqa: F401
from .engines import shopify  # noqa: F401
from .engines import sitemap_jsonld  # noqa: F401
from .engines import woocommerce_store_api  # noqa: F401
from .providers import discord as _discord  # noqa: F401
from .providers import sqlite as _sqlite  # noqa: F401

log = logging.getLogger("oem_radar.cli")


def _load(config_dir: Path) -> tuple[RadarConfig, dict]:
    radar = load_radar_config(config_dir / "radar.yaml")
    oems = load_oem_configs(config_dir / "oems")
    return radar, oems


def _open_store(radar: RadarConfig):
    """Construct the configured store behind the persistent-state
    compatibility barrier (STD-DEPLOY-COM-002). Returns the store, or None
    after printing the machine-readable refusal (exit code 3) with the
    read-only evidence — the caller must not touch the database then."""
    from .providers.sqlite import IncompatibleDatabaseError

    try:
        return stores.get(radar.store)(radar.db_path, radar.raw_dir)
    except IncompatibleDatabaseError as exc:
        print(json.dumps({
            "status": "state_incompatible",
            "gate": "persistent_state_compatibility",
            **exc.report.as_evidence(),
        }, indent=2, default=str))
        return None


def cmd_version(args: argparse.Namespace) -> int:
    from . import runtime_bridge

    print(json.dumps(runtime_bridge.get_version_info(), indent=2, default=str))
    return 0


def cmd_identity(args: argparse.Namespace) -> int:
    from . import runtime_bridge

    identity = runtime_bridge.as_jsonable(runtime_bridge.get_identity())
    print(json.dumps(identity, indent=2, default=str))
    return 0


def cmd_health(args: argparse.Namespace) -> int:
    from . import runtime_bridge
    from .paths import resolve_data_path

    config_dir = Path(args.config)
    try:
        radar = load_radar_config(config_dir / "radar.yaml")
        db_path = resolve_data_path(radar.db_path)
    except Exception:  # noqa: BLE001 - health must not raise even if config is broken
        db_path = resolve_data_path("data/radar.db")

    payload = runtime_bridge.as_jsonable(runtime_bridge.get_health(db_path))
    print(json.dumps(payload, indent=2, default=str))
    return 1 if payload.get("operational_state") == "failed" else 0


def _setup_logging(cfg: RadarConfig) -> None:
    level = getattr(logging, str(cfg.logging.get("level", "INFO")).upper(), logging.INFO)
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if cfg.logging.get("file"):
        Path(cfg.logging["file"]).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(cfg.logging["file"], encoding="utf-8"))
    logging.basicConfig(
        level=level, handlers=handlers,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def cmd_validate(args: argparse.Namespace) -> int:
    try:
        radar, oems = _load(Path(args.config))
    except (ConfigError, FileNotFoundError) as e:
        problems = e.problems if isinstance(e, ConfigError) else [str(e)]
        for p in problems:
            print(f"ERROR: {p}", file=sys.stderr)
        return 1
    problems = []
    for oem in oems.values():
        for src in oem.sources:
            if src.engine not in engines:
                problems.append(f"source {src.id}: unknown engine {src.engine!r} "
                                f"(registered: {engines.names()})")
                continue
            schema = engines.get(src.engine).config_schema
            try:
                schema.model_validate(src.model_dump())
            except Exception as exc:
                problems.append(f"source {src.id}: engine config invalid: {exc}")
    if problems:
        for p in problems:
            print(f"ERROR: {p}", file=sys.stderr)
        return 1
    n_sources = sum(len(o.sources) for o in oems.values())
    print(f"OK: {len(oems)} OEM(s), {n_sources} source(s), engines: {engines.names()}")
    return 0


# The run-assembly helpers moved to core.crawl_service so the dashboard's
# "run collectors now" button drives the identical code path. Re-exported
# here under their old names because that is how they are referred to in
# docs/COLLECTOR_ECONOMICS.md and in operator muscle memory.
_resolve_webhook = resolve_webhook
_build_fetcher = build_fetcher


def cmd_run(args: argparse.Namespace) -> int:
    from .core.crawl_service import execute_crawl
    from .core.run_lock import LockError

    radar, _ = _load(Path(args.config))
    _setup_logging(radar)

    if args.dry_run:
        print("dry run: in-memory store, console notifications, nothing persisted")
    elif resolve_webhook(radar, Path(args.config))[0] is None:
        print("WARNING: no Discord webhook found — notifications will queue "
              "as pending and NOT send.\n  Fix: run via start-radar.cmd, or put "
              "your webhook URL in config/discord_webhook.txt", file=sys.stderr)

    try:
        out = execute_crawl(
            Path(args.config),
            force=args.force, only_source=args.source,
            dry_run=args.dry_run,
            use_lock=not getattr(args, "no_lock", False),
        )
    except LockError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    except IncompatibleDatabaseError as e:
        print(json.dumps({
            "status": "state_incompatible",
            "gate": "persistent_state_compatibility",
            **e.report.as_evidence(),
        }, indent=2, default=str))
        return 3

    print(f"done: {out.sources} source(s) crawled, {out.snapshots} snapshot(s), "
          f"{out.events} event(s)")
    if out.pending_notifications:
        print(f"note: {out.pending_notifications} notification(s) still pending in "
              f"the outbox (webhook source: {out.webhook_source})")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    radar, _ = _load(Path(args.config))
    store = _open_store(radar)
    if store is None:
        return 3
    rows = store.recent_runs(20)
    if not rows:
        print("no runs recorded yet")
        return 0
    print(f"{'source':<24} {'started':<21} {'status':<7} stats")
    for r in rows:
        print(f"{r['source_key']:<24} {r['started_at'][:19]:<21} {r['status']:<7} "
              f"{r['stats_json']}")
    return 0


def cmd_coverage(args: argparse.Namespace) -> int:
    """Stage 7 Phase 6: platform-wide coverage/health/signal metrics.
    Config-derived numbers always print; DB-derived ones degrade gracefully
    if no database exists yet."""
    from .core.metrics import compute_platform_metrics
    from .providers.sqlite import connect_readonly

    radar, _ = _load(Path(args.config))
    conn = None
    if Path(radar.db_path).exists():
        conn = connect_readonly(radar.db_path)
    try:
        m = compute_platform_metrics(Path("config/oems"), Path("tests/fixtures"), conn)
    finally:
        if conn is not None:
            conn.close()

    if args.json:
        print(json.dumps(m, indent=2))
        return 0

    c = m["coverage"]
    print("=== Coverage ===")
    print(f"  OEM descriptors: {c['total_oem_descriptors']}  "
          f"(loaded: {c['total_oems_loaded']})")
    print(f"  Enabled sources: {c['enabled_sources']}   Disabled: {c['disabled_sources']}")
    print(f"  Engines in use: {', '.join(c['engines_in_use']) or '(none)'}")
    for engine, n in sorted(c["sources_per_engine"].items()):
        oems = c["enabled_oems_per_engine"].get(engine, [])
        print(f"    {engine}: {n} source(s) — {', '.join(oems)}")
    print("  Status breakdown (from descriptor `# support_status:` comments):")
    for status, n in sorted(c["status_breakdown"].items(), key=lambda x: -x[1]):
        print(f"    {status}: {n}")

    print("\n=== Fixture coverage ===")
    for engine, n in sorted(m["fixture_coverage"].items()):
        print(f"  {engine}: {n} fixture file(s)")

    h = m["health"]
    print("\n=== Health ===")
    if "note" in h:
        print(f"  {h['note']}")
    else:
        print(f"  Runs recorded: {h['total_runs']}  (ok: {h['ok_runs']}, failed: {h['failed_runs']})")
        rate = h["run_failure_rate"]
        print(f"  Run failure rate: {rate if rate is not None else 'n/a'}")
        print(f"  Collectors currently: healthy={h['collectors_currently_healthy']} "
              f"degraded={h['collectors_currently_degraded']} "
              f"failed={h['collectors_currently_failed']}")
        print(f"  Average catalog size: {h['average_catalog_size']}")
        dur = h["average_crawl_duration_seconds"]
        print(f"  Average crawl duration: {dur if dur is not None else 'not tracked (no finished runs yet)'}"
              + ("" if dur is None else "s"))
        stability = h["collector_stability"]
        print(f"  Collector stability (latest run ok): "
              f"{stability if stability is not None else 'n/a'}")

    es = m.get("engine_stability") or {}
    print("\n=== Engine stability (latest run per source, by engine) ===")
    if not es:
        print("  n/a (no database or no runs yet)")
    else:
        for engine, rate in sorted(es.items()):
            print(f"  {engine}: {rate}")

    s = m["signals"]
    print("\n=== Signals (feedback analytics) ===")
    if "note" in s:
        print(f"  {s['note']}")
    else:
        print(f"  Total change events: {s['total_change_events']}")
        print(f"  Reviewed: {s['reviewed_alerts']}  Unreviewed: {s['unreviewed_alerts']}")
        print(f"  HIT={s['hit_count']} INTERESTING={s['interesting_count']} "
              f"NOISE={s['noise_count']} BUG={s['bug_count']}")
        snr = s["signal_to_noise_ratio"]
        print(f"  Signal/Noise ratio: {'infinite' if s['signal_to_noise_infinite'] else snr}")
        print(f"  False-positive rate: {s['false_positive_rate']}")
        print(f"  New products/day: {s['new_products_per_day']}  "
              f"Changed/day: {s['changed_products_per_day']}  "
              f"Alerts/day: {s['alerts_per_day']}")
    return 0


def cmd_sanitize_har(args: argparse.Namespace) -> int:
    from .core.har_sanitize import sanitize_har

    src = Path(args.file)
    try:
        har = json.loads(src.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"sanitize-har failed: could not read/parse {src}: {e}", file=sys.stderr)
        return 1

    try:
        clean = sanitize_har(har)
    except ValueError as e:
        print(f"sanitize-har failed: {e}", file=sys.stderr)
        return 1

    out = Path(args.out) if args.out else src.with_name(src.stem + ".sanitized.har")
    out.write_text(json.dumps(clean, indent=2), encoding="utf-8")
    entry_count = len(clean.get("log", {}).get("entries", []))
    print(f"sanitized {entry_count} entr(y/ies) -> {out}")
    print("Stripped: cookies, Authorization/CSRF/API-key headers, bearer tokens, "
          "session-shaped query params and JSON body fields.")
    print("Review the output before pasting it into a doc or committing it as a fixture — "
          "this redacts known-sensitive shapes, it does not guarantee nothing sensitive remains.")
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    from .core.probe import probe_storefront

    r = probe_storefront(args.url)
    if r.error:
        print(f"probe failed: {r.error}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(r.to_dict(), indent=2))
        return 0

    score, deductions = r.discovery_quality()
    pursue, pursue_reason = r.should_pursue()

    print(f"{r.input_url}")
    print(f"  status: {r.status}" + (f"  (redirected -> {r.final_url})" if r.redirected else ""))
    print()
    print(f"Confidence          {r.confidence()}%")
    print("Evidence")
    for line in r.evidence():
        print(f"  - {line}")
    print(f"Theme                framework={r.framework or 'none detected'}"
          + (f", server={r.server_header}" if r.server_header else ""))
    print(f"Discovery            sitemap={'yes' if r.sitemap_found else 'no'}"
          f", bulk_api={'yes' if (r.shopify_products_json or r.woocommerce_store_api) else 'no'}"
          f", jsonld={'yes' if r.jsonld_product_count else 'no'}")
    print(f"Discovery Quality    {score}/100")
    for cat, pts, reason in deductions:
        print(f"  -{pts:>3} [{cat}] {reason}")
    print(f"Recommended engine   {r.collector_recommendation()}")
    print(f"Engineering effort   {r.estimated_implementation_effort()}")
    print(f"Engineer time        {r.recommended_engineer_time()}")
    print(f"Fixture count        {r.recommended_fixture_count()}")
    print("Expected editorial value   not determined by a static probe — requires human judgment (brand/market position)")
    print("Known risks")
    for risk in r.known_risks():
        print(f"  - {risk}")
    print("Missing information")
    for m in r.missing_information():
        print(f"  - {m}")
    print(f"Recommended next step   {r.recommended_next_step()}")
    print(f"Should this OEM be pursued?   {'YES' if pursue else 'NO'} — {pursue_reason}")
    return 0


def sync_registry_before_serve(radar: RadarConfig, oems: dict) -> int:
    """Refresh the OEM registry projection, then hand off to the read-only
    dashboard. Shared by `oem-radar dashboard` and launch_dashboard.py so
    both entry points show the same, complete OEM list.

    Best-effort by design: a locked DB (a crawl is running) or a
    read-only file must not stop you opening the dashboard. Returns the
    number of OEMs synced, or 0 if the sync was skipped.
    """
    try:
        store = _open_store(radar)
    except IncompatibleDatabaseError as exc:
        # Never masked as a mere "sync skipped": the compatibility refusal
        # must name its gate; the dashboard's data surfaces will refuse too.
        log.warning("OEM registry sync refused by the persistent-state "
                    "compatibility gate (%s)", exc)
        return 0
    except Exception as exc:  # noqa: BLE001 — never block the dashboard
        log.warning("OEM registry sync skipped (%s); "
                    "manufacturer list may be incomplete", exc)
        return 0
    try:
        from .core.runner import sync_oem_registry
        return sync_oem_registry(store, oems)
    except Exception as exc:  # noqa: BLE001
        log.warning("OEM registry sync failed (%s); "
                    "manufacturer list may be incomplete", exc)
        return 0
    finally:
        store.close()


def cmd_dashboard(args: argparse.Namespace) -> int:
    from pathlib import Path as _P

    from .dashboard import serve

    radar, oems = _load(_P(args.config))
    if not _P(radar.db_path).exists():
        print(f"no database at {radar.db_path} yet — run a crawl first "
              "(oem-radar run)", file=sys.stderr)
        return 1
    sync_registry_before_serve(radar, oems)
    fb = radar.feedback
    serve(radar.db_path, host=args.host, port=args.port,
          open_browser=not args.no_browser,
          max_body=fb.max_review_request_bytes,
          raw_dir=radar.raw_dir,
          **build_dashboard_crawl_kwargs(radar, _P(args.config), args),
          **build_dashboard_review_kwarg(radar, args))
    return 0


def build_dashboard_review_kwarg(radar: RadarConfig,
                                 args: argparse.Namespace | None = None) -> dict:
    """M4.5 QC activation: review writes are opt-in per launch via
    --allow-review-writes (default off). Loopback-only remains enforced in
    serve(); only /api/alerts/{id}/review is ever authorized."""
    enabled = getattr(args, "allow_review_writes", False)
    return {"allow_review_writes": bool(enabled)}


def build_dashboard_crawl_kwargs(radar: RadarConfig, config_dir: Path,
                                 args: argparse.Namespace | None = None) -> dict:
    """Decide whether this dashboard process may crawl, and hand `serve`
    the controller if so.

    Kept out of `serve` on purpose: the dashboard package serves a
    database, and deciding to reach out to the internet is a separate
    authority that belongs to whoever launched the process and holds the
    config. `--no-crawl` on the command line always wins over config.
    """
    dash = radar.dashboard
    # Phase 0 has no authenticated dashboard mutation profile. CSRF is not
    # authentication, so dashboard-triggered and launch-triggered crawls are
    # disabled regardless of older configuration values.
    return {
        "crawl": None,
        "auto_crawl": False,
        "auto_crawl_force": False,
        "stale_after_hours": dash.stale_after_hours,
    }


def cmd_outbox(args: argparse.Namespace) -> int:
    """Inspect the notification outbox; optionally suppress everything pending."""
    radar, _ = _load(Path(args.config))
    store = _open_store(radar)
    if store is None:
        return 3
    if args.suppress_pending:
        n = store.db.execute(
            "UPDATE notifications SET status='suppressed' WHERE status='pending'"
        ).rowcount
        store.db.commit()
        print(f"suppressed {n} pending notification(s) — they stay in history, won't send")
        return 0
    for row in store.db.execute(
        "SELECT status, COUNT(*) c FROM notifications GROUP BY status"
    ).fetchall():
        print(f"{row['status']:<12} {row['c']}")
    return 0


def cmd_test_notify(args: argparse.Namespace) -> int:
    """Send a sample embed through the real webhook path to verify wiring."""
    from datetime import datetime, timezone

    from .core.models import ChangeEvent, ChangeType, Component, NormalizedProduct, Price, Severity
    from .providers.discord import _post_webhook, build_embed

    radar, _ = _load(Path(args.config))
    webhook = args.webhook or _resolve_webhook(radar, Path(args.config))[0]
    if not webhook:
        print("no webhook found. Set it one of three ways:\n"
              "  1. run via start-radar.cmd (sets the env var)\n"
              "  2. put the URL in config/discord_webhook.txt\n"
              "  3. pass --webhook <url>", file=sys.stderr)
        return 1

    product = NormalizedProduct(
        manufacturer="GMKtec", model="K12 (sample)",
        cpu=Component(raw="AMD Ryzen AI MAX+ 396", canonical="ryzen-ai-max+-396", known=False),
        gpu=Component(raw="Radeon 8060S"), memory="128 GB", storage="2 TB",
        prices=[Price(amount=999.99, currency="USD", region="US")],
        source_url="https://www.gmktec.com/products/example",
    )
    event = ChangeEvent(
        product_key="test:k12", change_type=ChangeType.NEW_PRODUCT,
        new_value="K12", severity=Severity.BREAKING,
        detected_at=datetime.now(timezone.utc),
        meta={"hidden": True, "unseen_component": True},
    )
    payload = build_embed(event, product)
    payload["embeds"][0]["footer"] = {"text": "OEM Radar — test notification, not a real product"}
    ok, err = _post_webhook(webhook, payload)
    print("sent — check your Discord channel" if ok else f"failed: {err}")
    return 0 if ok else 1



def cmd_feedback_analyze(args: argparse.Namespace) -> int:
    """Deterministic offline analysis of reviewed alerts → suggestions."""
    from .core.feedback_analyze import analyze_reviews, persist_candidates
    radar, _ = _load(Path(args.config))
    store = _open_store(radar)
    if store is None:
        return 3
    fb = radar.feedback
    min_samples = args.minimum_samples or fb.minimum_samples_for_suggestion
    min_noise = args.minimum_noise_ratio if args.minimum_noise_ratio is not None else fb.minimum_noise_ratio
    max_sig = args.maximum_signal_loss_ratio if args.maximum_signal_loss_ratio is not None else getattr(fb, "maximum_signal_loss_ratio", fb.maximum_hit_loss_ratio)
    try:
        cands = analyze_reviews(
            store.db,
            start=args.start,
            end=args.end,
            collector=args.collector,
            alert_type=args.alert_type,
            min_samples=min_samples,
            min_noise_ratio=min_noise,
            max_signal_loss_ratio=max_sig,
        )
        if args.dry_run:
            rows = [
                {
                    "collector": c.collector,
                    "alert_type": c.alert_type,
                    "reason_code": c.reason_code,
                    "rule_type": c.rule_type,
                    "explanation": c.explanation,
                    "supporting_alert_count": c.supporting_alert_count,
                    "estimated_noise_reduction": c.estimated_noise_reduction,
                    "estimated_signal_loss": c.estimated_signal_loss,
                    "fingerprint": c.fingerprint(),
                    "status": "PROPOSED",
                }
                for c in cands
            ]
        else:
            rows = persist_candidates(store, cands, max_signal_loss_ratio=max_sig)
    finally:
        store.close()

    if args.json:
        import json as _json
        print(_json.dumps({"suggestions": rows, "count": len(rows)}, indent=2, default=str))
        return 0
    if not rows:
        print("No suggestions (insufficient evidence or no matching patterns).")
        return 0
    for r in rows:
        print(f"Collector: {r.get('collector')}")
        print(f"Alert type: {r.get('alert_type')}")
        print(f"Pattern: {r.get('explanation') or r.get('suggested_rule')}")
        print(f"Estimated noise reduction: {(r.get('estimated_noise_reduction') or 0)*100:.1f}%")
        print(f"Estimated signal loss: {(r.get('estimated_signal_loss') or r.get('estimated_hit_loss') or 0)*100:.1f}%")
        print(f"Status: {r.get('status')}")
        if r.get("id"):
            print(f"ID: {r['id']}")
        print("---")
    return 0


def cmd_feedback_simulate(args: argparse.Namespace) -> int:
    from .core.feedback_simulate import simulate_rule
    from .core.feedback import FeedbackError
    radar, _ = _load(Path(args.config))
    store = _open_store(radar)
    if store is None:
        return 3
    fb = radar.feedback
    try:
        result = simulate_rule(
            store.db,
            rule_id=args.rule_id,
            start=args.start,
            end=args.end,
            min_samples=fb.minimum_samples_for_suggestion,
            max_signal_loss_ratio=getattr(fb, "maximum_signal_loss_ratio", fb.maximum_hit_loss_ratio),
        )
    except FeedbackError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        store.close()
        return 1
    finally:
        store.close()
    if args.json:
        import json as _json
        print(_json.dumps(result, indent=2, default=str))
        return 0
    print(f"Suggestion {result.get('rule_id')}")
    rule = result.get("rule") or {}
    print(f"Rule: {rule.get('rule_type')}")
    print(f"Historical alerts matched: {result['total_matched']}")
    print(f"Reviewed matches: {result['reviewed_matched']}")
    print(f"NOISE affected: {result['noise_affected']}")
    print(f"BUG affected: {result['bug_affected']}")
    print(f"HIT affected: {result['hit_affected']}")
    print(f"INTERESTING affected: {result['interesting_affected']}")
    nr = result.get("estimated_noise_reduction")
    sl = result.get("estimated_signal_loss")
    print(f"Estimated noise reduction: {nr*100:.1f}%" if nr is not None else "Estimated noise reduction: n/a")
    print(f"Estimated signal loss: {sl*100:.1f}%" if sl is not None else "Estimated signal loss: n/a")
    print(f"Assessment: {result['assessment']}")
    if result.get("warnings"):
        print(f"Warnings: {', '.join(result['warnings'])}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="oem-radar", description="OEM product intelligence")
    parser.add_argument("--config", default="config", help="config directory (default: config)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("validate", help="validate configuration offline").set_defaults(func=cmd_validate)

    sub.add_parser("version", help="print runtime version info as JSON").set_defaults(func=cmd_version)
    sub.add_parser("identity", help="print Stage 0.5 runtime identity as JSON").set_defaults(func=cmd_identity)
    sub.add_parser("health", help="print truthful runtime health as JSON").set_defaults(func=cmd_health)

    p_run = sub.add_parser("run", help="one-shot crawl of all due sources")
    p_run.add_argument("--dry-run", action="store_true", help="no persistence, console output")
    p_run.add_argument("--force", action="store_true", help="ignore min_interval")
    p_run.add_argument("--source", help="crawl only this source id")
    p_run.add_argument("--no-lock", action="store_true",
                      help="skip single-instance lock (not recommended)")
    p_run.set_defaults(func=cmd_run)

    sub.add_parser("status", help="recent run telemetry").set_defaults(func=cmd_status)

    p_coverage = sub.add_parser("coverage", help="platform-wide coverage/health/signal metrics")
    p_coverage.add_argument("--json", action="store_true", help="print the full metrics as JSON")
    p_coverage.set_defaults(func=cmd_coverage)

    
    p_fb = sub.add_parser("feedback", help="feedback analyze | simulate")
    fb_sub = p_fb.add_subparsers(dest="feedback_cmd", required=True)
    p_an = fb_sub.add_parser("analyze", help="deterministic noise-pattern analysis")
    p_an.add_argument("--start")
    p_an.add_argument("--end")
    p_an.add_argument("--collector")
    p_an.add_argument("--alert-type")
    p_an.add_argument("--minimum-samples", type=int, default=None)
    p_an.add_argument("--minimum-noise-ratio", type=float, default=None)
    p_an.add_argument("--maximum-signal-loss-ratio", type=float, default=None)
    p_an.add_argument("--dry-run", action="store_true")
    p_an.add_argument("--json", action="store_true")
    p_an.set_defaults(func=cmd_feedback_analyze)
    p_sim = fb_sub.add_parser("simulate", help="counterfactual simulation of a suggestion")
    p_sim.add_argument("--rule-id", type=int, required=True)
    p_sim.add_argument("--start")
    p_sim.add_argument("--end")
    p_sim.add_argument("--json", action="store_true")
    p_sim.set_defaults(func=cmd_feedback_simulate)

    p_dash = sub.add_parser("dashboard", help="launch the local web dashboard")
    p_dash.add_argument("--port", type=int, default=8787)
    p_dash.add_argument("--host", default="127.0.0.1")
    p_dash.add_argument("--no-browser", action="store_true",
                        help="don't auto-open a browser window")
    p_dash.add_argument("--no-crawl", action="store_true",
                        help="serve read-only: no auto-crawl on start, no "
                             "'run collectors now' button (overrides config)")
    p_dash.add_argument("--allow-review-writes", action="store_true",
                        help="M4.5 QC activation: authorize ONLY the "
                             "alert-review POST path (loopback still enforced; "
                             "default off)")
    p_dash.set_defaults(func=cmd_dashboard)

    p_outbox = sub.add_parser("outbox", help="notification outbox status")
    p_outbox.add_argument("--suppress-pending", action="store_true",
                          help="mark all pending notifications suppressed (won't send)")
    p_outbox.set_defaults(func=cmd_outbox)

    p_test = sub.add_parser("test-notify", help="send a sample embed to the Discord webhook")
    p_test.add_argument("--webhook", help="override webhook URL (else env var)")
    p_test.set_defaults(func=cmd_test_notify)

    p_probe = sub.add_parser("probe", help="fingerprint a storefront platform")
    p_probe.add_argument("url")
    p_probe.add_argument("--json", action="store_true", help="also print the full result as JSON")
    p_probe.set_defaults(func=cmd_probe)

    p_sanitize = sub.add_parser("sanitize-har",
                                help="strip cookies/auth/tokens from an owner-captured HAR export")
    p_sanitize.add_argument("file", help="path to the .har file to sanitize")
    p_sanitize.add_argument("--out", help="output path (default: <file>.sanitized.har)")
    p_sanitize.set_defaults(func=cmd_sanitize_har)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

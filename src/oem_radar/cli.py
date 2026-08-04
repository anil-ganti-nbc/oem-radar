"""oem-radar CLI: validate | run | status | probe."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from .core.config import (
    ConfigError,
    RadarConfig,
    load_oem_configs,
    load_radar_config,
    parse_interval,
)
from .core.knownhw import SEED_COMPONENTS
from .core.registry import engines, notifiers, stores

# Imports for side effect: registry registration.
from . import providers  # noqa: F401
from .engines import dell  # noqa: F401
from .engines import shopify  # noqa: F401
from .providers import discord as _discord  # noqa: F401
from .providers import sqlite as _sqlite  # noqa: F401



def _apply_path_overrides(radar: RadarConfig) -> RadarConfig:
    """Resolve db/raw/log paths via paths.resolve_data_path (Stage 1.1).

    Mutates a copy-friendly model by re-validating with resolved absolute paths
    when OEM_RADAR_DATA_DIR is set or when relative paths need anchoring to cwd.
    """
    from .paths import resolve_data_path
    updates: dict = {
        "db_path": str(resolve_data_path(radar.db_path)),
        "raw_dir": str(resolve_data_path(radar.raw_dir)),
    }
    log_file = radar.logging.get("file") if radar.logging else None
    if log_file:
        new_logging = dict(radar.logging)
        new_logging["file"] = str(resolve_data_path(str(log_file)))
        updates["logging"] = new_logging
    return radar.model_copy(update=updates)

def _load(config_dir: Path) -> tuple[RadarConfig, dict]:
    radar = load_radar_config(config_dir / "radar.yaml")
    radar = _apply_path_overrides(radar)
    oems = load_oem_configs(config_dir / "oems")
    return radar, oems


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


def _resolve_webhook(radar: RadarConfig, config_dir: Path) -> tuple[str | None, int, str]:
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


def _build_fetcher(cfg: RadarConfig):
    from .core.fetch import HttpFetcher
    rl = cfg.rate_limit
    delay = rl.get("per_domain_delay", ["3s", "9s"])
    return HttpFetcher(
        cache_dir=Path(cfg.db_path).parent / "http_cache" if cfg.db_path != ":memory:" else None,
        delay_range=(float(parse_interval(delay[0])), float(parse_interval(delay[1]))),
        backoff_base=float(rl.get("backoff_base", 2)),
        backoff_max=float(parse_interval(rl.get("backoff_max", "300s"))),
        max_retries=int(rl.get("max_retries", 4)),
    )


def cmd_run(args: argparse.Namespace) -> int:
    from .core.runner import run_all

    radar, oems = _load(Path(args.config))
    _setup_logging(radar)

    if args.dry_run:
        store = stores.get(radar.store)(":memory:", radar.raw_dir)
        notifier = notifiers.get("console")()
        print("dry run: in-memory store, console notifications, nothing persisted")
    else:
        store = stores.get(radar.store)(radar.db_path, radar.raw_dir)
        webhook, min_sev, wh_src = _resolve_webhook(radar, Path(args.config))
        if webhook is None:
            print("WARNING: no Discord webhook found — notifications will queue "
                  "as pending and NOT send.\n  Fix: run via start-radar.cmd, or put "
                  "your webhook URL in config/discord_webhook.txt", file=sys.stderr)
        notifier = notifiers.get(radar.notifier)(store, webhook, min_sev)

    store.seed_components(SEED_COMPONENTS)
    stats = run_all(radar, oems, store, notifier, _build_fetcher(radar),
                    force=args.force, only_source=args.source)
    total_events = sum(s.events for s in stats)
    total_snaps = sum(s.snapshots_written for s in stats)
    print(f"done: {len(stats)} source(s) crawled, {total_snaps} snapshot(s), "
          f"{total_events} event(s)")
    if not args.dry_run:
        pending = store.db.execute(
            "SELECT COUNT(*) c FROM notifications WHERE status='pending'").fetchone()["c"]
        if pending:
            print(f"note: {pending} notification(s) still pending in the outbox "
                  f"(webhook source: {wh_src})")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    radar, _ = _load(Path(args.config))
    store = stores.get(radar.store)(radar.db_path, radar.raw_dir)
    rows = store.recent_runs(20)
    if not rows:
        print("no runs recorded yet")
        return 0
    print(f"{'source':<24} {'started':<21} {'status':<7} stats")
    for r in rows:
        print(f"{r['source_key']:<24} {r['started_at'][:19]:<21} {r['status']:<7} "
              f"{r['stats_json']}")
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    radar, _ = _load(Path(args.config)) if Path(args.config, "radar.yaml").exists() \
        else (RadarConfig(), {})
    fetcher = _build_fetcher(radar)
    base = args.url.rstrip("/")
    verdict = "unknown"
    try:
        doc = fetcher.get(f"{base}/products.json?limit=1")
        if doc.body.lstrip().startswith("{") and "products" in doc.body[:200]:
            verdict = "shopify"
    except Exception:
        pass
    if verdict == "unknown":
        try:
            doc = fetcher.get(base)
            body = doc.body.lower()
            if "woocommerce" in body or "/wp-content/" in body:
                verdict = "woocommerce"
            elif "cdn.shopify.com" in body:
                verdict = "shopify"
        except Exception as exc:
            print(f"probe failed: {exc}", file=sys.stderr)
            return 1
    print(f"{base}: {verdict}")
    return 0


def cmd_dashboard(args: argparse.Namespace) -> int:
    from pathlib import Path as _P

    from .dashboard import serve

    radar, _ = _load(_P(args.config))
    if not _P(radar.db_path).exists():
        print(f"no database at {radar.db_path} yet — run a crawl first "
              "(oem-radar run)", file=sys.stderr)
        return 1
    serve(radar.db_path, host=args.host, port=args.port,
          open_browser=(not args.no_browser and os.environ.get("OEM_RADAR_OPEN_BROWSER", "1") != "0"))
    return 0


def cmd_outbox(args: argparse.Namespace) -> int:
    """Inspect the notification outbox; optionally suppress everything pending."""
    radar, _ = _load(Path(args.config))
    store = stores.get(radar.store)(radar.db_path, radar.raw_dir)
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




def cmd_version(args: argparse.Namespace) -> int:
    """Report package and runtime contract versions (Stage 1)."""
    from .runtime_bridge import get_version_info
    info = get_version_info()
    print(json.dumps(info, indent=2))
    return 0


def cmd_identity(args: argparse.Namespace) -> int:
    """Emit runtime identity contract payload (Stage 1)."""
    from .runtime_bridge import as_jsonable, get_identity
    identity = get_identity(Path(args.config))
    print(json.dumps(as_jsonable(identity), indent=2))
    return 0


def cmd_health(args: argparse.Namespace) -> int:
    """Emit health contract payload without running collectors (Stage 1)."""
    from .runtime_bridge import as_jsonable, get_health
    health = get_health(Path(args.config))
    print(json.dumps(as_jsonable(health), indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="oem-radar", description="OEM product intelligence")
    parser.add_argument("--config", default="config", help="config directory (default: config)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("validate", help="validate configuration offline").set_defaults(func=cmd_validate)

    p_run = sub.add_parser("run", help="one-shot crawl of all due sources")
    p_run.add_argument("--dry-run", action="store_true", help="no persistence, console output")
    p_run.add_argument("--force", action="store_true", help="ignore min_interval")
    p_run.add_argument("--source", help="crawl only this source id")
    p_run.set_defaults(func=cmd_run)

    sub.add_parser("status", help="recent run telemetry").set_defaults(func=cmd_status)

    p_dash = sub.add_parser("dashboard", help="launch the local web dashboard")
    p_dash.add_argument("--port", type=int, default=8787)
    p_dash.add_argument("--host", default="127.0.0.1")
    p_dash.add_argument("--no-browser", action="store_true",
                        help="don't auto-open a browser window")
    p_dash.set_defaults(func=cmd_dashboard)

    p_outbox = sub.add_parser("outbox", help="notification outbox status")
    p_outbox.add_argument("--suppress-pending", action="store_true",
                          help="mark all pending notifications suppressed (won't send)")
    p_outbox.set_defaults(func=cmd_outbox)

    p_test = sub.add_parser("test-notify", help="send a sample embed to the Discord webhook")
    p_test.add_argument("--webhook", help="override webhook URL (else env var)")
    p_test.set_defaults(func=cmd_test_notify)

    sub.add_parser("version", help="package and contract versions (Stage 1)").set_defaults(func=cmd_version)
    sub.add_parser("identity", help="runtime identity payload (Stage 1)").set_defaults(func=cmd_identity)
    sub.add_parser("health", help="health payload without crawling (Stage 1)").set_defaults(func=cmd_health)

    p_probe = sub.add_parser("probe", help="fingerprint a storefront platform")
    p_probe.add_argument("url")
    p_probe.set_defaults(func=cmd_probe)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

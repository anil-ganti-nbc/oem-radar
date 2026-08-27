"""OEM Radar dashboard launcher — the source for OEM Radar Dashboard.exe.

Double-click entry point: opens the local review dashboard in your
default browser. No arguments, no console flags to remember. Bundled
into a standalone .exe with PyInstaller (`build_dashboard_exe.cmd`) so it
runs without a separate Python install.

Opening this window never starts a crawl by itself (fleet policy, Fleet
Law 5) — `dashboard.auto_crawl_on_start` is not wired to anything on this
path at all, regardless of what it's set to in `config/radar.yaml`. What
you get instead is a "Run collectors now" button on the page: a human
click, same authority as typing `oem-radar run` in a terminal, gated by
`dashboard.allow_manual_crawl` (on by default; `--no-crawl`-equivalent is
setting that to false). It runs the same code path as `oem-radar run`
(`core.crawl_service`), so it also sends Discord notifications exactly as
a scheduled crawl would — same as running the CLI by hand. Crawls started
this way are never forced; every source's own `min_interval` still
applies. Collectors whose normal runtime exceeds 5 minutes are excluded
from that button's "run everything" sweep and only run individually (see
`SourceConfig.heavy`); this is built and enforced by
`core.crawl_service.CrawlController`/`core.runner.run_all`, this file only
decides whether the button exists at all.

Uses `cli.build_dashboard_crawl_kwargs` — the exact function `oem-radar
dashboard` uses — so this launcher can never drift from that decision the
way it once did (see Fleet audit 2026-08-27: this file used to build its
own crawl kwargs from `auto_crawl_on_start` directly and always
constructed a controller, which made `serve()`'s auto_crawl/crawl guard
raise on every launch and crash before the browser ever opened).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# When frozen by PyInstaller, everything is unpacked next to the exe
# (see build_dashboard_exe.cmd's --add-data); when run as a plain script,
# resolve relative to this file so it works from any working directory.
if getattr(sys, "frozen", False):
    ROOT = Path(sys.executable).resolve().parent
else:
    ROOT = Path(__file__).resolve().parent
    sys.path.insert(0, str(ROOT / "src"))

CONFIG_DIR = ROOT / "config"


def main() -> int:
    from oem_radar.core.config import load_oem_configs, load_radar_config
    from oem_radar.dashboard import serve

    # Every path in radar.yaml (db_path, raw_dir, run_lock_path, the HTTP
    # cache) is relative to the project root, because that is where
    # start-radar.cmd runs `oem-radar run` from. A double-clicked .exe
    # inherits whatever directory Explorer felt like, so anchor it here —
    # otherwise a dashboard-triggered crawl would write its lock file and
    # its cache somewhere else than the scheduled one does.
    os.chdir(ROOT)

    radar = load_radar_config(CONFIG_DIR / "radar.yaml")
    db_path = radar.db_path
    if not Path(db_path).is_absolute():
        db_path = str(ROOT / db_path)

    if not Path(db_path).exists():
        print(f"No database found at {db_path} yet.")
        print("Run a crawl first (start-radar.cmd, or: oem-radar run), then try again.")
        input("Press Enter to close this window...")
        return 1

    fb = radar.feedback
    raw_dir = radar.raw_dir
    if raw_dir and not Path(raw_dir).is_absolute():
        raw_dir = str(ROOT / raw_dir)

    # Same one-writer registry sync `oem-radar dashboard` does, so the
    # manufacturer filter lists every configured OEM — not only the ones a
    # crawl happened to touch. Best-effort: never blocks the window opening.
    try:
        from oem_radar.core.runner import sync_oem_registry
        from oem_radar.providers.sqlite import SqliteStore

        store = SqliteStore(db_path, raw_dir or str(Path(db_path).parent / "raw"))
        try:
            sync_oem_registry(store, load_oem_configs(CONFIG_DIR / "oems"))
        finally:
            store.close()
    except Exception as exc:  # noqa: BLE001
        print(f"note: OEM registry sync skipped ({exc}); "
              "the manufacturer filter may be incomplete")

    # The crawl trigger. Built via the same helper `oem-radar dashboard`
    # uses (cli.build_dashboard_crawl_kwargs) so this launcher is a second
    # *caller*, never a second, drifting *implementation* of the decision
    # of whether/how the dashboard may crawl — that split is exactly what
    # broke this file once (see the module docstring's 2026-08-27 note).
    # auto_crawl is always False from that helper; only manual triggering
    # (dashboard.allow_manual_crawl) can be authorized here.
    crawl_kwargs = {"stale_after_hours": radar.dashboard.stale_after_hours}
    try:
        from oem_radar.cli import build_dashboard_crawl_kwargs

        crawl_kwargs = build_dashboard_crawl_kwargs(radar, CONFIG_DIR)
    except Exception as exc:  # noqa: BLE001 — never block the window opening
        print(f"note: crawl trigger unavailable ({exc}); dashboard is read-only "
              "this session")

    try:
        serve(db_path, open_browser=True, max_body=fb.max_review_request_bytes,
              raw_dir=raw_dir, **crawl_kwargs)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

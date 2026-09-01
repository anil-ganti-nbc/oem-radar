"""OEM Radar dashboard launcher — the source for OEM Radar Dashboard.exe.

Double-click entry point: opens the local review dashboard in your
default browser. No arguments, no console flags to remember. Bundled
into a standalone .exe with PyInstaller (`build_dashboard_exe.cmd`) so it
runs without a separate Python install.

Opening this window is treated as "show me current data": unless
`dashboard.auto_crawl_on_start` is false in `config/radar.yaml`, it kicks
off a crawl in the background before the browser opens, and the page
shows its progress live. The crawl is *not* forced — every source's own
`min_interval` still applies, so launching repeatedly costs nothing. The
"Run collectors now" button in the page triggers the same thing on
demand. Same code path as `oem-radar run` (`core.crawl_service`), which
means it also sends Discord notifications exactly as a scheduled crawl
would.
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
        from oem_radar.providers.sqlite import IncompatibleDatabaseError, SqliteStore

        store = SqliteStore(db_path, raw_dir or str(Path(db_path).parent / "raw"))
        try:
            sync_oem_registry(store, load_oem_configs(CONFIG_DIR / "oems"))
        finally:
            store.close()
    except IncompatibleDatabaseError as exc:
        # Never masked as a mere "sync skipped": the compatibility refusal
        # must name its gate. The dashboard's data surfaces refuse too.
        print(f"WARNING: OEM registry sync refused by the persistent-state "
              f"compatibility gate ({exc}); data views will refuse as well")
    except Exception as exc:  # noqa: BLE001
        print(f"note: OEM registry sync skipped ({exc}); "
              "the manufacturer filter may be incomplete")

    # The crawl trigger. Built here, not inside `serve`, for the same
    # reason the registry sync is: the entry point owns the config and
    # therefore the decision to reach out to the network.
    crawl_kwargs = {"stale_after_hours": radar.dashboard.stale_after_hours}
    try:
        from oem_radar.core.crawl_service import CrawlController

        crawl_kwargs |= {
            "crawl": CrawlController(CONFIG_DIR,
                                     allow_manual=radar.dashboard.allow_manual_crawl),
            "auto_crawl": radar.dashboard.auto_crawl_on_start,
            "auto_crawl_force": radar.dashboard.auto_crawl_force,
        }
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

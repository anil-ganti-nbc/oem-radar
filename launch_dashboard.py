"""OEM Radar dashboard launcher — the source for OEM Radar Dashboard.exe.

Double-click entry point: opens the local review dashboard in your
default browser. No arguments, no console flags to remember. Bundled
into a standalone .exe with PyInstaller (`build_dashboard_exe.cmd`) so it
runs without a separate Python install.

Opening this window is READ-ONLY. Phase 0 has no authenticated dashboard
mutation profile for *automatic* crawling, so `dashboard.serve` refuses
auto-crawl outright: opening this window starts no crawl, and no Discord
notification can be sent, merely by opening the dashboard.

Collection is an explicit operator action: this launcher authorizes the
GUI's "run collectors now" control, which calls the canonical
core.crawl_service.execute_crawl under the canonical run lock, against the
canonical database -- the same path the scheduled `oem-radar run` uses.
Nothing collects until that control is clicked.

Packaging note: config/ is bundled into the build and read back through
sys._MEIPASS, while the database, raw store, lock file and log stay
relative to the executable's own directory — a --onefile build does not
put those two roots in the same place.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Two different roots, which a --onefile build does NOT put in the same
# place — conflating them is why a frozen dashboard died looking for
# a config/radar.yaml that sat beside the exe rather than in the bundle:
#
#   RESOURCE_ROOT  read-only files baked into the build (config/). Under
#                  --onefile, PyInstaller extracts --add-data into a temp
#                  dir exposed as sys._MEIPASS, NOT next to the exe.
#   ROOT           the persistent project root that every relative path in
#                  radar.yaml (db_path, raw_dir, run_lock_path, the HTTP
#                  cache, the log) hangs off. That must be real, stable
#                  storage, so it stays the exe's own directory — never
#                  _MEIPASS, which is deleted on exit.
#
# build_dashboard_exe.cmd copies the built exe to the project root for
# exactly this reason: beside config/ and data/, the two roots coincide.
if getattr(sys, "frozen", False):
    ROOT = Path(sys.executable).resolve().parent
    RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", ROOT))
else:
    ROOT = Path(__file__).resolve().parent
    RESOURCE_ROOT = ROOT
    sys.path.insert(0, str(ROOT / "src"))

# Prefer bundled config, but let a real config/ beside the exe win, so an
# operator can still point a frozen build at edited local policy without
# rebuilding it.
CONFIG_DIR = ROOT / "config"
if not (CONFIG_DIR / "radar.yaml").exists():
    CONFIG_DIR = RESOURCE_ROOT / "config"


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

    # Defer to the same authority the CLI uses rather than re-deciding here:
    # build_dashboard_crawl_kwargs owns whether this process may crawl, and
    # builds the canonical CrawlController when it may.
    #
    # The desktop launcher is an operator sitting at the machine, so it opts
    # into explicit manual collection: the GUI gets a working "run collectors
    # now" control that calls the same core.crawl_service.execute_crawl the
    # scheduled `oem-radar run` uses, under the same run lock, against the
    # same database. Auto-crawl remains refused unconditionally inside
    # `serve`, so opening this window still never starts a crawl.
    from argparse import Namespace

    from oem_radar.cli import build_dashboard_crawl_kwargs

    crawl_kwargs = build_dashboard_crawl_kwargs(
        radar, CONFIG_DIR, Namespace(allow_manual_collection=True, no_crawl=False),
    )

    try:
        serve(db_path, open_browser=True, max_body=fb.max_review_request_bytes,
              raw_dir=raw_dir, **crawl_kwargs)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

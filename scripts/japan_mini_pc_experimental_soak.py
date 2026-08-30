"""Run the five approved Japan mini-PC probes in isolated local state.

No production source config, SnapshotStore, scheduler, dashboard, Discord, or
remote storage is touched.  Re-run this command to establish a delta after the
first quiet baseline.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from oem_radar.core.fetch import HttpFetcher
from oem_radar.experimental.japan_mini_pc import (
    ExperimentalJapanMiniStore,
    JapanMiniProbeCollector,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="isolated Japan mini-PC experimental soak")
    parser.add_argument("--db", type=Path, default=Path("data/experimental/japan-mini-pc.db"))
    parser.add_argument("--cache", type=Path, default=Path("data/experimental/japan-mini-pc-cache"))
    parser.add_argument("--include-catalogue", action="store_true",
                        help="download Epson's large PDF only for a manual catalogue checksum pass")
    args = parser.parse_args()
    args.db.parent.mkdir(parents=True, exist_ok=True)
    store = ExperimentalJapanMiniStore(str(args.db))
    try:
        fetcher = HttpFetcher(
            cache_dir=args.cache,
            user_agent="OEMRadar/2.0 (experimental Japan mini-PC probe)",
        )
        stats = JapanMiniProbeCollector(store, global_geekom_history_db=Path("data/radar.db")).run(fetcher, include_catalogue=getattr(args, "include_catalogue", False))
        inventory = [dict(row) for row in store.db.execute(
            "SELECT source, identity_key, model, platform, global_overlap, url "
            "FROM japan_mini_identities ORDER BY source, identity_key"
        )]
        candidates = [dict(row) for row in store.db.execute(
            "SELECT source, identity_key, model, platform, global_overlap, url "
            "FROM japan_mini_candidates ORDER BY id"
        )]
        print(json.dumps({
            **stats.__dict__, "fetch": fetcher.stats,
            "change_events": 0, "notifications": 0,
            "inventory": inventory, "candidates": candidates,
        }, ensure_ascii=False, indent=2, default=str))
        return 0 if not stats.failures else 1
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())

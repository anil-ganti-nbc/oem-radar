"""Manual/daily entry point for the isolated MousePro + GEEKOM JP soak."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from oem_radar.core.fetch import HttpFetcher
from oem_radar.experimental.japan_mini_pc_soak import JapanMiniPcSoak, JapanMiniPcSoakStore


def main() -> int:
    parser = argparse.ArgumentParser(description="isolated MousePro CR + GEEKOM JP five-day soak")
    parser.add_argument("--db", type=Path, default=Path("data/experimental/japan-mini-pc-five-day-soak.db"))
    parser.add_argument("--cache", type=Path, default=Path("data/experimental/japan-mini-pc-five-day-cache"))
    parser.add_argument("--global-history-db", type=Path, default=Path("data/radar.db"))
    args = parser.parse_args()
    store = JapanMiniPcSoakStore(str(args.db))
    try:
        fetcher = HttpFetcher(cache_dir=args.cache, user_agent="OEMRadar/2.0 (experimental Japan mini-PC five-day soak)")
        stats = JapanMiniPcSoak(store, args.global_history_db).run(fetcher)
        observations = [dict(row) for row in store.db.execute(
            "SELECT source,identity_key,classification,model,platform,source_url,first_seen_at "
            "FROM jp_mini_soak_observations ORDER BY id"
        )]
        print(json.dumps({**stats.__dict__, "observations": observations,
                          "change_events": 0, "notifications": 0}, ensure_ascii=False, indent=2))
        return 0 if not stats.failures else 1
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())

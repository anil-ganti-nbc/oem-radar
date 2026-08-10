"""Run one isolated Lenovo PSREF evidence-soak pass.

This is intentionally not wired into ``oem-radar run`` or the Windows task
scheduler.  Re-run it on a chosen cadence against its own SQLite database;
it has no notifier, no product pipeline, and no production configuration.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Runnable directly from a checkout without requiring an editable install.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from oem_radar.core.evidence_pipeline import run_evidence_source
from oem_radar.core.fetch import HttpFetcher
from oem_radar.evidence_sources.lenovo_psref import LenovoPsrefEvidenceSource
from oem_radar.providers.sqlite import SqliteStore


def main() -> int:
    parser = argparse.ArgumentParser(description="isolated PSREF experimental soak")
    parser.add_argument("--db", type=Path, default=Path("data/experimental/psref-soak.db"))
    parser.add_argument("--cache", type=Path, default=Path("data/experimental/psref-cache"))
    args = parser.parse_args()
    args.db.parent.mkdir(parents=True, exist_ok=True)
    store = SqliteStore(str(args.db), str(args.db.parent / "raw"))
    try:
        fetcher = HttpFetcher(cache_dir=args.cache, user_agent="OEMRadar/2.0 (experimental evidence soak)")
        stats = run_evidence_source("lenovo-psref", LenovoPsrefEvidenceSource(), fetcher, store)
        print(json.dumps({
            "source": stats.source_id, "discovered": stats.discovered,
            "new_items": stats.new_items, "updated_items": stats.updated_items,
            "unchanged_items": stats.unchanged_items, "errors": stats.errors,
            "candidates": [c.model_dump(mode="json") | {"dedup_key": c.dedup_key()} for c in stats.candidates],
            "candidate_count": len(stats.candidates),
            "product_alerts_written": store.db.execute("SELECT COUNT(*) FROM change_events").fetchone()[0],
            "notifications_written": store.db.execute("SELECT COUNT(*) FROM notifications").fetchone()[0],
        }, indent=2, default=str))
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

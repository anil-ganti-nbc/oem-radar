"""Run one isolated Lenovo regional sitemap delta pass; never production."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from oem_radar.core.fetch import HttpFetcher
from oem_radar.experimental.lenovo_sitemap_delta import ExperimentalSitemapStore, LenovoRegionalSitemapDeltaCollector

def main() -> int:
    p=argparse.ArgumentParser(description="isolated Lenovo regional sitemap soak")
    p.add_argument('--db',type=Path,default=Path('data/experimental/lenovo-sitemap-soak.db'))
    p.add_argument('--cache',type=Path,default=Path('data/experimental/lenovo-sitemap-cache'))
    a=p.parse_args(); a.db.parent.mkdir(parents=True,exist_ok=True)
    store=ExperimentalSitemapStore(str(a.db))
    try:
        fetcher=HttpFetcher(cache_dir=a.cache,user_agent='OEMRadar/2.0 (experimental sitemap soak)')
        s=LenovoRegionalSitemapDeltaCollector(store).run(fetcher)
        print(json.dumps({**s.__dict__, 'change_events':0, 'notifications':0},indent=2))
    finally: store.close()
    return 0
if __name__=='__main__': raise SystemExit(main())

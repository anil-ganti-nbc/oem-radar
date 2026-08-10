"""Task Scheduler entry point: append compact isolated-soak telemetry."""
from __future__ import annotations
import json, sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from oem_radar.core.fetch import HttpFetcher
from oem_radar.experimental.lenovo_sitemap_delta import ExperimentalSitemapStore, LenovoRegionalSitemapDeltaCollector
from oem_radar.experimental.asus_sitemap_delta import AsusRegionalSitemapDeltaCollector

ROOT=Path('data/experimental')
def run_one(oem, collector_cls, db_name):
    path=ROOT/db_name; store=ExperimentalSitemapStore(str(path))
    try:
        stats=collector_cls(store).run(HttpFetcher(cache_dir=ROOT/f'{oem.lower()}-sitemap-cache',user_agent='OEMRadar/2.0 (experimental sitemap soak)'))
        return {'oem':oem,'database_path':str(path),'status':'ok',**stats.__dict__}
    except Exception as exc:
        return {'oem':oem,'database_path':str(path),'status':'failed','failure_reason':repr(exc)}
    finally: store.close()
def main():
    ROOT.mkdir(parents=True,exist_ok=True); started=datetime.now(timezone.utc)
    rows=[run_one('Lenovo',LenovoRegionalSitemapDeltaCollector,'lenovo-sitemap-soak.db'),run_one('ASUS',AsusRegionalSitemapDeltaCollector,'asus-sitemap-soak.db')]
    record={'run_started':started.isoformat(),'run_ended':datetime.now(timezone.utc).isoformat(),'collectors':rows,'change_events':0,'notifications':0}
    with (ROOT/'soak-runs.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(record,sort_keys=True)+'\n')
    print(json.dumps(record,indent=2)); return 0
if __name__=='__main__': raise SystemExit(main())

from __future__ import annotations
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from oem_radar.core.fetch import HttpFetcher
from oem_radar.experimental.asus_sitemap_delta import AsusRegionalSitemapDeltaCollector
from oem_radar.experimental.lenovo_sitemap_delta import ExperimentalSitemapStore
def main():
 p=argparse.ArgumentParser(description='isolated ASUS regional sitemap soak');p.add_argument('--db',type=Path,default=Path('data/experimental/asus-sitemap-soak.db'));p.add_argument('--cache',type=Path,default=Path('data/experimental/asus-sitemap-cache'));a=p.parse_args();a.db.parent.mkdir(parents=True,exist_ok=True);s=ExperimentalSitemapStore(str(a.db))
 try:
  r=AsusRegionalSitemapDeltaCollector(s).run(HttpFetcher(cache_dir=a.cache,user_agent='OEMRadar/2.0 (experimental sitemap soak)'));print(json.dumps({**r.__dict__,'change_events':0,'notifications':0},indent=2))
 finally:s.close()
if __name__=='__main__':main()

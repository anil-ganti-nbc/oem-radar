from datetime import datetime, timezone
from pathlib import Path
from oem_radar.core.models import FetchedDocument
from oem_radar.experimental.lenovo_sitemap_delta import ExperimentalSitemapStore, LenovoRegion, LenovoRegionalSitemapDeltaCollector

REGIONS=(LenovoRegion('US','us-en','https://x/us.xml'),LenovoRegion('CA','ca-en','https://x/ca.xml'))
def sm(*urls): return '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+''.join(f'<url><loc>{u}</loc></url>' for u in urls)+'</urlset>'
def page(name,sku): return f'<link rel="canonical" href="https://www.lenovo.com/us/en/p/laptops/x/{sku}"/><script type="application/ld+json">{{"@type":"Product","name":"{name}","sku":"{sku}","offers":{{"price":"999","availability":"InStock"}}}}</script>'
class Fetch:
 def __init__(self,p): self.p=p; self.calls=[]
 def get(self,u): self.calls.append(u); return FetchedDocument(url=u,status=200,body=self.p[u])
def test_first_pass_baselines_without_fetching_product_pages(tmp_path):
 s=ExperimentalSitemapStore(str(tmp_path/'e.db')); f=Fetch({'https://x/us.xml':sm('https://www.lenovo.com/us/en/p/laptops/x/abc'),'https://x/ca.xml':sm()})
 r=LenovoRegionalSitemapDeltaCollector(s,REGIONS).run(f,datetime(2026,8,10,tzinfo=timezone.utc)); assert r.baseline_urls==1 and r.new_urls==0 and r.valid_candidates==0; assert f.calls==['https://x/us.xml','https://x/ca.xml']; s.close()
def test_delta_fetches_new_url_and_never_writes_product_alerts(tmp_path):
 s=ExperimentalSitemapStore(str(tmp_path/'e.db')); base={'https://x/us.xml':sm('https://www.lenovo.com/us/en/p/laptops/x/abc'),'https://x/ca.xml':sm()}; c=LenovoRegionalSitemapDeltaCollector(s,REGIONS); c.run(Fetch(base)); u='https://www.lenovo.com/us/en/p/laptops/x/newsku'; r=c.run(Fetch({'https://x/us.xml':sm(base['https://x/us.xml'].split('<loc>')[1].split('</loc>')[0],u),'https://x/ca.xml':sm(),'https://www.lenovo.com/us/en/p/laptops/x/newsku':page('ThinkPad New','NEWSKU')})); assert r.new_urls==1 and r.fetched_new_urls==1 and r.valid_candidates==1; assert s.db.execute('select candidate_type from regional_sitemap_candidates').fetchone()[0]=='new_model_from_regional_sitemap'; s.close()
def test_simultaneous_mirror_delta_emits_once(tmp_path):
 s=ExperimentalSitemapStore(str(tmp_path/'e.db')); c=LenovoRegionalSitemapDeltaCollector(s,REGIONS); c.run(Fetch({'https://x/us.xml':sm('https://www.lenovo.com/us/en/p/laptops/x/us-old'),'https://x/ca.xml':sm('https://www.lenovo.com/ca/en/p/laptops/x/ca-old')})); us='https://www.lenovo.com/us/en/p/laptops/x/shared'; ca='https://www.lenovo.com/ca/en/p/laptops/x/shared'; r=c.run(Fetch({'https://x/us.xml':sm('https://www.lenovo.com/us/en/p/laptops/x/us-old',us),'https://x/ca.xml':sm('https://www.lenovo.com/ca/en/p/laptops/x/ca-old',ca),us:page('Shared','SHARED'),ca:page('Shared','SHARED')})); assert r.valid_candidates==1 and r.mirror_duplicates_suppressed==1; s.close()
def test_later_sku_in_another_region_is_regional_page_appearance(tmp_path):
 s=ExperimentalSitemapStore(str(tmp_path/'e.db')); c=LenovoRegionalSitemapDeltaCollector(s,REGIONS); us='https://www.lenovo.com/us/en/p/laptops/x/us-old'; ca='https://www.lenovo.com/ca/en/p/laptops/x/ca-old'; c.run(Fetch({'https://x/us.xml':sm(us),'https://x/ca.xml':sm(ca)})); usn='https://www.lenovo.com/us/en/p/laptops/x/shared-us'; c.run(Fetch({'https://x/us.xml':sm(us,usn),'https://x/ca.xml':sm(ca),usn:page('Shared','SHARED')})); can='https://www.lenovo.com/ca/en/p/laptops/x/shared-ca'; c.run(Fetch({'https://x/us.xml':sm(us,usn),'https://x/ca.xml':sm(ca,can),can:page('Shared','SHARED')})); assert s.db.execute("select candidate_type from regional_sitemap_candidates where region='CA'").fetchone()[0]=='regional_page_appearance'; s.close()
def test_partial_sitemap_fails_without_replacing_baseline(tmp_path):
 s=ExperimentalSitemapStore(str(tmp_path/'e.db')); c=LenovoRegionalSitemapDeltaCollector(s,(REGIONS[0],)); urls=[f'https://www.lenovo.com/us/en/p/laptops/x/{i}' for i in range(10)]; c.run(Fetch({'https://x/us.xml':sm(*urls)})); r=c.run(Fetch({'https://x/us.xml':sm('https://www.lenovo.com/us/en/p/laptops/x/0')})); assert r.failures and s.previous_count('US')==10; s.close()

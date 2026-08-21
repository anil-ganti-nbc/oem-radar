from oem_radar.core.models import FetchedDocument
from oem_radar.experimental.asus_sitemap_delta import asus_product_urls, extract_asus_identity, AsusRegionalSitemapDeltaCollector
from oem_radar.experimental.lenovo_sitemap_delta import ExperimentalSitemapStore, LenovoRegion

def sm(*u): return '<urlset>'+''.join(f'<url><loc>{x}</loc></url>' for x in u)+'</urlset>'
def pg(name,sku): return f'<link rel="canonical" href="https://www.asus.com/laptops/x/{sku}/"><meta property="og:title" content="{name}｜ASUS"><h1>{name}</h1><script>var x={{"sku": "{sku}"}}</script>'
def test_product_filter_includes_laptops_and_mini_pc_but_not_support_or_review():
 urls=asus_product_urls(sm('https://www.asus.com/laptops/x/a/','https://www.asus.com/laptops/x/a/review/','https://www.asus.com/motherboards/x/','https://www.asus.com/mini-pcs/x/b/','https://www.asus.com/in/laptops/x/c/techspec/'))
 assert urls=={'https://www.asus.com/laptops/x/a','https://www.asus.com/mini-pcs/x/b'}
def test_identity_prefers_embedded_sku_over_locale_url():
 f=extract_asus_identity(pg('Vivobook Pro 16 H465','H465-001'),'https://www.asus.com/in/laptops/x/')
 assert f['identity_key']=='asus-sku:h465-001' and f['confidence']=='high'
def test_baseline_then_locale_mirror_delta_emits_one(tmp_path):
 regs=(LenovoRegion('GLOBAL','global','https://x/g'),LenovoRegion('IN','in','https://x/i'))
 class F:
  def __init__(self,p):self.p=p
  def get(self,u):return FetchedDocument(url=u,status=200,body=self.p[u.rstrip('/')])
 s=ExperimentalSitemapStore(str(tmp_path/'x.db')); c=AsusRegionalSitemapDeltaCollector(s,regs)
 c.run(F({'https://x/g':sm('https://www.asus.com/laptops/x/old/'),'https://x/i':sm('https://www.asus.com/in/laptops/x/old/')})); g='https://www.asus.com/laptops/x/new/'; i='https://www.asus.com/in/laptops/x/new/'; r=c.run(F({'https://x/g':sm('https://www.asus.com/laptops/x/old/',g),'https://x/i':sm('https://www.asus.com/in/laptops/x/old/',i),g.rstrip('/'):pg('Vivobook Pro 16 H465','H465'),i.rstrip('/'):pg('Vivobook Pro 16 H465','H465')})); assert r.valid_candidates==1 and r.mirror_duplicates_suppressed==1; s.close()

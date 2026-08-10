"""Bounded ASUS regional sitemap delta experiment (global, China, India)."""
from __future__ import annotations
import re
from datetime import datetime, timezone
from dataclasses import dataclass
from .lenovo_sitemap_delta import (DeltaStats, ExperimentalSitemapStore, LenovoRegion,
    normalize_url, url_identity)

ASUS_REGIONS=(
 LenovoRegion('GLOBAL','global','https://www.asus.com/sitemap/global1.xml'),
 LenovoRegion('CN','cn','https://www.asus.com.cn/sitemap/cn1.xml'),
 LenovoRegion('IN','in','https://www.asus.com/in/sitemap/in1.xml'),
)
_LOC=re.compile(r'<loc>(.*?)</loc>',re.I|re.S)
_INCLUDE=re.compile(r'/(?:laptops|notebooks|mini-pc(?:s)?|desktops)/',re.I)
_EXCLUDE=re.compile(r'/(?:review|techspec|where-to-buy|support|news|blog)(?:/|$)',re.I)
_CANON=re.compile(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)',re.I)
_OG=re.compile(r'<meta[^>]+(?:property|name)=["\']og:title["\'][^>]+content=["\']([^"\']+)',re.I)
_H1=re.compile(r'<h1[^>]*>(.*?)</h1>',re.I|re.S)
_SKU=re.compile(r'["\']sku["\']\s*:\s*["\']?([A-Za-z0-9_-]+)',re.I)
_TAGS=re.compile(r'<[^>]+>')

def asus_product_urls(xml:str)->set[str]:
    return {normalize_url(x.strip()) for x in _LOC.findall(xml)
            if _INCLUDE.search(x) and not _EXCLUDE.search(x)}

def extract_asus_identity(html:str,url:str)->dict|None:
    canonical=_CANON.search(html); og=_OG.search(html); h1=_H1.search(html); sku=_SKU.search(html)
    model=(h1.group(1) if h1 else (og.group(1) if og else None))
    model=_TAGS.sub('',model).strip() if model else None
    if not model: return None
    code=sku.group(1) if sku else None
    return {'model':model,'sku':code,'canonical_url':normalize_url(canonical.group(1) if canonical else url),
      'identity_key':'asus-sku:'+code.lower() if code else 'asus-model:'+re.sub(r'[^a-z0-9]+','-',model.lower()).strip('-'),
      'confidence':'high' if code else 'medium','price':None,'availability':None}

class AsusRegionalSitemapDeltaCollector:
    def __init__(self,store:ExperimentalSitemapStore,regions=ASUS_REGIONS,minimum_fraction=.35): self.store,self.regions,self.minimum_fraction=store,tuple(regions),minimum_fraction
    def run(self,fetcher,now:datetime|None=None)->DeltaStats:
        now=now or datetime.now(timezone.utc); stamp=now.isoformat(); stats=DeltaStats(); emitted=set()
        for region in self.regions:
            stats.regions_polled+=1
            try:
                urls=asus_product_urls(fetcher.get(region.sitemap_url).body); prev=self.store.previous_count(region.code)
                if not urls or (prev and len(urls)/prev<self.minimum_fraction): raise ValueError(f'unsafe sitemap count {len(urls)} (previous={prev})')
                new=urls-self.store.known_urls(region.code)
                if prev is None:
                    stats.baseline_urls+=len(urls); self.store.save_success(region.code,urls,[],stamp); continue
                candidates=[]
                for url in sorted(new):
                    stats.new_urls+=1; doc=fetcher.get(url); stats.fetched_new_urls+=1; facts=extract_asus_identity(doc.body,url)
                    if not facts: continue
                    identity=facts['identity_key']
                    if identity in emitted: stats.mirror_duplicates_suppressed+=1; continue
                    elsewhere=self.store.identity_seen_elsewhere(identity,region.code)
                    candidates.append({**facts,'region':region.code,'url':url,'candidate_type':'regional_page_appearance' if elsewhere else 'new_model_from_regional_sitemap','reason':'official_asus_sitemap_url_delta'})
                    emitted.add(identity); stats.valid_candidates+=1
                self.store.save_success(region.code,urls,candidates,stamp)
            except Exception as exc:
                stats.failures.append(f'{region.code}: {exc!r}'); self.store.save_failure(region.code,stamp,str(exc))
        return stats

"""Community evidence; collection runs under the native crawl lock."""
from __future__ import annotations
import json
from datetime import datetime
from clank_reddit import Submission, retrieve
from pydantic import BaseModel
from ...core.evidence_pipeline import run_evidence_source
from ...core.models import EvidenceDocument, EvidenceItem, EvidenceKind, EvidenceProvenance, EvidenceRef
from ...core.registry import evidence_sources

COMMUNITIES = ("GamingLaptops", "MiniPCs")

class CommunityEvidenceItem(EvidenceItem):
    def content_hash(self):
        import hashlib
        basis = super().content_hash() + json.dumps(self.raw_data.get("outbound_links", []))
        return hashlib.sha256(basis.encode()).hexdigest()

class RedditConfig(BaseModel):
    subreddit: str

@evidence_sources.register("reddit_community")
class RedditEvidenceSource:
    config_schema = RedditConfig
    def __init__(self, subreddit, *, run_id, code_revision, baseline):
        if subreddit not in COMMUNITIES:
            raise ValueError("Community outside OEM Radar admission scope")
        self.subreddit = subreddit
        self.source_id = f"reddit-{subreddit.lower()}"
        self.context = {"run_id": run_id, "code_revision": code_revision,
                        "observation_mode": "baseline" if baseline else "live",
                        "delivery": "blocked", "novelty": "unconfirmed"}

    def discover(self, fetcher):
        def get(url):
            doc = fetcher.get(url)
            return doc.status, doc.body
        return [EvidenceRef(external_id=p.external_id, url=p.permalink,
                            inline_payload=vars(p)) for p in retrieve(self.subreddit, get)]

    def fetch(self, ref, fetcher):
        return EvidenceDocument(url=ref.url, status=200, body=json.dumps(ref.inline_payload),
                                content_type="application/json")

    def extract(self, doc):
        p = Submission(**json.loads(doc.body))
        return [CommunityEvidenceItem(
            manufacturer="UNKNOWN", source_id=self.source_id,
            evidence_kind=EvidenceKind.OTHER, provenance=EvidenceProvenance.COMMUNITY_REPORT,
            canonical_url=p.permalink, external_id=p.external_id,
            title=p.title, description=p.body, confidence=0.0,
            published_at=datetime.fromisoformat(p.published_at) if p.published_at else None,
            raw_data=p.evidence() | self.context)]

def collect_community(subreddit, fetcher, store, *, code_revision="UNKNOWN"):
    """Reuse evidence_items/events and crawler_runs; never create product alerts."""
    if subreddit not in COMMUNITIES:
        raise ValueError("Community outside OEM Radar admission scope")
    source_id = f"reddit-{subreddit.lower()}"
    baseline = not store.has_completed_run(source_id)
    run_id = store.run_started(source_id)
    try:
        source = RedditEvidenceSource(subreddit, run_id=run_id,
                                      code_revision=code_revision, baseline=baseline)
        stats = run_evidence_source(source_id, source, fetcher, store)
        store.run_finished(run_id, "failed" if stats.errors else "ok", {
            "discovered": stats.discovered, "new_items": stats.new_items,
            "updated_items": stats.updated_items, "unchanged_items": stats.unchanged_items,
            "baseline": baseline, "delivery": "blocked", "code_revision": code_revision,
            "collection_health": "failed" if stats.errors else "ok",
            "pipeline_health": "failed" if stats.errors else "ok"}, stats.errors)
        return stats
    except Exception as exc:
        store.run_finished(run_id, "failed", {"baseline": baseline, "delivery": "blocked"},
                           [repr(exc)])
        raise

from xml.sax.saxutils import escape

def listing(community="GamingLaptops", ids=("a1",), title="New game sequel reportedly leaked", target="https://example.com/story?utm_source=reddit"):
    entries = []
    for eid in ids:
        link = f"https://www.reddit.com/r/{community}/comments/{eid}/story/"
        body = escape(f'<a href="{target}">[link]</a>')
        entries.append(f'<entry><id>t3_{eid}</id><title>{escape(title)}</title>'
                       f'<link href="{link}"/><published>2026-09-07T12:00:00Z</published>'
                       f'<content type="html">{body}</content></entry>')
    return '<feed xmlns="http://www.w3.org/2005/Atom">'+''.join(entries)+'</feed>'

import json
import pytest
from clank_reddit import RedditUnavailable, parse_listing, retrieve, link_key
from oem_radar.core.models import FetchedDocument
from oem_radar.evidence_sources.reddit import collect_community
from oem_radar.providers.sqlite import SqliteStore

@pytest.mark.parametrize("status", [301, 403, 429, 500])
def test_http_failures_are_not_empty_success(status):
    with pytest.raises(RedditUnavailable):
        retrieve("GamingLaptops", lambda _: (status, listing()))

@pytest.mark.parametrize("body", ['<html>blocked</html>', '<broken', '<feed xmlns="http://www.w3.org/2005/Atom"/>'])
def test_malformed_and_empty_fail(body):
    with pytest.raises(RedditUnavailable):
        parse_listing(body, "GamingLaptops")

def test_duplicate_ids_and_same_article_keep_distinct_observations():
    posts = parse_listing(listing(ids=("a1", "a1", "a2")), "GamingLaptops")
    assert len(posts) == 2
    assert posts[0].related_urls == posts[1].related_urls
    assert posts[0].external_id != posts[1].external_id
    assert posts[0].published_at == "2026-09-07T12:00:00+00:00"
    assert posts[0].evidence()["original_source_url"] is None
    assert link_key("https://example.com/x?id=1") != link_key("https://example.com/x?id=2")

def test_deleted_and_incomplete_entries_fail_soft_when_listing_has_valid_evidence():
    deleted = listing(ids=("gone",), title="[deleted]")
    incomplete = listing(ids=("blank",), title="")
    valid = listing(ids=("kept",), title="A real community observation")
    body = deleted.replace("</feed>", "") + incomplete.removeprefix(
        '<feed xmlns="http://www.w3.org/2005/Atom">'
    ).replace("</feed>", "") + valid.removeprefix(
        '<feed xmlns="http://www.w3.org/2005/Atom">'
    )
    posts = parse_listing(body, "GamingLaptops")
    assert [post.external_id for post in posts] == ["t3_kept"]

def test_listing_with_only_deleted_entries_is_not_a_healthy_empty_run():
    with pytest.raises(RedditUnavailable, match="no usable submissions"):
        parse_listing(listing(ids=("gone",), title="[removed]"), "GamingLaptops")

class Fetcher:
    def __init__(self, body): self.body = body
    def get(self, url): return FetchedDocument(url=url, status=200, body=self.body)

def test_baseline_restart_and_link_edits_never_create_market_novelty(tmp_path):
    path = str(tmp_path / "radar.db")
    store = SqliteStore(path, str(tmp_path / "raw"))
    first = collect_community("GamingLaptops", Fetcher(listing()), store)
    assert first.new_items == 1 and first.candidates == []
    assert store.db.execute("select count(*) from change_events").fetchone()[0] == 0
    store.close()
    store = SqliteStore(path, str(tmp_path / "raw"))
    repeat = collect_community("GamingLaptops", Fetcher(listing()), store)
    assert repeat.unchanged_items == 1 and repeat.events == 0
    changed = collect_community("GamingLaptops", Fetcher(listing(target="https://example.com/correction")), store)
    assert changed.updated_items == 1
    raw = json.loads(store.db.execute("select raw_data_json from evidence_items").fetchone()[0])
    assert raw["observation_mode"] == "baseline"
    assert raw["revision_history"][0]["outbound_links"] == ["https://example.com/story?utm_source=reddit"]
    assert raw["delivery"] == "blocked"
    store.close()

def test_failed_first_intake_does_not_complete_baseline(tmp_path):
    store = SqliteStore(str(tmp_path / "radar.db"), str(tmp_path / "raw"))
    stats = collect_community("GamingLaptops", Fetcher("<html>blocked</html>"), store)
    assert stats.errors and not store.has_completed_run("reddit-gaminglaptops")
    store.close()


def test_runner_explicit_opt_in_and_routine_scope(tmp_path):
    from oem_radar.core.config import RadarConfig
    from oem_radar.core.runner import run_all
    class CommunityFetcher:
        def get(self, url):
            community = "MiniPCs" if "/MiniPCs/" in url else "GamingLaptops"
            return FetchedDocument(url=url, status=200, body=listing(community))
    class Notifier:
        def enqueue(self, *args): raise AssertionError("Community evidence became an alert")
        def drain(self): return 0
    store = SqliteStore(str(tmp_path / "radar.db"), str(tmp_path / "raw"))
    assert run_all(RadarConfig(), {}, store, Notifier(), CommunityFetcher()) == []
    stats = run_all(RadarConfig(reddit_discovery_enabled=True), {}, store, Notifier(),
                    CommunityFetcher(), routine_scope=True)
    assert len(stats) == 2 and all(s.events == 0 for s in stats)
    assert run_all(RadarConfig(reddit_discovery_enabled=True), {}, store, Notifier(),
                   CommunityFetcher(), routine_scope=True) == []
    store.close()

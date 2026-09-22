"""Hourly Reddit rotation derived from crawler_runs, not a second scheduler."""
import json
from pathlib import Path
from xml.sax.saxutils import escape

from oem_radar.core.config import ManufacturerConfig, OemConfig, RadarConfig, SourceConfig
from oem_radar.core.knownhw import SEED_COMPONENTS
from oem_radar.core.models import FetchedDocument
from oem_radar.core.runner import run_all
from oem_radar.engines import shopify  # noqa: F401
from oem_radar.evidence_sources.reddit import next_hourly_community
from oem_radar.providers.discord import DiscordNotifier
from oem_radar.providers.sqlite import SqliteStore

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "shopify" / "gmktec_products.json")
    .read_text(encoding="utf-8")
)
BASE = "https://www.gmktec.com"


def listing(community="GamingLaptops", ids=("a1",)):
    entries = []
    for eid in ids:
        link = f"https://www.reddit.com/r/{community}/comments/{eid}/story/"
        body = escape('<a href="https://example.com/story">[link]</a>')
        entries.append(
            f"<entry><id>t3_{eid}</id><title>New game sequel reportedly leaked</title>"
            f'<link href="{link}"/><published>2026-09-07T12:00:00Z</published>'
            f'<content type="html">{body}</content></entry>'
        )
    return '<feed xmlns="http://www.w3.org/2005/Atom">' + "".join(entries) + "</feed>"


def test_rotation_is_deterministic_and_starts_with_gaminglaptops():
    assert next_hourly_community(None, ["MiniPCs", "GamingLaptops"]) == "GamingLaptops"
    assert next_hourly_community("reddit-gaminglaptops", ["MiniPCs", "GamingLaptops"]) == "MiniPCs"
    assert next_hourly_community("reddit-minipcs", ["GamingLaptops", "MiniPCs"]) == "GamingLaptops"
    assert next_hourly_community("reddit-minipcs", ["MiniPCs"]) == "MiniPCs"


class Feed:
    def __init__(self, *, fail_minipcs=False):
        self.fail_minipcs = fail_minipcs
        self.urls = []

    def get(self, url):
        self.urls.append(url)
        if url.startswith(f"{BASE}/products.json?limit=250&page=1"):
            return FetchedDocument(url=url, status=200, body=json.dumps(FIXTURE))
        if url.startswith(f"{BASE}/products.json"):
            return FetchedDocument(url=url, status=200, body=json.dumps({"products": []}))
        if self.fail_minipcs and "/r/MiniPCs/" in url:
            return FetchedDocument(url=url, status=429, body="slow down")
        community = "MiniPCs" if "/r/MiniPCs/" in url else "GamingLaptops"
        return FetchedDocument(url=url, status=200, body=listing(community))


def _notifier(store):
    sent = []
    notifier = DiscordNotifier(
        store, "https://hook.example", 3,
        sender=lambda u, p: (sent.append(p), None) and (True, None),
    )
    return notifier, sent


def _open(tmp_path):
    radar = RadarConfig(
        db_path=str(tmp_path / "radar.db"),
        raw_dir=str(tmp_path / "raw"),
        reddit_discovery_enabled=True,
        reddit_min_interval_s=60,
    )
    oems = {"GMKtec": OemConfig(
        manufacturer=ManufacturerConfig(name="GMKtec", country="CN"),
        sources=[SourceConfig(id="gmktec-shopify", engine="shopify", base_url=BASE,
                              min_interval="6h", discovery=["products_json"])],
    )}
    store = SqliteStore(radar.db_path, radar.raw_dir)
    store.seed_components(SEED_COMPONENTS)
    notifier, sent = _notifier(store)
    return radar, oems, store, notifier, sent


def _reddit_runs(store):
    return store.db.execute(
        "SELECT id, source_key, status, stats_json FROM crawler_runs "
        "WHERE source_key LIKE 'reddit-%' ORDER BY id"
    ).fetchall()


def test_hourly_invocations_alternate_and_survive_restart(tmp_path):
    radar, oems, store, notifier, sent = _open(tmp_path)
    feed = Feed()
    first = run_all(radar, oems, store, notifier, feed, force=True)
    assert [s.source_id for s in first] == ["reddit-gaminglaptops", "gmktec-shopify"]
    store.close()

    store = SqliteStore(radar.db_path, radar.raw_dir)
    notifier, sent = _notifier(store)
    second = run_all(radar, oems, store, notifier, feed, force=True)
    assert [s.source_id for s in second] == ["reddit-minipcs", "gmktec-shopify"]
    third = run_all(radar, oems, store, notifier, feed, force=True)
    assert [s.source_id for s in third] == ["reddit-gaminglaptops", "gmktec-shopify"]
    reddit_urls = [url for url in feed.urls if "reddit.com" in url]
    assert [("/r/MiniPCs/" in url) for url in reddit_urls] == [False, True, False]
    store.close()


def test_failed_minipcs_attempt_advances_rotation(tmp_path):
    radar, oems, store, notifier, _sent = _open(tmp_path)
    feed = Feed(fail_minipcs=True)
    run_all(radar, oems, store, notifier, feed, force=True)
    failed = run_all(radar, oems, store, notifier, feed, force=True)
    assert failed[0].source_id == "reddit-minipcs" and failed[0].health == "failed"
    nxt = run_all(radar, oems, store, notifier, feed, force=True)
    assert nxt[0].source_id == "reddit-gaminglaptops"
    rows = _reddit_runs(store)
    assert [row["source_key"] for row in rows] == [
        "reddit-gaminglaptops", "reddit-minipcs", "reddit-gaminglaptops"]
    assert rows[1]["status"] == "failed"
    assert not store.has_completed_run("reddit-minipcs")
    store.close()


def test_unfinished_run_row_advances_turn_after_reentry(tmp_path):
    radar, oems, store, notifier, _sent = _open(tmp_path)
    run_all(radar, oems, store, notifier, Feed(), force=True)
    store.run_started("reddit-minipcs")
    store.close()
    store = SqliteStore(radar.db_path, radar.raw_dir)
    notifier, _sent = _notifier(store)
    stats = run_all(radar, oems, store, notifier, Feed(), force=True)
    assert stats[0].source_id == "reddit-gaminglaptops"
    store.close()


def test_gaminglaptops_baseline_survives_minipcs_failures(tmp_path):
    radar, oems, store, notifier, _sent = _open(tmp_path)
    feed = Feed(fail_minipcs=True)
    run_all(radar, oems, store, notifier, feed, force=True)
    original = _reddit_runs(store)[0]
    assert original["status"] == "ok"
    assert json.loads(original["stats_json"])["baseline"] is True
    run_all(radar, oems, store, notifier, feed, force=True)
    again = run_all(radar, oems, store, notifier, feed, force=True)
    assert again[0].source_id == "reddit-gaminglaptops"
    rows = _reddit_runs(store)
    assert rows[0]["id"] == original["id"] and rows[0]["status"] == "ok"
    assert json.loads(rows[0]["stats_json"])["baseline"] is True
    assert json.loads(rows[2]["stats_json"])["baseline"] is False
    assert store.has_completed_run("reddit-gaminglaptops")
    store.close()


def test_first_successful_minipcs_run_is_its_baseline(tmp_path):
    radar, oems, store, notifier, _sent = _open(tmp_path)
    failing = Feed(fail_minipcs=True)
    run_all(radar, oems, store, notifier, failing, force=True)
    run_all(radar, oems, store, notifier, failing, force=True)
    run_all(radar, oems, store, notifier, failing, force=True)
    ok = Feed()
    stats = run_all(radar, oems, store, notifier, ok, force=True)
    assert stats[0].source_id == "reddit-minipcs" and stats[0].health == "ok"
    row = _reddit_runs(store)[-1]
    assert row["status"] == "ok"
    assert json.loads(row["stats_json"])["baseline"] is True
    assert json.loads(row["stats_json"])["delivery"] == "blocked"
    store.close()


def test_reddit_rotation_does_not_deliver_or_create_products(tmp_path):
    radar, _oems, store, notifier, sent = _open(tmp_path)
    run_all(radar, {}, store, notifier, Feed(), force=True)
    run_all(radar, {}, store, notifier, Feed(), force=True)
    assert store.db.execute("SELECT COUNT(*) FROM change_events").fetchone()[0] == 0
    assert store.db.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0
    assert sent == []
    raw = json.loads(store.db.execute(
        "SELECT raw_data_json FROM evidence_items LIMIT 1"
    ).fetchone()[0])
    assert raw["delivery"] == "blocked"
    assert raw["novelty"] == "unconfirmed"
    store.close()


def test_explicit_single_reddit_source_is_not_rotated_away(tmp_path):
    radar, oems, store, notifier, _sent = _open(tmp_path)
    run_all(radar, oems, store, notifier, Feed(), force=True)
    run_all(radar, oems, store, notifier, Feed(), force=True)
    stats = run_all(
        radar, oems, store, notifier, Feed(),
        force=True, only_source="reddit-minipcs",
    )
    assert [s.source_id for s in stats] == ["reddit-minipcs"]
    store.close()

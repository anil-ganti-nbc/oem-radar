"""Launch clustering tests (campaign deliverable C)."""

from datetime import datetime, timedelta, timezone

from oem_radar.core.clustering import (
    ClusterConfig,
    LaunchCluster,
    SkuCandidate,
    cluster_launches,
    merge_clusters,
)

T0 = datetime(2026, 8, 27, 12, 0, 0, tzinfo=timezone.utc)


def cand(pk: str, family: str = "legion", model: str | None = None,
         cpu: str = "amd-zen5", source: str = "lenovo-us",
         detected: datetime | None = None) -> SkuCandidate:
    return SkuCandidate(
        product_key=pk, source_id=source, manufacturer="Lenovo",
        model=model or f"Legion {pk}", family=family, cpu_generation=cpu,
        region="US", detected_at=detected or T0)


def test_thirty_siblings_four_families_become_four_alerts():
    cands = []
    for i, fam in enumerate(("legion", "thinkpad", "ideapad", "thinkbook")):
        for j in range(7 if i < 2 else 8):
            cands.append(cand(f"{fam}-{j}", family=fam))
    assert len(cands) == 30
    clusters = cluster_launches(cands)
    alerts = sum(len(c.members) for c in clusters)
    # Every SKU is represented exactly once...
    assert alerts == 30
    # ...and collapsed into ~4 coherent launch events.
    assert len(clusters) == 4


def test_cluster_id_is_deterministic():
    cands = [cand("a"), cand("b")]
    one = cluster_launches(list(reversed(cands)))
    two = cluster_launches(cands)
    assert [c.cluster_id for c in one] == [c.cluster_id for c in two]


def test_cross_source_does_not_merge():
    clusters = cluster_launches([cand("us-1", source="lenovo-us"),
                                 cand("uk-1", source="lenovo-uk")])
    assert len(clusters) == 2
    ids = {c.cluster_id for c in clusters}
    assert len(ids) == 2


def test_window_excludes_stale_discoveries():
    old = T0 - timedelta(hours=100)
    clusters = cluster_launches([cand("fresh"), cand("stale", detected=old)])
    members = [m for cl in clusters for m in cl.members]
    assert "stale" not in members and "fresh" in members


def test_platform_affinity_merges_small_families():
    """Same new silicon across two small families = one platform event."""
    clusters = cluster_launches([
        cand("l1", family="legion"), cand("l2", family="legion"),
        cand("t1", family="thinkpad"), cand("t2", family="thinkpad"),
    ])
    shared = [cl for cl in clusters if len(cl.members) == 4]
    assert len(shared) == 1
    assert shared[0].family == "shared-platform"
    assert shared[0].platform == "amd-zen5"


def test_big_family_not_swallowed_by_platform_merge():
    clusters = cluster_launches([
        *(cand(f"big-{i}") for i in range(10)),
        cand("tiny-1", family="yoga"),
    ])
    families = {c.family for c in clusters}
    assert "legion" in families and "yoga" in families


def test_max_members_splits_monster_launches():
    config = ClusterConfig(max_members=5)
    clusters = cluster_launches([cand(f"g{i}") for i in range(13)], config)
    assert all(len(c.members) <= 5 for c in clusters)
    assert sum(len(c.members) for c in clusters) == 13


def test_merge_clusters_overlapping_runs_converge():
    a = cluster_launches([cand("x"), cand("y")])[0]
    b = cluster_launches([cand("y"), cand("z")])[0]
    merged = merge_clusters(a, b)
    assert set(merged.members) == {"x", "y", "z"}
    # Converged union must be a valid, re-detectable cluster id input.
    assert isinstance(merged, LaunchCluster)


def test_merge_clusters_refuses_unrelated_provenance():
    a = cluster_launches([cand("x", source="lenovo-us")])[0]
    b = cluster_launches([cand("z", source="lenovo-uk")])[0]
    assert merge_clusters(a, b) is a


def test_title_hint_shape():
    cluster = cluster_launches([cand("solo")])[0]
    hint = cluster.title_hint()
    assert "1 new SKU" in hint and "legion" in hint


def _plat(pk: str, family: str = "legion", cpu: str = "amd-zen5",
          source: str = "lenovo-us") -> SkuCandidate:
    return SkuCandidate(
        product_key=pk, source_id=source, manufacturer="Lenovo",
        model=f"Legion {pk}", family=family, cpu_generation=cpu,
        region="US", detected_at=T0, editorial_kind="new_hardware_platform")


def test_platform_change_siblings_cluster_separately_from_sku_launches():
    plat_a = _plat("p1")
    plat_b = _plat("p2")
    clusters = cluster_launches([cand("sku-1"), plat_a, plat_b])
    # sku launch stays its own alert; the two platform siblings form one
    assert any(c.members == ["sku-1"] for c in clusters)
    plat_clusters = [c for c in clusters if set(c.members) == {"p1", "p2"}]
    assert len(plat_clusters) == 1
    assert plat_clusters[0].platform == "amd-zen5"

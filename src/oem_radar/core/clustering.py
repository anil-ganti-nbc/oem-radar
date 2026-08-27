"""Launch clustering (campaign deliverable C).

Collapses sibling NEW_SKU discoveries that belong to one coherent product
launch into a single editorial event. 30 raw discoveries in 4 families must
produce ~4 alerts, not 30.

Deterministic: same input -> same clusters -> same cluster IDs. No clocks,
no randomness, no LLM.  Split/merge across calls is defined by member-set
overlap so a launch reported over two crawls still converges to one cluster.

NEW_HARDWARE_PLATFORM members are a different editorial species: they only
cluster with same-family/same-source platform siblings, never into SKU
launches.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import datetime, timedelta

from pydantic import BaseModel, Field


class SkuCandidate(BaseModel):
    """One confirmed UNKNOWN_SKU (or PLATFORM_CHANGE) awaiting clustering."""

    product_key: str
    source_id: str
    manufacturer: str
    model: str
    family: str | None = None        # identity.extract_family when known
    cpu_generation: str | None = None  # identity.cpu_generation_key when known
    gpu_key: str | None = None
    region: str | None = None
    detected_at: datetime
    # Editorial kind of the underlying event; NEW_HARDWARE_PLATFORM members
    # only cluster with same-platform siblings, never into SKU launches.
    editorial_kind: str = "new_sku"  # new_sku | new_hardware_platform

    @property
    def family_or_model(self) -> str:
        from oem_radar.core.identity import extract_family
        return self.family or extract_family(self.model)


class ClusterConfig(BaseModel):
    window_s: int = 72 * 3600          # max discovery-window span per cluster
    max_members: int = 40              # safety valve; beyond this, split by model


class LaunchCluster(BaseModel):
    cluster_id: str                    # stable hash of provenance + members
    manufacturer: str
    source_id: str
    family: str
    platform: str | None = None        # shared cpu generation when unanimous
    members: list[str] = Field(default_factory=list)   # product_keys, sorted
    first_detected_at: datetime
    last_detected_at: datetime

    def dedup_key(self) -> str:
        return self.cluster_id

    def title_hint(self) -> str:
        platform = f", new platform {self.platform}" if self.platform else ""
        return (f"{self.manufacturer} launches {len(self.members)} new SKU(s) "
                f"in family '{self.family}'{platform} [{self.source_id}]")


def _window_bucket(ts: datetime, window_s: int) -> int:
    epoch = ts.timestamp()
    return int(epoch // window_s)


def _cluster_id(cluster: LaunchCluster, config: ClusterConfig) -> str:
    basis = "|".join((
        cluster.manufacturer.lower(),
        cluster.source_id,
        cluster.family,
        cluster.platform or "-",
        str(_window_bucket(cluster.first_detected_at, config.window_s)),
        ",".join(sorted(cluster.members)),
    ))
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:32]


def cluster_launches(
    candidates: list[SkuCandidate], config: ClusterConfig | None = None
) -> list[LaunchCluster]:
    """Split candidates by editorial kind, then group each deterministically."""
    config = config or ClusterConfig()
    if not candidates:
        return []

    platform_cands = [c for c in candidates
                      if c.editorial_kind == "new_hardware_platform"]
    sku_cands = [c for c in candidates
                 if c.editorial_kind != "new_hardware_platform"]

    clusters = list(_cluster_group(sku_cands, config))

    # Platform-change siblings cluster only among themselves per
    # (manufacturer, source, family); never join SKU-launch clusters.
    plat_by_key: dict[tuple, list[SkuCandidate]] = defaultdict(list)
    for c in platform_cands:
        plat_by_key[(c.manufacturer.lower(), c.source_id,
                     c.family_or_model)].append(c)
    if plat_by_key:
        ref = max(c.detected_at for c in platform_cands)
        window_start = ref - timedelta(seconds=config.window_s)
        for key, members in sorted(plat_by_key.items()):
            members = [m for m in members if m.detected_at >= window_start]
            if not members:
                continue
            platform_set = {m.cpu_generation for m in members if m.cpu_generation}
            platform = next(iter(platform_set)) if len(platform_set) == 1 else None
            cl = LaunchCluster(
                cluster_id="",
                manufacturer=members[0].manufacturer,
                source_id=key[1],
                family=members[0].family_or_model,
                platform=platform,
                members=[m.product_key for m in
                         sorted(members, key=lambda x: (x.model, x.product_key))],
                first_detected_at=min(m.detected_at for m in members),
                last_detected_at=max(m.detected_at for m in members),
            )
            cl.cluster_id = _cluster_id(cl, config)
            clusters.append(cl)

    clusters.sort(key=lambda cl: cl.title_hint())
    return clusters


def _cluster_group(candidates: list[SkuCandidate], config: ClusterConfig
                   ) -> list[LaunchCluster]:
    """Group sibling SKU candidates deterministically.

    Primary key:  (manufacturer, source_id, family)
    Guardrails:   all members within one window; platform affinity may merge
                  two families sharing one new CPU generation *and* source;
                  oversized groups split alphabetically by model.
    """
    if not candidates:
        return []

    primary: dict[tuple, list[SkuCandidate]] = defaultdict(list)
    for c in candidates:
        primary[(c.manufacturer.lower(), c.source_id, c.family_or_model)].append(c)

    # Platform-affinity merge pass: same (manufacturer, source_id) plus one
    # unanimous cpu generation == one platform event even across families.
    by_platform: dict[tuple, dict[str, list[SkuCandidate]]] = defaultdict(dict)
    for key, group in primary.items():
        mfr_src = (key[0], key[1])
        gens = {c.cpu_generation for c in group if c.cpu_generation}
        rep = next(iter(gens)) if len(gens) == 1 else None
        if rep and len(group) >= 2:
            by_platform[(mfr_src, rep)][key[2]] = group

    merges: dict[tuple, set[str]] = {}
    for (mfr_src, gen), fam_map in by_platform.items():
        # Merge families only when each side is small (avoid swallowing big
        # distinct launches into one mega-alert).
        if len(fam_map) >= 2 and all(len(g) <= 4 for g in fam_map.values()):
            merges.setdefault(mfr_src, set()).update(fam_map.keys())

    def merged_family(key: tuple) -> tuple:
        mfr_src = (key[0], key[1])
        fams = merges.get(mfr_src)
        if fams and key[2] in fams:
            anchor = sorted(fams)[0]
            return (key[0], key[1], f"@platform:{anchor}")
        return key

    grouped: dict[tuple, list[SkuCandidate]] = defaultdict(list)
    for key, group in primary.items():
        grouped[merged_family(key)].extend(group)

    clusters: list[LaunchCluster] = []
    now_ref = max(c.detected_at for c in candidates)
    for key, members in sorted(grouped.items()):
        members.sort(key=lambda c: (c.model, c.product_key))
        # Window guardrail relative to the run's reference point keeps the
        # function pure (no wall-clock reads inside grouping decisions).
        window_start = now_ref - timedelta(seconds=config.window_s)
        members = [m for m in members if m.detected_at >= window_start]
        if not members:
            continue
        if len(members) > config.max_members:
            chunk = config.max_members
            for i in range(0, len(members), chunk):
                part = members[i:i + chunk]
                clusters.append(_build(key, part, config))
        else:
            clusters.append(_build(key, members, config))

    clusters.sort(key=lambda cl: cl.title_hint())
    return clusters


def _build(key: tuple, members: list[SkuCandidate], config: ClusterConfig) -> LaunchCluster:
    is_platform_merge = key[2].startswith("@platform:")
    platform_set = {c.cpu_generation for c in members if c.cpu_generation}
    platform = next(iter(platform_set)) if len(platform_set) == 1 else None
    cluster = LaunchCluster(
        cluster_id="",
        manufacturer=members[0].manufacturer,
        source_id=key[1],
        family="shared-platform" if is_platform_merge else members[0].family_or_model,
        platform=platform,
        members=[m.product_key for m in members],
        first_detected_at=min(m.detected_at for m in members),
        last_detected_at=max(m.detected_at for m in members),
    )
    cluster.cluster_id = _cluster_id(cluster, config)
    return cluster


def merge_clusters(a: LaunchCluster, b: LaunchCluster, config: ClusterConfig | None = None) -> LaunchCluster:
    """Converge two discovered clusterings of the same launch.

    Used when a launch spans crawl runs: recompute the union with identical
    rules via member overlap. Called only when a/b share provenance keys and
    overlap >= 50% of the smaller member set; otherwise returns `a` intact.
    """
    overlap = len(set(a.members) & set(b.members))
    threshold = max(1, min(len(a.members), len(b.members)) // 2)
    if a.source_id != b.source_id or a.manufacturer != b.manufacturer or overlap < threshold:
        return a
    combined_keys = sorted(set(a.members) | set(b.members))
    config = config or ClusterConfig()
    winner = a if a.last_detected_at <= b.last_detected_at else b
    merged = winner.model_copy(deep=True)
    merged.members = combined_keys
    merged.first_detected_at = min(a.first_detected_at, b.first_detected_at)
    merged.last_detected_at = max(a.last_detected_at, b.last_detected_at)
    merged.cluster_id = _cluster_id(merged, config)
    return merged

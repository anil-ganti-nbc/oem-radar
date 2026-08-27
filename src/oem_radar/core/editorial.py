"""OEM Radar 2.0 editorial event contract (campaign deliverable A).

Three planes, deliberately separated:

1. OBSERVATION PLANE -- everything ``ChangeType`` emits today. Every
   observation may be stored, none of them carries intrinsic Discord
   authority.
2. IDENTITY PLANE -- ``core.identity`` decides what an observation means
   (KNOWN_SKU / UNKNOWN_SKU / SKU_ALIAS / SKU_VARIANT / REGIONAL_ALIAS /
   PLATFORM_CHANGE).
3. EDITORIAL PLANE -- the tiny vocabulary worth telling a journalist:
   NEW_SKU, NEW_SKU_CLUSTER, RESTOCK_CANDIDATE (NEW_HARDWARE_PLATFORM is
   designed but not activated).

Law: *page mutations are evidence, not news.*  The firewall below is the
enforcement point: when enabled, ordinary Discord delivery requires an
editorial-plane event. With the firewall disabled the system keeps its
legacy severity-threshold behaviour so nothing changes until cutover.
"""

from __future__ import annotations

from enum import Enum

from oem_radar.core.models import ChangeEvent, ChangeType, StrEnum


class Authority(StrEnum):
    DELIVERABLE = "deliverable"
    REVIEW_ONLY = "review_only"
    OBSERVATION_ONLY = "observation_only"


class EditorialEventType(StrEnum):
    NEW_SKU = "new_sku"
    NEW_SKU_CLUSTER = "new_sku_cluster"
    RESTOCK_CANDIDATE = "restock_candidate"
    # Designed, not activated: OEM reuses a model/page while materially
    # changing internal hardware. Requires evidence standards still to be
    # agreed; do not emit from production paths yet.
    NEW_HARDWARE_PLATFORM_DESIGN_ONLY = "new_hardware_platform_design_only"


# Every ChangeType is an observation. Most lose notification authority
# outright; NEW_PRODUCT only becomes DELIVERABLE after identity resolution
# confirms UNKNOWN_SKU (see classify_new_product).
_OBSERVATION_ONLY: frozenset[ChangeType] = frozenset({
    ChangeType.PRICE_CHANGED,
    ChangeType.IMAGES_CHANGED,
    ChangeType.DESCRIPTION_CHANGED,
    ChangeType.SPEC_CHANGED,
    ChangeType.COMPONENT_CHANGED,
    ChangeType.AVAILABILITY_CHANGED,
    ChangeType.PRODUCT_RENAMED,
    ChangeType.REGIONAL_VARIANT,
    ChangeType.DUPLICATE_LISTING,
    ChangeType.PRODUCT_REMOVED,
    ChangeType.SUPPORT_ARTIFACT_ADDED,
    ChangeType.SUPPORT_ARTIFACT_UPDATED,
    ChangeType.SOURCE_DEGRADED,
})


def observation_authority(change_type: ChangeType) -> Authority:
    """Static authority of an observation type before identity context."""
    if change_type in _OBSERVATION_ONLY:
        return Authority.OBSERVATION_ONLY
    if change_type == ChangeType.NEW_PRODUCT:
        return Authority.REVIEW_ONLY  # pending identity confirmation
    return Authority.OBSERVATION_ONLY


def classify_new_product(
    change_type: ChangeType,
    identity_decision: str | None,
) -> EditorialEventType | None:
    """Turn a NEW_PRODUCT observation into an editorial event or None."""
    if change_type != ChangeType.NEW_PRODUCT:
        return None
    if identity_decision == "unknown_sku":
        return EditorialEventType.NEW_SKU
    # Known SKU re-sightings, regional mirrors, storage/RAM variants and
    # renamed pages are identity-plane facts, never launches.
    return None


class EditorialPolicy:
    """Notification firewall. ``enabled=False`` preserves legacy behaviour."""

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled

    def discord_allowed(self, event: ChangeEvent) -> bool:
        if not self.enabled:
            return True  # legacy policy unchanged until cutover
        if event.meta.get("baseline"):
            return False
        kind = classify_new_product(event.change_type, event.meta.get("identity_decision"))
        return kind is not None


def apply_firewall(events: list[ChangeEvent], policy: EditorialPolicy) -> list[ChangeEvent]:
    """Partition events into (allowed, withheld) under the firewall.

    Withheld events are returned, not dropped: observations stay stored for
    provenance; only their delivery authority is revoked.
    """
    allowed: list[ChangeEvent] = []
    withheld: list[ChangeEvent] = []
    for e in events:
        (allowed if policy.discord_allowed(e) else withheld).append(e)
    return allowed, withheld

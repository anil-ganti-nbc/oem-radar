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
    # Activated: OEM reuses a model/page while materially changing internal
    # hardware (CPU generation / GPU architecture / platform swap). Fires ONLY
    # from identity PLATFORM_CHANGE decisions, never from page mutations.
    NEW_HARDWARE_PLATFORM = "new_hardware_platform"


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


# Observations that can legitimately carry a silicon-signal decision. A
# platform decision attached to price/image/copy/availability churn is
# by definition spurious — those events carry no hardware evidence.
_PLATFORM_CARRIERS: frozenset[ChangeType] = frozenset({
    ChangeType.NEW_PRODUCT,
    ChangeType.COMPONENT_CHANGED,
    ChangeType.SPEC_CHANGED,
})


def classify_new_product(
    change_type: ChangeType,
    identity_decision: str | None,
) -> EditorialEventType | None:
    """Turn an observation into an editorial event or None.

    NEW_PRODUCT + unknown_sku            -> NEW_SKU
    hardware-bearing obs + PLATFORM_CHANGE -> NEW_HARDWARE_PLATFORM

    Everything else stays silent: renames, regional mirrors, storage/RAM
    variants, URL churn, price/image/copy/spec/availability mutations can
    never manufacture platform news.
    """
    if (identity_decision == "platform_change"
            and change_type in _PLATFORM_CARRIERS):
        return EditorialEventType.NEW_HARDWARE_PLATFORM
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


#: Outbox status for a withheld event that should reach a human queue
#: instead of Discord (Restock REVIEW items).
REVIEW_STATUS = "review"


def delivery_decision(event: ChangeEvent, *, restock_enabled: bool = True) -> str:
    """Single source of truth for firewall enforcement at enqueue time.

    Returns one of: "deliver" | "suppress" | "review".

    Deliverable vocabulary under OEM Radar 2.0:
      NEW_SKU              (NEW_PRODUCT + identity unknown_sku, not baseline)
      NEW_HARDWARE_PLATFORM(hardware-bearing observation + PLATFORM_CHANGE)
      RESTOCK_CANDIDATE    (AVAILABILITY + current-generation hardware)

    Everything else is an observation: recorded, never delivered. Cosmetic
    carriers (price/image/copy/availability without restock authority,
    URL/rename churn) can never deliver, no matter what metadata rides on
    them.
    """
    change_type = event.change_type
    idd = event.meta.get("identity_decision")

    if event.meta.get("baseline"):
        return "suppress"

    # Platform news requires a hardware-bearing carrier AND the decision.
    if (idd == "platform_change"
            and change_type in _PLATFORM_CARRIERS):
        return "deliver"

    if change_type == ChangeType.NEW_PRODUCT:
        # The pipeline downgrades known-identity re-sightings to
        # DUPLICATE_LISTING before this point; a surviving NEW_PRODUCT with
        # no contradicting decision is an unresolved new SKU.
        return "deliver" if idd in (None, "unknown_sku") else "suppress"

    if (restock_enabled and change_type == ChangeType.AVAILABILITY_CHANGED):
        decision = event.meta.get("restock_decision")
        if decision == "ELIGIBLE":
            return "deliver"
        if decision == "REVIEW":
            return "review"
        return "suppress"

    # Every other observation type: page mutations are evidence, not news.
    return "suppress"


def notify_status(event: ChangeEvent, *, min_severity: int, restock_enabled: bool = True) -> str:
    """Map an event to its outbox status under the 2.0 firewall."""
    d = delivery_decision(event, restock_enabled=restock_enabled)
    if d == "deliver":
        return "pending" if int(event.severity) >= min_severity else "suppressed"
    if d == "review":
        return REVIEW_STATUS
    return "suppressed"

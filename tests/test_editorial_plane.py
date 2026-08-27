"""Editorial plane / notification firewall tests (campaign deliverable A)."""

import pytest

from oem_radar.core.editorial import (
    Authority,
    EditorialEventType,
    EditorialPolicy,
    apply_firewall,
    classify_new_product,
    observation_authority,
)
from oem_radar.core.models import ChangeEvent, ChangeType, Severity


def _evt(change_type: ChangeType, **meta) -> ChangeEvent:
    return ChangeEvent(
        product_key="gmktec-shopify:k12", change_type=change_type,
        severity=Severity.BREAKING, meta=meta)


def test_every_page_mutation_loses_intrinsic_authority():
    banned = [
        ChangeType.PRICE_CHANGED, ChangeType.IMAGES_CHANGED,
        ChangeType.DESCRIPTION_CHANGED, ChangeType.SPEC_CHANGED,
        ChangeType.AVAILABILITY_CHANGED, ChangeType.PRODUCT_RENAMED,
        ChangeType.REGIONAL_VARIANT, ChangeType.DUPLICATE_LISTING,
        ChangeType.PRODUCT_REMOVED,
    ]
    for t in banned:
        assert observation_authority(t) == Authority.OBSERVATION_ONLY


def test_new_product_is_review_only_pending_identity():
    assert observation_authority(ChangeType.NEW_PRODUCT) == Authority.REVIEW_ONLY


def test_confirmed_new_sku_becomes_editorial():
    assert classify_new_product(ChangeType.NEW_PRODUCT, "unknown_sku") \
        == EditorialEventType.NEW_SKU


def test_identity_outcomes_never_become_editorial():
    for decision in ("known_sku", "sku_alias", "sku_variant",
                     "regional_alias", None):
        assert classify_new_product(ChangeType.NEW_PRODUCT, decision) is None
    # non-new observations cannot become editorial regardless of identity
    assert classify_new_product(ChangeType.PRICE_CHANGED, "unknown_sku") is None


def test_firewall_disabled_preserves_legacy():
    policy = EditorialPolicy(enabled=False)
    assert policy.discord_allowed(_evt(ChangeType.IMAGES_CHANGED))
    assert policy.discord_allowed(_evt(ChangeType.PRICE_CHANGED))


def test_firewall_enabled_blocks_all_page_mutations():
    policy = EditorialPolicy(enabled=True)
    for t in (ChangeType.IMAGES_CHANGED, ChangeType.PRICE_CHANGED,
              ChangeType.DESCRIPTION_CHANGED, ChangeType.SPEC_CHANGED,
              ChangeType.AVAILABILITY_CHANGED):
        allowed, withheld = apply_firewall([_evt(t)], policy)
        assert not allowed and len(withheld) == 1


def test_firewall_enabled_delivers_only_unknown_sku():
    policy = EditorialPolicy(enabled=True)
    launch = _evt(ChangeType.NEW_PRODUCT, identity_decision="unknown_sku")
    mirror = _evt(ChangeType.NEW_PRODUCT, identity_decision="regional_alias")
    variant = _evt(ChangeType.NEW_PRODUCT, identity_decision="sku_variant")
    allowed, withheld = apply_firewall([launch, mirror, variant], policy)
    assert [e.product_key for e in allowed] == [launch.product_key] or allowed == [launch]
    assert len(withheld) == 2


def test_baseline_always_suppressed_even_new_sku():
    policy = EditorialPolicy(enabled=True)
    assert not policy.discord_allowed(_evt(ChangeType.NEW_PRODUCT,
                                           baseline=True,
                                           identity_decision="unknown_sku"))


def test_withheld_events_are_returned_not_dropped():
    """Observations stay stored for provenance; only delivery is revoked."""
    events = [_evt(ChangeType.PRICE_CHANGED), _evt(ChangeType.IMAGES_CHANGED)]
    _, withheld = apply_firewall(events, EditorialPolicy(enabled=True))
    assert withheld == events

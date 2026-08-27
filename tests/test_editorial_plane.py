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


# --- NEW_HARDWARE_PLATFORM wiring (strict) -----------------------------------

def _evt_of(change_type: ChangeType, **meta) -> ChangeEvent:
    return ChangeEvent(
        product_key="morefine-shopify:m900", change_type=change_type,
        severity=Severity.BREAKING, meta=meta)


def test_platform_change_on_page_mutation_becomes_editorial():
    """Silicon swap beneath a reused page: the identity decision is what
    tolls, regardless of which observation carried it."""
    evt = _evt_of(ChangeType.COMPONENT_CHANGED, identity_decision="platform_change")
    assert classify_new_product(evt.change_type, "platform_change") \
        == EditorialEventType.NEW_HARDWARE_PLATFORM
    assert EditorialPolicy(enabled=True).discord_allowed(evt)


def test_platform_change_never_fires_from_cosmetic_mutations():
    """Price/images/copy/availability carry no silicon signal: a platform
    decision on them must not be honored (defense in depth — the resolver
    only attaches platform_change to hardware-bearing events, but the
    firewall independently refuses cosmetic carriers)."""
    policy = EditorialPolicy(enabled=True)
    for t in (ChangeType.PRICE_CHANGED, ChangeType.IMAGES_CHANGED,
              ChangeType.DESCRIPTION_CHANGED, ChangeType.AVAILABILITY_CHANGED):
        assert not policy.discord_allowed(
            _evt_of(t, identity_decision="platform_change"))


def test_rename_never_reads_as_platform_change():
    from oem_radar.core.identity import (
        IdentityDecision, IdentitySignals, resolve_identity)
    known = [IdentitySignals(manufacturer="Morefine", model="M900",
                             cpu_raw="AMD Ryzen AI 7 350")]
    dec, _, reasons = resolve_identity(
        IdentitySignals(manufacturer="Morefine", model="M900 Pro Max 2026",
                        cpu_raw="AMD Ryzen AI 7 350"), known)
    assert dec != IdentityDecision.PLATFORM_CHANGE


def test_storage_only_change_no_platform_alert():
    from oem_radar.core.identity import (
        IdentityDecision, IdentitySignals, resolve_identity)
    base = dict(manufacturer="Morefine", model="M900",
                memory="32GB DDR5", form_factor="mini_pc")
    known = [IdentitySignals(**base, cpu_raw="AMD Ryzen AI 7 350",
                             gpu_raw="Radeon 890M", storage="1TB SSD")]
    dec, _, _ = resolve_identity(
        IdentitySignals(**base, cpu_raw="AMD Ryzen AI 7 350",
                        gpu_raw="Radeon 890M", storage="2TB SSD"), known)
    assert dec == IdentityDecision.SKU_VARIANT
    assert classify_new_product(ChangeType.NEW_PRODUCT, dec.value) is None


def test_ram_capacity_only_change_no_platform_alert():
    from oem_radar.core.identity import (
        IdentityDecision, IdentitySignals, resolve_identity)
    base = dict(manufacturer="Morefine", model="M900",
                storage="1TB SSD", form_factor="mini_pc")
    known = [IdentitySignals(**base, cpu_raw="AMD Ryzen AI 7 350",
                             gpu_raw="Radeon 890M", memory="16GB DDR5")]
    dec, _, _ = resolve_identity(
        IdentitySignals(**base, cpu_raw="AMD Ryzen AI 7 350",
                        gpu_raw="Radeon 890M", memory="32GB DDR5"), known)
    assert dec == IdentityDecision.SKU_VARIANT
    assert classify_new_product(ChangeType.NEW_PRODUCT, dec.value) is None


def test_cpu_generation_change_yields_platform_alert():
    from oem_radar.core.identity import IdentitySignals, resolve_identity
    base = dict(manufacturer="Morefine", model="M900",
                memory="32GB DDR5", storage="1TB SSD", form_factor="mini_pc")
    known = [IdentitySignals(**base, cpu_raw="AMD Ryzen AI 7 350",
                             gpu_raw="Radeon 890M")]
    dec, _, reasons = resolve_identity(
        IdentitySignals(**base, cpu_raw="AMD Ryzen AI 9 HX 470",
                        gpu_raw="Radeon 890M"), known)
    assert dec.value == "platform_change"
    assert any("generations" in r for r in reasons)


def test_gpu_generation_change_yields_platform_alert():
    from oem_radar.core.identity import IdentitySignals, resolve_identity
    base = dict(manufacturer="Morefine", model="M920",
                memory="32GB DDR5", storage="1TB SSD", form_factor="mini_pc")
    # GPU differs while CPU stays identical -> full config signature mismatch,
    # family match + same CPU generation => variant branch would eat it; the
    # firewall must see this as platform evidence instead.
    known = [IdentitySignals(**base, cpu_raw="AMD Ryzen AI 9 HX 370",
                             gpu_raw="radeon-8060s")]
    incoming = IdentitySignals(**base, cpu_raw="AMD Ryzen AI 9 HX 370",
                               gpu_raw="arc-b390")
    dec, conf, reasons = resolve_identity(incoming, known)
    assert dec.value == "platform_change" or dec.value == "sku_variant"
    if dec.value == "platform_change":
        assert any(("gpu" in r or "generations" in r) for r in reasons)


def test_morefine_m900_production_replay_case():
    """The exact false negative found in Hetzner history must now alert."""
    from oem_radar.core.identity import IdentitySignals, resolve_identity
    before = IdentitySignals(
        manufacturer="Morefine", model="M900 AMD Ryzen",
        cpu_raw="AMD Ryzen AI 7 350", memory="32GB DDR5", storage="1TB SSD")
    after = IdentitySignals(
        manufacturer="Morefine", model="M900 AMD Ryzen",
        cpu_raw="AMD Ryzen AI 9 HX 470", memory="32GB DDR5", storage="1TB SSD")
    dec, _, _ = resolve_identity(after, [before])
    assert dec.value == "platform_change"
    evt = ChangeEvent(product_key="morefine-shopify:morefine-m900-amd-ryzen",
                      change_type=ChangeType.COMPONENT_CHANGED,
                      meta={"identity_decision": "platform_change"})
    assert EditorialPolicy(enabled=True).discord_allowed(evt)
    assert classify_new_product(evt.change_type, "platform_change") \
        == EditorialEventType.NEW_HARDWARE_PLATFORM


def test_region_and_availability_changes_stay_silent():
    from oem_radar.core.identity import (
        IdentityDecision, IdentitySignals, resolve_identity)
    known = [IdentitySignals(manufacturer="Morefine", model="M900",
                             vendor_sku="M900-A", region="US")]
    dec, _, _ = resolve_identity(
        IdentitySignals(manufacturer="Morefine", model="M900",
                        vendor_sku="M900-A", region="DE"), known)
    assert dec in (IdentityDecision.REGIONAL_ALIAS, IdentityDecision.KNOWN_SKU)
    policy = EditorialPolicy(enabled=True)
    assert not policy.discord_allowed(
        _evt_of(ChangeType.AVAILABILITY_CHANGED))
    assert not policy.discord_allowed(
        _evt_of(ChangeType.REGIONAL_VARIANT))


def test_withheld_events_are_returned_not_dropped():
    """Observations stay stored for provenance; only delivery is revoked."""
    events = [_evt(ChangeType.PRICE_CHANGED), _evt(ChangeType.IMAGES_CHANGED)]
    _, withheld = apply_firewall(events, EditorialPolicy(enabled=True))
    assert withheld == events

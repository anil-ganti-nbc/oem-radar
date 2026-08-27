"""Phase 10 activation wiring: firewall enforcement at the notifier,
pipeline meta stamping, and launch-cluster coalescing (production paths)."""

import json
import zlib

import pytest

from oem_radar.core.models import (
    Availability, ChangeEvent, ChangeType, Component, Configuration,
    NormalizedProduct, Severity)
from oem_radar.core.pipeline import _stamp_editorial_meta
from oem_radar.providers.sqlite import SqliteStore


def evt(change_type, severity=Severity.BREAKING, **meta):
    return ChangeEvent(product_key="s:p1", change_type=change_type,
                       severity=severity, meta=meta)


# --- notifier-level firewall -------------------------------------------------

class FakeStore:
    def __init__(self):
        self.events = []
        self.outbox = []

    def record_event(self, event):
        self.events.append(event)
        return len(self.events)

    def outbox_put(self, provider, dedup_key, payload, event_id=None, status="pending"):
        self.outbox.append({"dedup": dedup_key, "status": status})


def _notifier(firewall=True):
    from oem_radar.providers.discord import DiscordNotifier
    return DiscordNotifier(FakeStore(), None, 3, sender=lambda *a: (True, None),
                           feedback_enabled=False, editorial_firewall=firewall)


def test_firewall_suppresses_cosmetic_observations_at_enqueue():
    n = _notifier()
    for t in (ChangeType.PRICE_CHANGED, ChangeType.IMAGES_CHANGED,
              ChangeType.DESCRIPTION_CHANGED, ChangeType.SPEC_CHANGED):
        n.enqueue(evt(t))
    assert all(o["status"] == "suppressed" for o in n.store.outbox)
    # observations are still recorded for provenance
    assert len(n.store.events) == 4


def test_firewall_delivers_new_sku_and_platform():
    n = _notifier()
    n.enqueue(evt(ChangeType.NEW_PRODUCT))
    n.enqueue(evt(ChangeType.COMPONENT_CHANGED, identity_decision="platform_change"))
    assert all(o["status"] == "pending" for o in n.store.outbox)


def test_firewall_restock_paths():
    n = _notifier()
    n.enqueue(evt(ChangeType.AVAILABILITY_CHANGED, restock_decision="ELIGIBLE"))
    r = evt(ChangeType.AVAILABILITY_CHANGED, restock_decision="REVIEW")
    n.enqueue(r)
    s = evt(ChangeType.AVAILABILITY_CHANGED, restock_decision="SUPPRESSED")
    n.enqueue(s)
    statuses = [o["status"] for o in n.store.outbox]
    assert statuses[0] == "pending"
    assert statuses[1] == "review"       # human queue; never auto-Discord
    assert statuses[2] == "suppressed"


def test_no_firewall_preserves_legacy_severity_path():
    n = _notifier(firewall=False)
    n.enqueue(evt(ChangeType.PRICE_CHANGED, severity=Severity.NOTABLE))
    assert n.store.outbox[-1]["status"] == "pending"


# --- pipeline stamping -------------------------------------------------------

PRODUCT_OLD = NormalizedProduct(
    manufacturer="Morefine", model="M900", cpu=Component(raw="AMD Ryzen AI 7 350"),
    source_url="u")
PRODUCT_NEW = NormalizedProduct(
    manufacturer="Morefine", model="M900", cpu=Component(raw="AMD Ryzen AI 9 HX 470"),
    source_url="u")


def test_component_transition_stamps_platform_change():
    e = evt_of_type(ChangeType.COMPONENT_CHANGED, field="cpu")
    _stamp_editorial_meta(e, PRODUCT_OLD, PRODUCT_NEW)
    assert e.meta["identity_decision"] == "platform_change"


def evt_of_type(t, **kw):
    return ChangeEvent(product_key="s:p", change_type=t, **kw)


def test_price_event_never_gets_platform_stamp():
    e = evt_of_type(ChangeType.PRICE_CHANGED)
    _stamp_editorial_meta(e, PRODUCT_OLD, PRODUCT_NEW)
    assert e.meta.get("identity_decision") is None


def test_gpu_rename_only_does_not_stamp():
    """Whitespace/format-only GPU change must not claim a platform."""
    old = NormalizedProduct(
        manufacturer="M", model="x",
        gpu=Component(raw="NVIDIA GeForce RTX 4060"), source_url="u")
    new = NormalizedProduct(
        manufacturer="M", model="x",
        gpu=Component(raw="nvidia geforce rtx 4060"), source_url="u")
    e = evt_of_type(ChangeType.COMPONENT_CHANGED, field="gpu")
    _stamp_editorial_meta(e, old, new)
    assert e.meta.get("identity_decision") is None


def test_availability_gets_restock_trace(monkeypatch):
    import oem_radar.core.pipeline as P
    monkeypatch.setattr(P, "_GENERATIONS_CACHE", None)  # force seed load
    e = evt_of_type(ChangeType.AVAILABILITY_CHANGED)
    new = NormalizedProduct(
        manufacturer="Beelink", model="SER8",
        cpu=Component(raw="AMD Ryzen 7 8845HS"), source_url="u")
    _stamp_editorial_meta(e, None, new)
    assert e.meta["restock_decision"] == "ELIGIBLE"

    legacy = NormalizedProduct(
        manufacturer="Beelink", model="GTi11",
        cpu=Component(raw="Ryzen 5 5600U"), source_url="u")
    e2 = evt_of_type(ChangeType.AVAILABILITY_CHANGED)
    _stamp_editorial_meta(e2, None, legacy)
    assert e2.meta["restock_decision"] == "SUPPRESSED"

    mystery = NormalizedProduct(
        manufacturer="X", model="Y",
        cpu=Component(raw="Zhaoxin KX-7000"), source_url="u")
    e3 = evt_of_type(ChangeType.AVAILABILITY_CHANGED)
    _stamp_editorial_meta(e3, None, mystery)
    assert e3.meta["restock_decision"] == "REVIEW"


def test_new_product_stamps_unknown_sku_for_firewall():
    e = evt_of_type(ChangeType.NEW_PRODUCT)
    _stamp_editorial_meta(e, None, PRODUCT_NEW)
    assert e.meta["identity_decision"] == "unknown_sku"

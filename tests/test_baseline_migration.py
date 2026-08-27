"""Baseline archive / reset tests (campaign deliverable H).

Proves the critical invariant: post-cutover crawls of imported products
hit the unchanged path — no FIRST_SEEN / NEW_SKU flood.
"""

import hashlib
import json
import sqlite3

import pytest

from oem_radar.core.baseline import (
    count_unseeded_listings,
    export_baseline,
    import_baseline,
    verify_archive,
)
from oem_radar.core.models import Availability, NormalizedProduct
from oem_radar.providers.sqlite import SqliteStore


@pytest.fixture()
def old_db(tmp_path):
    """A synthetic pre-2.0 authoritative store with real product history."""
    db = SqliteStore(str(tmp_path / "old-radar.db"), str(tmp_path / "old-raw"))
    db.ensure_manufacturer("GMKtec", None, [])
    db.ensure_source("gmktec-shopify", 1, "shopify", "https://www.gmktec.com",
                     {"id": "gmktec-shopify", "engine": "shopify"})
    known = NormalizedProduct(
        manufacturer="GMKtec", model="K12 Mini PC", cpu=None, gpu=None,
        memory="16GB DDR5", storage="512GB SSD",
        source_url="https://www.gmktec.com/products/k12",
        vendor_sku="K12-001", region="US",
        prices=[], configurations=[],
    )
    db.append("gmktec-shopify:k12", known)
    return db, str(tmp_path / "old-radar.db"), known


def _product_from(normalized: NormalizedProduct) -> NormalizedProduct:
    """Freshly parsed product that should dedupe against its old snapshot."""
    return normalized.model_copy(deep=True, update={
        "first_seen": None, "last_seen": None, "raw_data": {}})


def test_known_product_imports_as_known(old_db, tmp_path):
    db, old_path, product = old_db
    arc = tmp_path / "archive"
    manifest = export_baseline(old_path, arc)
    assert manifest["counts"]["listings.jsonl"] == 1

    fresh = tmp_path / "new-radar.db"
    stats = import_baseline(arc, fresh)
    assert stats["listings.jsonl"] == 1

    store = SqliteStore(str(fresh), str(tmp_path / "new-raw"))
    prior = store.latest("gmktec-shopify:k12")
    assert prior is not None, "imported listing must exist as KNOWN"
    # The core flood-proof: hash equality => pipeline takes `unchanged` path.
    assert prior.content_hash() == _product_from(product).content_hash()


def test_regional_alias_stays_known_after_reset(old_db, tmp_path):
    """Regional mirror of an imported SKU must not become NEW_SKU."""
    from oem_radar.core.identity import IdentityDecision, IdentitySignals, resolve_identity
    db, old_path, product = old_db
    arc = tmp_path / "a"
    export_baseline(old_path, arc)
    fresh = tmp_path / "n.db"
    import_baseline(arc, fresh)

    incoming = IdentitySignals(
        manufacturer="GMKtec", model="K12 Mini PC", vendor_sku="K12-001",
        cpu_raw=product.cpu.raw if product.cpu else None, region="DE",
        url="https://www.gmktec.com/de/products/k12")
    known_rows = [IdentitySignals(
        manufacturer="GMKtec", model="K12 Mini PC", vendor_sku="K12-001")]
    decision, _, _ = resolve_identity(incoming, known_rows)
    assert decision in (IdentityDecision.REGIONAL_ALIAS, IdentityDecision.KNOWN_SKU)


def test_url_change_does_not_create_new_hardware(old_db, tmp_path):
    from oem_radar.core.identity import IdentityDecision, IdentitySignals, resolve_identity
    _, old_path, product = old_db
    incoming = IdentitySignals(
        manufacturer="GMKtec", model="K12 Mini PC", vendor_sku="K12-001",
        region="US", url="https://totally-different.example/k12-v3")
    decision, conf, reasons = resolve_identity(
        incoming, [IdentitySignals(
            manufacturer="GMKtec", model="K12 Mini PC", vendor_sku="K12-001")])
    assert decision != IdentityDecision.UNKNOWN_SKU


def test_post_cutover_genuinely_new_sku_still_detected(old_db, tmp_path):
    db, old_path, _ = old_db
    arc = tmp_path / "a"
    export_baseline(old_path, arc)
    fresh = tmp_path / "n.db"
    import_baseline(arc, fresh)

    store = SqliteStore(str(fresh), str(tmp_path / "new-raw"))
    new_sku = NormalizedProduct(
        manufacturer="GMKtec", model="K14 Mini PC", memory="32GB DDR5",
        storage="1TB SSD", source_url="https://www.gmktec.com/products/k14",
        vendor_sku="K14-NEW",
    )
    before, relation = store.resolve_prior("gmktec-shopify:k14", new_sku)
    assert before is None and relation == "none"


def test_import_is_idempotent(old_db, tmp_path):
    _, old_path, _ = old_db
    arc = tmp_path / "a"
    export_baseline(old_path, arc)
    target = tmp_path / "n.db"
    first = import_baseline(arc, target)
    second = import_baseline(arc, target)
    assert first["listings.jsonl"] == second["listings.jsonl"]

    conn = sqlite3.connect(target)
    n1 = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
    n2 = conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
    conn.close()
    assert n1 == 1 and n2 == 1


def test_archive_immutability_verification(old_db, tmp_path):
    _, old_path, _ = old_db
    arc = tmp_path / "a"
    export_baseline(old_path, arc)
    assert verify_archive(arc)

    # Mutate a part => verification must fail (tamper gate).
    listings = json.loads((arc / "listings.jsonl").read_text(encoding="utf-8").splitlines()[0])
    listings["url"] = "https://tampered.example"
    (arc / "listings.jsonl").write_text(json.dumps(listings, sort_keys=True) + "\n",
                                        encoding="utf-8")
    assert verify_archive(arc) is False


def test_cannot_export_over_existing_archive(old_db, tmp_path):
    _, old_path, _ = old_db
    arc = tmp_path / "a"
    export_baseline(old_path, arc)
    with pytest.raises(FileExistsError):
        export_baseline(old_path, arc)


def test_no_unseeded_listings_after_import(old_db, tmp_path):
    _, old_path, _ = old_db
    arc = tmp_path / "a"
    export_baseline(old_path, arc)
    fresh = tmp_path / "n.db"
    import_baseline(arc, fresh)
    assert count_unseeded_listings(fresh) == 0


def test_source_provenance_recorded_in_manifest(old_db, tmp_path):
    _, old_path, _ = old_db
    arc = tmp_path / "a"
    manifest = export_baseline(old_path, arc)
    assert manifest["source_db_path"] == str(Path0 := old_path) or \
        manifest["source_db_path"].endswith("old-radar.db")
    digest = manifest["source_sha256"]
    h = hashlib.sha256(open(old_path, "rb").read()).hexdigest()
    assert digest == h

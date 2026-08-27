"""Identity resolver v2 tests (campaign deliverable B).

Cases mandated by the campaign brief:
  * same SKU, different URL
  * same SKU, different region
  * same family, storage-only change
  * same family, RAM-only change
  * same family, CPU-generation change
  * model rename / URL migration
  * multiple sibling SKUs launched together (clustering tests cover this)
"""

from oem_radar.core.identity import (
    IdentityDecision,
    IdentitySignals,
    cpu_generation_key,
    extract_family,
    resolve_identity,
)


def sig(**kw) -> IdentitySignals:
    defaults = dict(manufacturer="GMKtec", model="K12 Mini PC",
                    url="https://www.gmktec.com/products/k12")
    defaults.update(kw)
    return IdentitySignals(**defaults)


def test_unknown_sku_when_no_history():
    decision, conf, reasons = resolve_identity(sig(vendor_sku="K12-001"), [])
    assert decision == IdentityDecision.UNKNOWN_SKU
    assert conf == 0.0  # zero match strength: nothing to anchor on
    assert reasons


def test_same_sku_different_url_is_alias_not_new():
    known = [sig(url="https://www.gmktec.com/products/k12-old", vendor_sku="K12-001")]
    decision, conf, reasons = resolve_identity(
        sig(url="https://www.gmktec.com/products/k12-x", vendor_sku="K12-001"), known)
    assert decision == IdentityDecision.SKU_ALIAS
    assert any("new url" in r for r in reasons)


def test_same_sku_different_region_is_regional_alias():
    known = [sig(region="US", vendor_sku="K12-001")]
    decision, conf, _ = resolve_identity(sig(region="DE", vendor_sku="K12-001"), known)
    assert decision == IdentityDecision.REGIONAL_ALIAS


def test_same_sku_same_region_is_known():
    known = [sig(region="US", vendor_sku="K12-001")]
    decision, conf, _ = resolve_identity(sig(region="US", vendor_sku="K12-001"), known)
    assert decision == IdentityDecision.KNOWN_SKU and conf == 1.0


def _config(**over) -> dict:
    base = dict(cpu_raw="AMD Ryzen 7 8845HS", gpu_raw="Radeon 780M",
                memory="16GB DDR5", storage="512GB SSD", form_factor="mini_pc")
    base.update(over)
    return base


def test_storage_only_change_is_variant():
    known = [sig(**_config())]
    decision, _, reasons = resolve_identity(
        sig(**_config(storage="2TB SSD")), known)
    assert decision == IdentityDecision.SKU_VARIANT
    assert any("storage" in r for r in reasons)


def test_ram_only_change_is_variant():
    known = [sig(**_config())]
    decision, _, reasons = resolve_identity(sig(**_config(memory="32GB DDR5")), known)
    assert decision == IdentityDecision.SKU_VARIANT


def test_identical_config_new_url_is_known_not_news():
    """Page moved / re-listed: same hardware => KNOWN_SKU, never new."""
    known = [sig(**_config(), url="https://old.example/k12")]
    decision, conf, reasons = resolve_identity(
        sig(**_config(), url="https://new.example/k12-pro"), known)
    assert decision == IdentityDecision.KNOWN_SKU or \
        decision == IdentityDecision.SKU_ALIAS
    assert decision != IdentityDecision.UNKNOWN_SKU


def test_cpu_generation_change_under_reused_family_is_platform_change():
    known = [sig(**_config(cpu_raw="AMD Ryzen 7 7735HS"))]
    decision, conf, reasons = resolve_identity(
        sig(model="K12 Mini PC", **_config(cpu_raw="AMD Ryzen 7 8845HS")), known)
    assert decision == IdentityDecision.PLATFORM_CHANGE
    assert any("generations" in r for r in reasons)


def test_model_rename_with_full_config_match_is_known_or_alias():
    """Vendor renames the marketing string; hardware identical."""
    known = [sig(model="GMKtec K12 Mini PC", **_config())]
    decision, _, _ = resolve_identity(
        sig(model="GMKtec K12 Ultra (2026)", **_config()), known)
    assert decision in (IdentityDecision.KNOWN_SKU, IdentityDecision.SKU_ALIAS)


def test_rename_without_sku_never_reads_as_platform_change():
    known = [sig(model="NucBox G5", **_config())]
    decision, _, _ = resolve_identity(sig(model="G5 Plus", **_config()), known)
    assert decision != IdentityDecision.PLATFORM_CHANGE


def test_alias_table_hit():
    known = [sig(alias="gmktec-k12-2026")]
    decision, conf, reasons = resolve_identity(sig(alias="gmktec-k12-2026"), known)
    assert decision == IdentityDecision.SKU_ALIAS
    assert any("alias" in r for r in reasons)


def test_family_extraction_strips_numbers_and_tier_words():
    assert extract_family("GMKtec K12 Mini PC AMD") == "gmktec"
    assert extract_family("Minisforum UM890 Pro") == "minisforum"
    assert extract_family("Beelink SER9").startswith("beelink")
    assert extract_family("Lenovo Legion Pro 7") == "lenovo-legion"


def test_cpu_generation_keys_distinguish_generations():
    assert cpu_generation_key("AMD Ryzen 7 7735HS") != \
        cpu_generation_key("AMD Ryzen 7 8845HS")
    assert cpu_generation_key("Intel Core i7-13620H") == "intel-13"
    assert cpu_generation_key("Intel Core i7-13620H") != \
        cpu_generation_key("Intel Core i7-14650HX")

"""Identity resolution v2 (campaign deliverable B).

Decides what a newly observed listing *is*, independent of URL churn.
Returns one of six decisions; UNKNOWN_SKU is the only decision that can
become an editorial NEW_SKU event.

Hierarchy (from the campaign contract):

    FAMILY -> MODEL -> SKU / HARDWARE CONFIGURATION -> REGIONAL LISTING -> URL

A new URL is not automatically a new SKU. A regional mirror is not a new
SKU. A RAM/storage variation is a variant, not new hardware. New silicon
beneath a reused family/model page is PLATFORM_CHANGE -- detectable and
review-worthy, even when the URL never changed.
"""

from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel, Field


class IdentityDecision(str, Enum):
    KNOWN_SKU = "known_sku"
    UNKNOWN_SKU = "unknown_sku"
    SKU_ALIAS = "sku_alias"
    SKU_VARIANT = "sku_variant"
    REGIONAL_ALIAS = "regional_alias"
    PLATFORM_CHANGE = "platform_change"


_TIER_WORDS = {"pro", "max", "ultra", "elite", "plus", "neo", "gtx", "ti"}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def extract_family(model: str) -> str:
    """Coarse family key: leading tokens up to the first digit-bearing token."""
    tokens = _slug(model).split("-") if model else []
    keep: list[str] = []
    for tok in tokens:
        if any(ch.isdigit() for ch in tok) or tok in _TIER_WORDS:
            break
        keep.append(tok)
    return "-".join(keep) if keep else _slug(model)


def memory_arch(memory: str | None) -> tuple[str, int] | None:
    """(type, capacity_gb band). Capacity is banded so 512GB->1TB stays one
    step of storage novelty while 16GB vs 32GB RAM is distinguishable but
    explicitly NOT editorially new hardware."""
    if not memory:
        return None
    m = re.search(r"(\d+)\s*(GB|TB)", memory.upper())
    if not m:
        return None
    qty = int(m.group(1))
    gb = qty * 1024 if m.group(2) == "TB" else qty
    kind = "DDR5" if "DDR5" in memory.upper() or "LPDDR5" in memory.upper() else (
        "DDR4" if "DDR4" in memory.upper() else ("SSD" if gb >= 128 else "OTHER"))
    return kind, gb


def cpu_generation_key(cpu: str | None) -> str | None:
    """Cheap deterministic generation proxy.

    AMD Ryzen mobile chips carry a 4-digit model like 7735HS/8845HS where the
    first digit is the generation class; Intel Core chips show 13xx/14xx/
    Ultra 9 185H style marks; simple SoCs (N100 etc.) are their own keys.
    """
    if not cpu:
        return None
    c = cpu.upper()
    m = re.search(r"RYZEN.*?(\d{4})", c)
    if m:
        return f"amd-zen{m.group(1)[0]}"
    m = re.search(r"(?:I[3579]|CORE\s*I[3579])[-\s]?(\d+)", c)
    if m:
        return f"intel-{m.group(1)[:2]}"
    m = re.search(r"ULTRA\s*[579]\s*(\d{1,2})\w*", c)
    if m:
        return f"intel-core-ultra-s{m.group(1)[:1]}"
    m = re.search(r"\b(N\d{2,3}|Celeron\s*\S+|Pentium\s*\S+)", c)
    if m:
        return f"soc-{_slug(m.group(1))}"
    return f"cpu-{_slug(c)}"


class IdentitySignals(BaseModel):
    """Everything the resolver may weigh. All optional except identity core."""

    manufacturer: str
    model: str
    vendor_sku: str | None = None
    alias: str | None = None          # known alias-space membership marker
    cpu_raw: str | None = None
    gpu_raw: str | None = None
    memory: str | None = None
    storage: str | None = None
    form_factor: str | None = None    # category, e.g. mini_pc / laptop
    region: str | None = None
    url: str | None = None

    @property
    def family(self) -> str:
        return extract_family(self.model)

    def config_signature(self) -> tuple:
        """Hardware-only signature. The model string is deliberately excluded:
        a marketing rename must not mask identical hardware."""
        return (
            self.manufacturer.lower(),
            _slug(self.cpu_raw or ""),
            _slug(self.gpu_raw or ""),
            memory_arch(self.memory),
            memory_arch(self.storage),
            self.form_factor,
        )


def resolve_identity(
    incoming: IdentitySignals,
    known: list[IdentitySignals],
) -> tuple[IdentityDecision, float, list[str]]:
    """Match cascade. Returns (decision, confidence, reasons).

    Order matters and each rule documents why it beats later ones:
      1 exact SKU on another URL/region   -> alias/regional (vendor truth)
      2 full config signature match       -> same hardware, page moved
      3 only memory/storage differ        -> variant, not news
      4 CPU generation differs            -> platform change under old name
    """
    reasons: list[str] = []
    best: tuple[IdentityDecision, float] = (IdentityDecision.UNKNOWN_SKU, 0.0)

    for k in known:
        # Rule 1: exact vendor SKU is authoritative regardless of URL/story.
        if k.vendor_sku and incoming.vendor_sku and k.vendor_sku == incoming.vendor_sku:
            regions_differ = (k.region and incoming.region
                              and k.region != incoming.region)
            urls_differ = bool(k.url and incoming.url and k.url != incoming.url)
            if regions_differ:
                reasons.append(f"exact sku {incoming.vendor_sku} re-sighted in region {k.region}")
                cand = (IdentityDecision.REGIONAL_ALIAS, 0.95)
            elif urls_differ:
                reasons.append(f"exact sku {incoming.vendor_sku} at new url")
                cand = (IdentityDecision.SKU_ALIAS, 0.95)
            else:
                reasons.append(f"exact sku {incoming.vendor_sku} matched")
                cand = (IdentityDecision.KNOWN_SKU, 1.0)
            if cand[1] >= best[1]:
                best = cand
            continue

        # Alias markers already recorded for this product.
        if incoming.alias and k.alias == incoming.alias:
            reasons.append("alias-table hit")
            if best[1] < 0.85:
                best = (IdentityDecision.SKU_ALIAS, 0.85)
            continue

        cfg_same = k.config_signature() == incoming.config_signature()
        fam_match = (k.family == incoming.family
                     and k.manufacturer.lower() == incoming.manufacturer.lower())
        cpu_in, cpu_k = cpu_generation_key(incoming.cpu_raw), cpu_generation_key(k.cpu_raw)

        if cfg_same and fam_match:
            reasons.append("full configuration signature matches known sku")
            if best[1] < 0.9:
                best = (IdentityDecision.KNOWN_SKU, 0.9)
            continue

        if cfg_same and not fam_match:
            # Same hardware re-listed under a different family/model string ->
            # rename / migration evidence handled at listing level.
            reasons.append("config match with divergent model naming")
            if best[1] < 0.75:
                best = (IdentityDecision.SKU_ALIAS, 0.75)
            continue

        if fam_match and cfg_same is False and cpu_in and cpu_in == cpu_k:
            mem_differs = memory_arch(incoming.memory) != memory_arch(k.memory)
            stor_differs = memory_arch(incoming.storage) != memory_arch(k.storage)
            if mem_differs or stor_differs:
                reasons.append(
                    "same family/platform, "
                    + ("memory" if mem_differs else "") + ("/" if mem_differs and stor_differs else "")
                    + ("storage" if stor_differs else "")
                    + " variation only")
                if best[1] < 0.8:
                    best = (IdentityDecision.SKU_VARIANT, 0.8)
            continue

        if fam_match and cpu_in and cpu_k and cpu_in != cpu_k:
            reasons.append(
                f"family reused across cpu generations {cpu_k}->{cpu_in}")
            if best[1] < 0.7:
                best = (IdentityDecision.PLATFORM_CHANGE, 0.7)

    if not known:
        reasons.append("no prior record for this manufacturer identity space")
    return best[0], best[1], reasons

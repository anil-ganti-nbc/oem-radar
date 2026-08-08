"""Lenovo PSREF EvidenceSource (Stage 11) — the first real implementation
of the `EvidenceSource` protocol, built after Lenovo (PSREF) and HP
(support product-category API) independently confirmed the same
architectural concept — official, public, enumerable, stable-identity
product intelligence outside a blocked/JS-hydrated storefront — firing
the trigger Stage 10 set and left unchanged. See `docs/PSREF_RECON.md`
for the full reconnaissance and `docs/EVIDENCE_ARCHITECTURE.md` for why
this is `EvidenceSource`, not a `SourceEngine`: PSREF's confirmed data
(identity + `Withdraw`/current-vs-discontinued status) is not a full
product entity — no price, no confirmed spec fields — so it is not
forced into `NormalizedProduct`.

Bulk-inline shape: one request (`ProductCategoryTree`) returns every
record. `fetch()` is a formality here (the payload already arrived via
`discover()`'s single request) — the same pattern `shopify`/`dell`/
`category_jsonld` use for their own bulk endpoints.
"""

from __future__ import annotations

import json
from typing import Iterable

from pydantic import BaseModel

from ...core.interfaces import Fetcher
from ...core.models import (
    EvidenceDocument,
    EvidenceItem,
    EvidenceKind,
    EvidenceProvenance,
    EvidenceRef,
)
from ...core.registry import evidence_sources


class LenovoPsrefConfig(BaseModel):
    base_url: str = "https://psref.lenovo.com"
    endpoint_path: str = "/api/ph/ProductCategoryTree"
    # PSREF's 1,544 records are full history, not just current products
    # (docs/PSREF_RECON.md: 952 withdrawn / 592 current). Default keeps
    # everything — a discontinuation is itself real editorial signal
    # (see the change-value matrix) — scoping to current-only is a config
    # knob, not a code change, matching every other engine's convention.
    include_withdrawn: bool = True


@evidence_sources.register("lenovo_psref")
class LenovoPsrefEvidenceSource:
    config_schema = LenovoPsrefConfig

    def __init__(self, cfg: LenovoPsrefConfig | None = None):
        self.cfg = cfg or LenovoPsrefConfig()

    def discover(self, fetcher: Fetcher) -> Iterable[EvidenceRef]:
        url = self.cfg.base_url.rstrip("/") + self.cfg.endpoint_path
        doc = fetcher.get(url)
        try:
            data = json.loads(doc.body)
        except (json.JSONDecodeError, TypeError, ValueError):
            return []

        refs: list[EvidenceRef] = []
        classifications = data.get("data", {}).get("ProductClassificationList", [])
        if not isinstance(classifications, list):
            return []
        for classification in classifications:
            for line in classification.get("ProductLineList", []) or []:
                for series in line.get("ProductSeriesList", []) or []:
                    for p in series.get("ProductList", []) or []:
                        key = p.get("ProductKey")
                        product_id = p.get("ProductID")
                        if not key or product_id is None:
                            continue  # no stable identity to anchor on — skip, don't guess
                        payload = dict(p)
                        payload["_classification"] = classification.get("ClassificationName")
                        payload["_line"] = line.get("ProductLine")
                        payload["_series"] = series.get("SeriesName")
                        product_line = line.get("ProductLine") or "Product"
                        refs.append(EvidenceRef(
                            external_id=str(product_id),
                            url=f"{self.cfg.base_url.rstrip('/')}/Product/{product_line}/{key}",
                            inline_payload=payload,
                        ))
        return refs

    def fetch(self, ref: EvidenceRef, fetcher: Fetcher) -> EvidenceDocument:
        return EvidenceDocument(
            url=ref.url, status=200,
            body=json.dumps(ref.inline_payload or {}),
            content_type="application/json",
        )

    def extract(self, doc: EvidenceDocument) -> list[EvidenceItem]:
        try:
            p = json.loads(doc.body)
        except (json.JSONDecodeError, TypeError, ValueError):
            return []
        if not isinstance(p, dict) or not p.get("ProductKey") or p.get("ProductID") is None:
            return []

        withdrawn = bool(p.get("Withdraw"))
        if withdrawn and not self.cfg.include_withdrawn:
            return []

        status_note = "Status: discontinued (Withdraw=1)" if withdrawn else "Status: current (Withdraw=0)"
        item = EvidenceItem(
            manufacturer="Lenovo",
            source_id="lenovo-psref",
            evidence_kind=EvidenceKind.PRODUCT_DATABASE,
            provenance=EvidenceProvenance.OFFICIAL_PRODUCT_DATABASE,
            canonical_url=doc.url,
            external_id=str(p["ProductID"]),
            model=p.get("ProductName"),
            family=p.get("_series"),
            title=p.get("ProductName"),
            description=status_note,
            raw_data=p,
        )
        return [item]

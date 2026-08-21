"""Stage 11: the Evidence Fusion v0.1 pipeline — discover -> fetch/extract
-> persist -> conservative identity link -> event.

Deliberately NOT merged into `core/pipeline.py::run_source`: evidence has
no snapshot/diff/severity-rule machinery, and a `NormalizedProduct` isn't
what an `EvidenceItem` is (see `docs/EVIDENCE_ARCHITECTURE.md`). Forcing
this through the product pipeline would mean stubbing out most of it for
no benefit — a small, parallel, honestly-separate pipeline is simpler and
more legible than one pipeline with two unrelated modes.

Scope boundary, deliberate: this does not enqueue a Discord notification.
`docs/STAGE11.md`/Track 6 asked for persistence, identity linking, and a
record of what changed — not full delivery + noise-suppression policy
(routine driver updates should stay quiet, per the stage's own
instruction), which needs real production experience this project doesn't
have yet for any evidence source.

Stage 11.1 correction: this originally called `store.record_event()`, so
every evidence observation became a row in `change_events` — i.e. a
product alert. That was wrong, and at production scale it was 44% of the
alert stream. An evidence observation now lands in `evidence_events`,
which is a log of what an evidence source saw, not a claim that a tracked
product changed. Evidence becomes a product alert only when a *product*
pipeline decides it does; that promotion path does not exist yet and is
not faked here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .interfaces import EvidenceSource, Fetcher
from .models import EvidenceCandidate, EvidenceCandidateType, EvidenceItem


@dataclass
class EvidenceRunStats:
    source_id: str
    discovered: int = 0
    new_items: int = 0
    updated_items: int = 0
    unchanged_items: int = 0
    linked: int = 0
    unlinked: int = 0
    events: int = 0
    candidates: list[EvidenceCandidate] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def candidates_for_evidence(
    item: EvidenceItem, product_key: str | None,
) -> list[EvidenceCandidate]:
    """Return conservative editorial-review candidates for an evidence item.

    A product database observation only yields a new-model candidate when it
    is current and has no exact link to a tracked product.  SKU and region are
    additional *evidence* candidates, never commercial alerts.  A withdrawn
    PSREF record is historical inventory, not a launch signal.
    """
    if item.evidence_kind.value != "product_database":
        return []
    if item.raw_data.get("Withdraw"):
        return []
    # PSREF enumerates its entire current catalogue.  `IsNewProduct` is the
    # only first-party freshness bit exposed by ProductCategoryTree; without
    # it, a first experimental run would manufacture hundreds of stale
    # "new-model" candidates.  Missing/false is intentionally conservative.
    if not item.raw_data.get("IsNewProduct"):
        return []
    common = dict(
        source_id=item.source_id, manufacturer=item.manufacturer,
        external_id=item.external_id, canonical_url=item.canonical_url,
        model=item.model, sku=item.sku, region=item.region,
        linked_product_key=product_key, published_at=item.published_at,
        novelty_reason="official_is_new_product",
    )
    # A regional availability signal is only meaningful when the identity is
    # already known.  An unlinked regional page is still model evidence, not
    # proof that an existing product newly reached that market.
    if item.region and product_key:
        return [EvidenceCandidate(
            candidate_type=EvidenceCandidateType.REGIONAL_PRODUCT_EVIDENCE,
            **common,
        )]
    if item.sku:
        return [EvidenceCandidate(
            candidate_type=EvidenceCandidateType.NEW_CONFIGURATION_EVIDENCE,
            **common,
        )]
    if product_key is None and item.model:
        return [EvidenceCandidate(
            candidate_type=EvidenceCandidateType.NEW_MODEL_EVIDENCE,
            **common,
        )]
    return []


def run_evidence_source(source_id: str, source: EvidenceSource, fetcher: Fetcher, store) -> EvidenceRunStats:
    stats = EvidenceRunStats(source_id=source_id)
    try:
        refs = list(source.discover(fetcher))
    except Exception as exc:  # a broken source must not crash the caller
        stats.errors.append(f"discover: {exc!r}")
        return stats
    stats.discovered = len(refs)

    for ref in refs:
        try:
            doc = source.fetch(ref, fetcher)
            items = source.extract(doc)
        except Exception as exc:
            stats.errors.append(f"{ref.url}: {exc!r}")
            continue

        for item in items:
            item_id, status = store.record_evidence_item(item)
            if status == "new":
                stats.new_items += 1
            elif status == "updated":
                stats.updated_items += 1
            else:
                stats.unchanged_items += 1
                continue  # identical facts re-observed: no link churn, no event

            product_key, method = store.resolve_evidence_link(item)
            store.link_evidence(item_id, product_key, method, 1.0 if product_key else 0.0)
            if product_key:
                stats.linked += 1
            else:
                stats.unlinked += 1

            candidates = candidates_for_evidence(item, product_key)
            stats.candidates.extend(candidates)

            store.record_evidence_event(
                item_id,
                "added" if status == "new" else "updated",
                meta={
                    "evidence_kind": item.evidence_kind.value,
                    "provenance": item.provenance.value,
                    "manufacturer": item.manufacturer,
                    "title": item.title,
                    "canonical_url": item.canonical_url,
                    "linked": bool(product_key),
                    "candidates": [c.model_dump(mode="json") for c in candidates],
                },
            )
            stats.events += 1

    return stats

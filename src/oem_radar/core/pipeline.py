"""Run orchestration: discover → fetch → parse → normalize → validate →
resolve → snapshot → diff → score → outbox.

Core knows engines/stores/notifiers only through protocols. This module is
deliberately boring — all intelligence lives in the stages it wires together.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from .config import SeverityRule, SourceConfig
from .diff import diff
from .interfaces import Fetcher, Notifier, SnapshotStore, SourceEngine
from .knownhw import canonicalize
from .models import ChangeEvent, ChangeType, FetchedDocument, NormalizedProduct, Severity

log = logging.getLogger("oem_radar.pipeline")


@dataclass
class SourceRunStats:
    source_id: str
    discovered: int = 0
    fetched: int = 0
    snapshots_written: int = 0
    unchanged: int = 0
    skipped: int = 0        # non-product listings dropped by fatal validation
    events: int = 0
    errors: list[str] = field(default_factory=list)


def _stamp_components(product: NormalizedProduct, store: SnapshotStore) -> None:
    """Canonicalize cpu/gpu/npu and mark against the known-hardware DB.
    Unseen components are learned immediately so the *second* sighting is
    no longer breaking news (DIFF_ENGINE.md §4)."""
    for kind in ("cpu", "gpu", "npu"):
        comp = getattr(product, kind)
        if comp is None:
            continue
        comp.canonical = canonicalize(comp.raw)
        if comp.canonical is None:
            comp.known = None  # can't judge; renderers must caveat, not guess
        else:
            comp.known = store.known_component(comp.canonical)


def _learn_components(product: NormalizedProduct, store: SnapshotStore) -> None:
    for kind in ("cpu", "gpu", "npu"):
        comp = getattr(product, kind)
        if comp is not None and comp.canonical and comp.known is False:
            store.learn_component(kind, comp.canonical, comp.raw)


def run_source(
    source: SourceConfig,
    engine: SourceEngine,
    fetcher: Fetcher,
    store: SnapshotStore,
    notifier: Notifier,
    rules: list[SeverityRule] | None = None,
    baseline: bool = False,
) -> SourceRunStats:
    """Crawl one source. Degrades per-product, never aborts the source;
    the caller wraps this in one storage transaction (ADR-1)."""
    stats = SourceRunStats(source_id=source.id)

    refs = list(engine.discover(fetcher))
    log.info("%s: %d product(s) discovered, processing...", source.id, len(refs))
    for ref in refs:
        stats.discovered += 1
        if stats.discovered % 25 == 0:
            log.info("%s: %d/%d processed (%d changed so far)",
                     source.id, stats.discovered, len(refs), stats.snapshots_written)
        try:
            if ref.inline_payload is not None:
                doc = FetchedDocument(
                    url=ref.url, status=200,
                    body=json.dumps(ref.inline_payload),
                    content_type="application/json",
                )
            else:
                doc = fetcher.get(ref.url)
                stats.fetched += 1
            raw = engine.parse(doc)
            product = engine.normalize(raw)
            issues = engine.validate(product)
            if any(i.fatal for i in issues):
                # Fatal = not a trackable product (non-product listing, empty
                # model). Skip entirely: no snapshot, no diff, no notification.
                # This is the accessories/"Contact US" filter (DESIGN_REVIEW).
                stats.skipped += 1
                continue
            if issues:  # non-fatal: keep, but lower confidence (parse gaps are
                product.confidence = min(product.confidence, 0.5)  # still signal
            _stamp_components(product, store)

            product_key = f"{source.id}:{ref.handle or ref.url}"
            before, relation = store.resolve_prior(product_key, product)

            if before is not None and before.content_hash() == product.content_hash():
                store.touch(product_key)
                stats.unchanged += 1
                continue

            store.append(product_key, product)
            stats.snapshots_written += 1

            events = diff(before, product, product_key, rules)
            unseen = any(
                getattr(product, k) is not None and getattr(product, k).known is False
                for k in ("cpu", "gpu", "npu")
            )
            for event in events:
                if baseline:
                    # First-ever crawl of this source: everything is "new" by
                    # definition. Record events for history, don't ping.
                    event.meta["baseline"] = True
                if event.change_type == ChangeType.NEW_PRODUCT:
                    if relation == "existing_product":
                        # A different listing already carries this identity:
                        # variant/duplicate, not a launch (ADR-3).
                        event.change_type = ChangeType.DUPLICATE_LISTING
                        event.severity = Severity.MINOR
                    if ref.hidden:
                        event.meta["hidden"] = True
                    if unseen:
                        event.meta["unseen_component"] = True
                notifier.enqueue(event, product)
                stats.events += 1
            _learn_components(product, store)
        except Exception as exc:  # degrade, log, continue (ARCHITECTURE.md §3)
            log.warning("source %s: %s failed: %r", source.id, ref.url, exc)
            stats.errors.append(f"{ref.url}: {exc!r}")

    return stats

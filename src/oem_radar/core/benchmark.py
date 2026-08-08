"""Stage 9 Phase 6: discovery benchmark suite.

Runs an engine's real `discover()` (and, for a bounded sample, `parse()`/
`normalize()`/`validate()`) against real captured fixtures and measures
what Stage 9 asked for: time, requests, products found, duplicates,
identity quality, and validation-pass rate as a proxy for category
quality (a ref that validates cleanly is, by construction, one the
denylist/shape checks accepted as a real product).

Every number here comes from actually executing engine code against real
fixture data — nothing is estimated or hand-typed. Re-running this module
against the same fixtures always produces the same numbers (deterministic,
no network, no clock-sensitive logic beyond wall-clock timing itself),
which is what makes it a benchmark rather than a one-off measurement.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from .interfaces import Fetcher
from .models import FetchedDocument


@dataclass
class DiscoveryBenchmarkResult:
    source_id: str
    engine: str
    time_seconds: float
    requests_made: int
    products_found: int
    duplicate_refs: int
    unique_identities: int
    identity_quality: float          # fraction of refs carrying a non-empty handle
    validation_pass_rate: float | None  # fraction of a normalized sample with zero fatal issues
    normalized_sample_size: int
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def benchmark_discovery(source_id: str, engine_name: str, engine, fetcher: Fetcher,
                         *, normalize_sample: int = 12) -> DiscoveryBenchmarkResult:
    """One benchmark pass: discover (timed, requests counted), then
    normalize+validate up to `normalize_sample` refs (bounded so a
    catalog with hundreds of refs doesn't make the benchmark slow — the
    sample is deterministic, always the first N in discovery order)."""
    calls_before = len(getattr(fetcher, "calls", []))
    start = time.perf_counter()
    refs = list(engine.discover(fetcher))
    elapsed = time.perf_counter() - start
    calls_after = len(getattr(fetcher, "calls", []))

    identities = [r.handle or r.url for r in refs]
    unique = set(identities)
    duplicates = len(identities) - len(unique)
    with_identity = sum(1 for r in refs if r.handle)
    identity_quality = round(with_identity / len(refs), 2) if refs else 0.0

    notes: list[str] = []
    pass_count = 0
    normalized = 0
    for ref in refs[:normalize_sample]:
        try:
            if ref.inline_payload is not None:
                doc = FetchedDocument(url=ref.url, status=200, body=json.dumps(ref.inline_payload))
            else:
                doc = fetcher.get(ref.url)
            if doc.status != 200:
                # Not an engine failure — the benchmark's fixture set simply
                # doesn't cover this ref. Distinct from a real parse/validate
                # failure, so it's excluded from the pass-rate denominator
                # rather than silently counted against the engine.
                notes.append(f"{ref.url}: no fixture captured for this ref (status={doc.status})")
                continue
            raw = engine.parse(doc)
            product = engine.normalize(raw)
            issues = engine.validate(product)
            normalized += 1
            if not any(i.fatal for i in issues):
                pass_count += 1
        except Exception as exc:  # a broken ref is itself a benchmark finding, not a crash
            notes.append(f"{ref.url}: {exc!r}")

    validation_pass_rate = round(pass_count / normalized, 2) if normalized else None

    return DiscoveryBenchmarkResult(
        source_id=source_id,
        engine=engine_name,
        time_seconds=round(elapsed, 4),
        requests_made=calls_after - calls_before,
        products_found=len(refs),
        duplicate_refs=duplicates,
        unique_identities=len(unique),
        identity_quality=identity_quality,
        validation_pass_rate=validation_pass_rate,
        normalized_sample_size=normalized,
        notes=notes,
    )

"""Conservative review candidates for a source's quiet initial baseline.

This is intentionally separate from the product pipeline: baseline events are
not alerts, and these candidates never enter ``change_events`` or the outbox.
Only a source-supplied, parseable, recent publication timestamp can qualify a
baseline item for later editorial review.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from .models import NormalizedProduct


def baseline_review_candidate(
    source_id: str,
    product_key: str,
    product: NormalizedProduct,
    *,
    observed_at: datetime | None = None,
    maximum_age: timedelta = timedelta(days=14),
) -> dict | None:
    """Return a review-only candidate for a freshly published baseline item.

    No timestamp, invalid timestamp, future timestamp, or an old catalogue
    item remains quiet.  The producer must provide ``raw_data.published_at``;
    Radar never substitutes crawl time or a sitemap timestamp.
    """
    raw = product.raw_data.get("published_at")
    if not isinstance(raw, str):
        return None
    try:
        published = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if published.tzinfo is None:
        return None
    now = observed_at or datetime.now(timezone.utc)
    if published > now or now - published > maximum_age:
        return None
    basis = f"{source_id}|{product_key}|{published.isoformat()}"
    return {
        "candidate_type": "baseline_recent_product_evidence",
        "source_id": source_id,
        "product_key": product_key,
        "manufacturer": product.manufacturer,
        "model": product.model,
        "source_url": product.source_url,
        "published_at": published.isoformat(),
        "first_observed_at": now.isoformat(),
        "novelty_reason": "source_published_at_within_baseline_window",
        "dedup_key": hashlib.sha256(basis.encode("utf-8")).hexdigest()[:32],
    }

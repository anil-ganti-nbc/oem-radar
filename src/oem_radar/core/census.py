"""Collector classification framework (campaign deliverable E).

Builds the collector census from ``crawler_runs`` history and classifies:

    runtime: FAST (<2m P95) | STANDARD (2-5m) | HEAVY (5-10m) | DAILY (>10m)
    yield:   HIGH_YIELD | NORMAL | LOW_YIELD | DEAD
    disposition: KEEP | DEMOTE | REWORK | REPLACE | DISABLE

HARD RULE enforced here: production P95 > 10 minutes => DAILY.

Evidence discipline: any dataset that is not the recovered authoritative
Hetzner history carries verification=UNVERIFIED_PENDING_HETZNER, and no
final production tier may be assigned from it. This module computes
machinery only; it never claims production truth from a local epoch.
"""

from __future__ import annotations

import json
import statistics
from datetime import datetime, timezone

from pydantic import BaseModel, Field

VERIFICATION_UNVERIFIED = "UNVERIFIED_PENDING_HETZNER"
VERIFICATION_AUTHORITATIVE = "HETZNER_HISTORY"

RUNTIME_BOUND_FAST_S = 120
RUNTIME_BOUND_STANDARD_S = 300
RUNTIME_BOUND_HEAVY_S = 600  # firm campaign requirement


class RuntimeClass:
    FAST = "FAST"
    STANDARD = "STANDARD"
    HEAVY = "HEAVY"
    DAILY = "DAILY"


class YieldClass:
    HIGH_YIELD = "HIGH_YIELD"
    NORMAL = "NORMAL"
    LOW_YIELD = "LOW_YIELD"
    DEAD = "DEAD"


class Disposition:
    KEEP = "KEEP"
    DEMOTE = "DEMOTE"
    REWORK = "REWORK"
    REPLACE = "REPLACE"
    DISABLE = "DISABLE"


def _pctl(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    k = min(len(sorted_vals) - 1, max(0, int(round((len(sorted_vals) - 1) * p))))
    return sorted_vals[k]


def classify_runtime(p95_runtime_s: float) -> str:
    if p95_runtime_s > RUNTIME_BOUND_HEAVY_S:
        return RuntimeClass.DAILY      # >10 min => once per day, by law
    if p95_runtime_s > RUNTIME_BOUND_STANDARD_S:
        return RuntimeClass.HEAVY
    if p95_runtime_s > RUNTIME_BOUND_FAST_S:
        return RuntimeClass.STANDARD
    return RuntimeClass.FAST


def classify_yield(
    editorial_candidates_total: int,
    successful_runs: int,
) -> str:
    """Editorial yield per successful run. Thresholds deliberately blunt;
    refinement requires authoritative history."""
    if successful_runs <= 0:
        return YieldClass.DEAD
    rate = editorial_candidates_total / successful_runs
    if rate >= 0.05:
        return YieldClass.HIGH_YIELD
    if rate > 0:
        return YieldClass.NORMAL
    return YieldClass.LOW_YIELD


class SourceCensus(BaseModel):
    source_key: str
    runs: int
    ok_runs: int
    failed_runs: int
    success_rate: float
    blocked_rate: float                  # fraction of failed mentioning 403/forbidden
    median_runtime_s: float
    p90_runtime_s: float
    p95_runtime_s: float
    max_runtime_s: float
    products_seen_max: int               # last observed catalog size
    new_skus_observed: int
    editorial_candidates: int
    last_success_at: str | None
    runtime_class: str
    yield_class: str
    disposition: str
    verification: str = VERIFICATION_UNVERIFIED
    notes: list[str] = Field(default_factory=list)


def _blocked_count(failed_stats: list[dict]) -> int:
    blocked = 0
    for s in failed_stats:
        blob = json.dumps(s).lower()
        if "403" in blob or "forbidden" in blob:
            blocked += 1
    return blocked


def classify_source(
    rows: list[dict],
    verification: str = VERIFICATION_UNVERIFIED,
) -> SourceCensus:
    """rows: dicts shaped like crawler_runs:
    {source_key, started_at, finished_at, status, stats_json}"""
    ok_rows = [r for r in rows if r.get("status") == "ok"]
    failed_rows = [r for r in rows if r.get("status") == "failed"]
    runtimes: list[float] = []
    products_seen = 0
    new_skus = 0
    for r in ok_rows:
        try:
            s = json.loads(r.get("stats_json") or "{}")
        except json.JSONDecodeError:
            s = {}
        st, fin = r.get("started_at"), r.get("finished_at")
        if st and fin:
            dur = (datetime.fromisoformat(fin) - datetime.fromisoformat(st)).total_seconds()
            if dur >= 0:
                runtimes.append(dur)
        products_seen = max(products_seen, int(s.get("discovered") or 0))
        # events counted as candidates only when flagged editorial upstream;
        # raw `events` is observation volume, not editorial yield.
        new_skus += int(s.get("editorial_new_skus") or 0)
    rt_sorted = sorted(runtimes)
    p95 = _pctl(rt_sorted, 0.95)
    success_rate = len(ok_rows) / len(rows) if rows else 0.0
    blocked_rate = (_blocked_count(failed_rows) / len(failed_rows)) if failed_rows else 0.0
    last_success = max(
        (r["finished_at"] or r["started_at"] for r in ok_rows), default=None)
    yc = classify_yield(new_skus, len(ok_rows))

    notes: list[str] = []
    rc = classify_runtime(p95)
    if verification == VERIFICATION_UNVERIFIED and rt_sorted:
        notes.append("runtime distribution measured on non-authoritative data")

    dispositions = {
        (RuntimeClass.DAILY, YieldClass.HIGH_YIELD): (Disposition.DEMOTE, "slow but valuable -> daily slot"),
        (RuntimeClass.HEAVY, YieldClass.LOW_YIELD): (Disposition.REWORK, "expensive with nothing to show"),
        (RuntimeClass.FAST, YieldClass.HIGH_YIELD): (Disposition.KEEP, "cheap and productive"),
        (RuntimeClass.FAST, YieldClass.NORMAL): (Disposition.KEEP, "healthy"),
        (RuntimeClass.STANDARD, YieldClass.NORMAL): (Disposition.KEEP, "healthy"),
        (RuntimeClass.STANDARD, YieldClass.HIGH_YIELD): (Disposition.KEEP, "productive"),
        (RuntimeClass.FAST, YieldClass.LOW_YIELD): (Disposition.REPLACE, "fast yet zero editorial yield"),
        (RuntimeClass.STANDARD, YieldClass.LOW_YIELD): (Disposition.REWORK, "moderate cost, no yield"),
        (RuntimeClass.HEAVY, YieldClass.NORMAL): (Disposition.DEMOTE, "healthy but watch runtime"),
        (RuntimeClass.HEAVY, YieldClass.HIGH_YIELD): (Disposition.DEMOTE, "valuable but expensive"),
        (RuntimeClass.DAILY, YieldClass.NORMAL): (Disposition.DEMOTE, "over cadence for its value"),
        (RuntimeClass.DAILY, YieldClass.LOW_YIELD): (Disposition.DISABLE, "expensive dead weight"),
        (RuntimeClass.DAILY, YieldClass.DEAD): (Disposition.DISABLE, "dead and expensive"),
    }
    disp, note = dispositions.get((rc, yc), (Disposition.REWORK, "needs evidence-based review"))
    if yc == YieldClass.DEAD and failed_rows and not ok_rows:
        disp, note = Disposition.REWORK, "no successful run recorded"
    if yc == YieldClass.LOW_YIELD and ok_rows and success_rate < 0.5:
        disp, note = Disposition.REPLACE, "unreliable and unproductive"

    return SourceCensus(
        source_key=str(rows[0].get("source_key")) if rows else "?",
        runs=len(rows),
        ok_runs=len(ok_rows),
        failed_runs=len(failed_rows),
        success_rate=round(success_rate, 3),
        blocked_rate=round(blocked_rate, 3),
        median_runtime_s=round(statistics.median(runtimes), 1) if runtimes else 0.0,
        p90_runtime_s=round(_pctl(rt_sorted, 0.90), 1),
        p95_runtime_s=round(p95, 1),
        max_runtime_s=round(max(runtimes), 1) if runtimes else 0.0,
        products_seen_max=products_seen,
        new_skus_observed=new_skus,
        editorial_candidates=new_skus,
        last_success_at=last_success,
        runtime_class=rc,
        yield_class=yc,
        disposition=disp,
        verification=verification,
        notes=[*notes, f"{note}: {disp}"],
    )

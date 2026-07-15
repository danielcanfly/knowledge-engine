from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from typing import Any

from . import m23_7_5_live_shadow as live_shadow

SCHEMA_VERSION = "knowledge-engine-m23-7-5-latency-diagnostic/v1"
CANONICAL_MAX_SHADOW_P95_MS = live_shadow.MAX_SHADOW_P95_MS
DIAGNOSTIC_MAX_SHADOW_P95_MS = 30_000


def _sha(value: Any) -> str:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def run_latency_diagnostic(
    client: live_shadow.LiveShadowClient,
    *,
    clock_ns: Callable[[], int] = time.perf_counter_ns,
) -> dict[str, Any]:
    """Run the real bounded observation while preserving rejected latency evidence.

    The temporary diagnostic ceiling exists only so the canonical runner can construct
    its already-redacted report. Acceptance is still evaluated against the unchanged
    canonical 1200 ms shadow p95 and 25 ms dispatch-overhead budgets.
    """

    original_limit = live_shadow.MAX_SHADOW_P95_MS
    try:
        live_shadow.MAX_SHADOW_P95_MS = DIAGNOSTIC_MAX_SHADOW_P95_MS
        observed = live_shadow.run_bounded_observation(client, clock_ns=clock_ns)
    finally:
        live_shadow.MAX_SHADOW_P95_MS = original_limit

    metrics = observed["metrics"]
    violations: list[str] = []
    if metrics["error_rate"] > 0.0:
        violations.append("error-rate")
    if metrics["shadow_p95_ms"] > CANONICAL_MAX_SHADOW_P95_MS:
        violations.append("shadow-latency")
    if metrics["primary_dispatch_overhead_p95_ms"] > live_shadow.MAX_PRIMARY_DISPATCH_OVERHEAD_MS:
        violations.append("primary-dispatch-overhead")

    receipt = {
        **observed,
        "schema_version": SCHEMA_VERSION,
        "status": "pass" if not violations else "rejected",
        "acceptance": {
            "canonical_max_shadow_p95_ms": CANONICAL_MAX_SHADOW_P95_MS,
            "canonical_max_primary_dispatch_overhead_ms": (
                live_shadow.MAX_PRIMARY_DISPATCH_OVERHEAD_MS
            ),
            "diagnostic_ceiling_ms": DIAGNOSTIC_MAX_SHADOW_P95_MS,
            "budget_violations": violations,
            "canonical_budget_changed": False,
        },
    }
    receipt.pop("live_shadow_sha256", None)
    receipt["latency_diagnostic_sha256"] = _sha(receipt)
    return receipt

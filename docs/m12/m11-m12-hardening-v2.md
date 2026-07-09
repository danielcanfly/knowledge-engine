# M11/M12 Hardening v2

Status: implementation candidate  
Issue: #171  
Baseline: `56b8b8787b72d1eaea36a0e1dabd71748ca406ff`

## Purpose

This hardening layer preserves all existing v1 artifacts for replay while introducing explicit v2 semantics for closure, coverage, claim alignment, and final release eligibility.

## M11 semantic closure matrix

The v1 M11 invariant matrix mixed positive and negative observations in one boolean map. For example, `canonical_source_written: false` represented a successful outcome even though a generic `all(values)` interpretation would treat it as failure.

`compiler_m11_closure_v2.py` converts every invariant into an explicit check:

```json
{
  "name": "canonical_source_written",
  "expected": false,
  "observed": false,
  "passed": true,
  "evidence_ref": "...#/invariants/canonical_source_written"
}
```

`all_passed` is derived exclusively from each check's `passed` field. A legacy matrix with incomplete coverage or any unexpected observation fails closed.

## Retrieval and citation coverage floors

`retrieval_citation_metrics_v2.py` reuses the deterministic v1 metrics, then requires minimum suite coverage for:

- total cases;
- answered cases;
- cited results;
- expected concepts;
- citation expectations;
- zero-result probes.

A suite cannot pass merely because every denominator is empty. Coverage counts, floors, and per-floor checks are included in the stable artifact identity.

## Claim-level answer alignment

`answer_performance_metrics_v2.py` replaces aggregate-only answer observations with claim-level records. Every claim includes:

- stable claim ID;
- claim-text SHA-256;
- support status;
- expected fact IDs;
- citation source IDs;
- unsupported reason when applicable;
- contradiction evidence IDs;
- unknown-handling evidence IDs.

Supported claims require both expected facts and citations. Contradicted and unsupported claims require explicit reasons. Unknown claims require explicit unknown evidence. The evaluator computes faithfulness, completeness, unsupported-claim rate, contradiction handling, unknown handling, response stability, latency, token cost, index load, and cache-hit rate from these records.

Coverage floors require minimum cases, claims, supported claims, cited claims, contradiction probes, unknown probes, and samples per case.

## Strict final gate v2

`m12_final_gate_v2.py` requires exactly three top-level artifact families:

```text
rqdecision_  -> M12.4
rcmetrics2_  -> M12.5 v2
apmetrics2_  -> M12.6 v2
```

It also inspects the nested M12.4 evidence references and requires real families for:

```text
qeval_             -> M12.1
gqreport_          -> M12.2
gqbaselinecheck_   -> M12.3
```

Artifact counts are no longer used as a proxy for milestone completion. Unknown, missing, duplicate, stale, failed, release-blocking, release-drifted, manifest-drifted, coverage-failing, claim-alignment-free, audience-broadening, raw-fallback, or governance-broadening evidence blocks eligibility.

## Compatibility and governance

Existing v1 artifacts and APIs remain available for deterministic replay. New production-quality evaluation should use the v2 artifacts.

All hardening modules retain the no-write boundary:

```text
canonical_source_write_permitted: false
source_pr_creation_permitted: false
candidate_write_permitted: false
release_write_permitted: false
production_write_permitted: false
rollback_permitted: false
permanent_ledger_append_permitted: false
```

No canonical Source, candidate, release, production pointer, rollback, or permanent ledger mutation occurs.

## Test organization

Shared M12 fixtures now live in `tests/fixtures/m12_hardening.py`. The previous monolithic M12 test module is reduced to v1 compatibility coverage, while `tests/test_m11_m12_hardening_v2.py` covers all v2 hardening conditions. The M12-specific Ruff `I001` exception is removed.

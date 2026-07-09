# M12.5 Deterministic Retrieval and Citation Metrics

Status: implementation candidate  
Issue: #167  
Depends on: M12.4 issue #165 / PR #166  
Engine baseline: `cfc782fa2123ecaa15648a4b976500ce35a7ed10`

## Purpose

M12.5 turns one exact M12.2 golden query report plus explicit per-case expectations into deterministic retrieval and citation quality evidence. It consumes only ACL-filtered result payloads already present in the golden report. It does not inspect hidden candidates, raw evidence, canonical Source, or unauthorized audience material.

## Retrieval metrics

The artifact reports:

- expected-concept hit rate;
- selected precision;
- false-positive rate;
- zero-result correctness;
- raw-fallback rate;
- total ACL-filtered count.

Expectations explicitly identify relevant concepts, required concepts, and zero-result cases. Expected concepts must be a subset of relevant concepts. A zero-result case cannot simultaneously define expected results.

## Citation metrics

The artifact reports:

- citation presence across selected results;
- citation support precision across cited relevant results;
- per-citation target correctness against explicit source allowlists;
- citation coverage across relevant selected results.

Citation source allowlists are declared per concept. Missing source IDs, malformed citations, incomplete case coverage, duplicate case IDs, raw fallback, or threshold regression fail closed.

## Determinism and governance

The expectation set, release identity, metrics, thresholds, case metrics, and failure reasons form a canonical stable-JSON identity. Exact replay produces the same `rcmetricset_` and `rcmetrics_` identities.

The artifact always carries the existing M12 no-write governance boundary:

```text
canonical_source_write_permitted: false
source_pr_creation_permitted: false
candidate_write_permitted: false
release_write_permitted: false
production_write_permitted: false
rollback_permitted: false
permanent_ledger_append_permitted: false
```

No Source, candidate, release, production pointer, rollback, or permanent ledger mutation occurs.

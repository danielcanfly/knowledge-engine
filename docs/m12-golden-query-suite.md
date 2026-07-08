# M12.2 Golden Query Suite

M12.2 extends the single-query runtime evaluation evidence from M12.1 into a deterministic golden query suite. The suite is an offline evaluation surface for runtime query quality. It does not write canonical Source, create release candidates, promote production, roll back production, or append the permanent audit ledger.

## Case contract

Each `GoldenQueryCase` declares the expected runtime behavior for one query:

```python
GoldenQueryCase(
    case_id="m12-answer-internal-knowledge-compiler",
    query="knowledge compiler",
    audiences=frozenset({"public", "internal"}),
    expected_status="answered",
    min_selected_results=1,
    required_concepts=frozenset({"concepts/knowledge-compiler"}),
    forbidden_concepts=frozenset(),
    expected_reasons=frozenset(),
    release_blocking=False,
)
```

The runner executes cases only through the ACL-aware `Runtime.query(...)` surface. It never inspects hidden retrieval candidates or raw evidence outside the response already authorized for the caller audience.

## Deterministic identities

The suite emits stable identities:

- `gqcase_<sha256-prefix>` for each case contract;
- `gqsuite_<sha256-prefix>` for the sorted suite contract;
- `gqrun_<sha256-prefix>` for each case result;
- `gqreport_<sha256-prefix>` for the aggregate report.

The same release, suite cases, query responses, evaluation evidence, and expected outcomes produce the same report. Case ordering is normalized by `case_id`, so replay is idempotent.

## Fail-closed checks

A case fails closed when any of these stable reasons occur:

- `status_mismatch`;
- `insufficient_selected_results`;
- `required_concept_missing`;
- `forbidden_concept_returned`;
- `evaluation_reasons_mismatch`;
- `release_blocking_mismatch`;
- `unexpected_release_blocking_evaluation`.

The aggregate report sets `passed=false` and `release_blocking=true` whenever any case fails. This makes the suite suitable as a release-blocking evaluation gate in later M12 slices without weakening the per-query gate from M12.1.

## Governance boundary

M12.2 is evaluation-only. It records deterministic evidence around runtime answers and non-answers, including ACL-filtered behavior and citation gate results. It does not mutate canonical Source, candidate releases, production pointers, rollback state, or permanent audit ledgers.

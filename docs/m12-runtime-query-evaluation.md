# M12 Runtime Query Evaluation

M12.1 adds a deterministic runtime query evaluation contract. The evaluator runs after ACL filtering and before serialization, so it only sees the results the caller is already authorized to receive.

## Evaluation evidence

Every `/v1/query` response now includes an `evaluation` object:

```json
{
  "schema_version": "1.0",
  "evaluation_id": "qeval_<sha256-prefix>",
  "passed": true,
  "release_blocking": false,
  "reasons": [],
  "metrics": {
    "candidate_count": 1,
    "selected_count": 1,
    "citation_count": 1,
    "citation_coverage": 1.0,
    "acl_filtered_count": 0,
    "raw_fallback_used": false
  },
  "policy": {
    "min_selected_for_answer": 1,
    "min_citation_coverage": 1.0,
    "raw_fallback_allowed": false
  }
}
```

The `evaluation_id` is derived from stable JSON containing release identity, query, sorted audiences, answer status, metrics, reasons, and policy. The same release, query, audiences, results, and retrieval metadata produce the same evaluation artifact.

## Fail-closed rules

The evaluator marks `passed=false` and `release_blocking=true` when any stable reason is present:

- `raw_fallback_disallowed` when raw fallback is used;
- `insufficient_selected_results` when an answered response has fewer selected results than policy allows;
- `insufficient_citation_coverage` when an answered response lacks citation coverage;
- `no_authorized_match` for authorized non-answers;
- `no_retrieval_candidates` when no post-ACL candidates remain.

These rules are intentionally strict for M12.1. Later M12 slices can add graded evaluation dimensions, golden query suites, and offline aggregate reports without weakening this runtime gate.

## Governance boundary

M12.1 does not write canonical Source, create candidates, request releases, promote production, roll back production, or append the permanent audit ledger. It only adds runtime response evidence and tests around existing release artifacts.

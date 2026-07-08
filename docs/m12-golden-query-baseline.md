# M12.3 Golden Query Baseline Gate

M12.3 turns the M12.2 golden query suite report into an immutable runtime quality floor. The gate is evaluation-only: it compares a deterministic `gqreport_` payload to an approved `GoldenQueryBaseline` contract and emits a replayable `gqbaselinecheck_` artifact.

## Baseline contract

A `GoldenQueryBaseline` records:

- the exact `gqsuite_` identity;
- the exact release ID and manifest SHA-256 evaluated by the suite;
- minimum passed-case count;
- maximum failed-case count;
- maximum release-blocking evaluation count;
- required case IDs;
- allowed failure reasons, when an intentionally failing suite is under review;
- the approved audience set;
- non-empty reviewer notes.

The baseline is immutable input. Updating the quality floor in a future slice requires a new explicit baseline, not silent mutation of prior evidence.

## Fail-closed checks

`evaluate_golden_query_baseline(...)` returns `passed=false` and `release_blocking=true` for stable reasons including:

- `suite_id_mismatch`;
- `release_id_mismatch`;
- `manifest_sha256_mismatch`;
- `passed_count_regression`;
- `failed_count_regression`;
- `release_blocking_count_regression`;
- `required_case_missing`;
- `unexpected_failure_reason`;
- `audience_broadening`;
- `unexpected_report_release_blocking`.

This keeps quality regression, identity drift, ACL/audience broadening, and release-blocking surprises from becoming ambiguous reviewer judgment calls.

## Deterministic identities

The gate emits:

- `gqbaseline_<sha256-prefix>` for the baseline contract;
- `gqbaselinecheck_<sha256-prefix>` for the report-vs-baseline check.

The same baseline and same suite report produce the same check artifact. Replays are idempotent and collision-resistant through stable sorted JSON hashing.

## Governance boundary

M12.3 does not write canonical Source, create candidates, publish releases, update production pointers, roll back production, or append the permanent audit ledger. The check explicitly records those write permissions as false so downstream orchestration can treat the artifact as release-blocking evaluation evidence only.
